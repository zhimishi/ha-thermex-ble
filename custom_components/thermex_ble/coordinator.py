"""Maintain the Thermex BLE connection and publish current hood state."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from thermex_ble import HoodState, ThermexHood

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
HEALTH_CHECK_INTERVAL = 5.0
CONNECT_TIMEOUT = 60.0
DISCONNECT_TIMEOUT = 25.0
COMMAND_TIMEOUT = 10.0
RETRY_INITIAL = 5.0
RETRY_MAX = 60.0


class ThermexCoordinator(DataUpdateCoordinator[HoodState]):
    """Keep one BLE link alive, without polling or replaying user commands.

    The hood reports its state through notifications. An idle but connected
    hood remains available; the watchdog handles missing disconnect callbacks.
    """

    def __init__(
        self, hass: HomeAssistant, address: str, *, config_entry: ConfigEntry | None = None
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {address}",
            update_interval=None,
        )
        self.address = address
        self.hood: ThermexHood | None = None
        self._unregister: list[Callable[[], None]] = []
        self._operation_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._monitor_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._last_state_at: float | None = None
        self._needs_reconnect = True

    async def async_setup(self) -> None:
        """Connect initially; Home Assistant retries failed entry setup."""
        try:
            await self._async_connect()
        except (Exception, asyncio.CancelledError) as err:
            await self.async_shutdown()
            if isinstance(err, asyncio.CancelledError):
                raise
            raise ConfigEntryNotReady(
                f"Could not connect to Thermex hood at {self.address}: {err}"
            ) from err
        self._monitor_task = self.hass.async_create_background_task(
            self._async_monitor(), f"{DOMAIN} reconnect {self.address}"
        )

    def _healthy(self) -> bool:
        return (
            not self._needs_reconnect
            and self.hood is not None
            and self.hood.is_connected
            and self._last_state_at is not None
        )

    async def _async_connect(self) -> None:
        async with self._operation_lock:
            if self._stopping:
                return
            await self._async_disconnect()
            # Resolve again after every outage: the proxy and its BLEDevice
            # details may have changed. Never reconnect using the old object.
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address.upper(), connectable=True
            )
            if ble_device is None:
                raise UpdateFailed(f"No available Bluetooth route to {self.address}")
            hood = self.hood = ThermexHood(ble_device)
            self._unregister = [
                hood.register_callback(lambda state: self._handle_state(hood, state)),
            ]
            # Older cached library versions have no disconnect subscription;
            # the periodic watchdog still detects their disconnected links.
            register_disconnect = getattr(hood, "register_disconnect_callback", None)
            if register_disconnect is not None:
                self._unregister.append(register_disconnect(lambda: self._handle_disconnect(hood)))
            async with asyncio.timeout(CONNECT_TIMEOUT):
                await hood.connect()
            if not hood.is_connected or hood.state is None or not hood.state.unlocked:
                raise UpdateFailed("No unlocked status received from the hood")
            self._needs_reconnect = False
            self._handle_state(hood, hood.state)

    async def _async_disconnect(self) -> None:
        for unregister in self._unregister:
            unregister()
        self._unregister.clear()
        self._needs_reconnect = True
        self._last_state_at = None
        if self.hood is not None:
            # Keep the old hood if cleanup fails. The next attempt retries its
            # cleanup before opening a new link on this single-client device.
            async with asyncio.timeout(DISCONNECT_TIMEOUT):
                await self.hood.disconnect()
            self.hood = None

    async def _async_monitor(self) -> None:
        delay = HEALTH_CHECK_INTERVAL
        retry_delay = RETRY_INITIAL
        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except TimeoutError:
                pass
            self._wake.clear()
            if self._stopping:
                return
            if self._healthy():
                delay = HEALTH_CHECK_INTERVAL
                retry_delay = RETRY_INITIAL
                continue
            self._mark_unavailable("Bluetooth connection lost")
            try:
                await self._async_connect()
            except Exception as err:  # bleak can raise several backend-specific errors
                self._mark_unavailable(str(err))
                _LOGGER.debug("Reconnect to %s failed", self.address, exc_info=True)
                # A disconnect during setup must not bypass the retry delay.
                self._wake.clear()
                delay = retry_delay
                retry_delay = min(retry_delay * 2, RETRY_MAX)
            else:
                _LOGGER.info("Reconnected to Thermex hood %s", self.address)
                delay = HEALTH_CHECK_INTERVAL
                retry_delay = RETRY_INITIAL

    async def async_shutdown(self) -> None:
        """Stop retries before releasing the link; safe to call more than once."""
        if self._stopping:
            return
        self._stopping = True
        task, self._monitor_task = self._monitor_task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        try:
            async with self._operation_lock:
                await self._async_disconnect()
        except Exception:
            _LOGGER.warning("Could not release Thermex link during shutdown", exc_info=True)
        finally:
            await super().async_shutdown()

    @callback
    def _mark_unavailable(self, reason: str) -> None:
        self._needs_reconnect = True
        self.async_set_update_error(UpdateFailed(reason))

    @callback
    def _handle_disconnect(self, hood: ThermexHood) -> None:
        if self._stopping or hood is not self.hood:
            return
        self._mark_unavailable("Bluetooth connection lost")
        self._wake.set()

    @callback
    def _handle_state(self, hood: ThermexHood, state: HoodState) -> None:
        # Ignore late frames from retired links and the initial locked frame.
        if self._stopping or hood is not self.hood or not state.unlocked:
            return
        self._last_state_at = self.hass.loop.time()
        if not self._needs_reconnect and hood.is_connected:
            self.async_set_updated_data(state)

    @callback
    def _check_available(self) -> None:
        if self._stopping or not self._healthy():
            if not self._stopping:
                self._mark_unavailable("Bluetooth connection is not ready")
                self._wake.set()
            raise HomeAssistantError("Thermex hood is unavailable; reconnecting automatically")

    async def _async_command(self, method: str, value: int) -> None:
        # Reject commands during recovery without waiting behind a connection
        # attempt and unexpectedly executing them much later.
        self._check_available()
        async with self._operation_lock:
            self._check_available()
            assert self.hood is not None
            try:
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    await getattr(self.hood, method)(value)
            except Exception as err:
                self._mark_unavailable(f"Command failed: {err}")
                self._wake.set()
                # Do not replay: a write can succeed on the hood before its
                # acknowledgement is lost, or become obsolete during recovery.
                raise HomeAssistantError(
                    "Thermex command failed; reconnecting automatically"
                ) from err

    async def async_set_fan(self, speed: int) -> None:
        await self._async_command("set_fan", speed)

    async def async_set_light(self, brightness: int) -> None:
        await self._async_command("set_light", brightness)
