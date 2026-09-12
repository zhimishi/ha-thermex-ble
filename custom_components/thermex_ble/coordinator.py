"""Connection coordinator for a Thermex hood."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from thermex_ble import HoodState, ThermexHood

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ThermexCoordinator(DataUpdateCoordinator[HoodState]):
    """Owns the BLE link and fans state changes out to entities.

    There is deliberately no update interval. The hood pushes a status frame
    roughly once a second over its notify characteristic, so polling would only
    add contention on a radio link that allows a single connection.
    """

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} {address}", update_interval=None)
        self.address = address
        self.hood: ThermexHood | None = None
        self._unregister = None

    async def async_setup(self) -> None:
        """Resolve the device and open the connection."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address.upper(), connectable=True
        )
        if ble_device is None:
            # Home Assistant can only hand bleak a device it has heard
            # advertise. This hood goes quiet while connected, so after a
            # restart the cache may be empty until it is power-cycled.
            # Raising ConfigEntryNotReady makes HA retry with backoff, which
            # picks the hood up as soon as it advertises again.
            raise ConfigEntryNotReady(
                f"Thermex hood {self.address} has not been seen advertising yet. "
                "Power-cycle the hood, and make sure no phone is connected to it."
            )

        self.hood = ThermexHood(ble_device)
        self._unregister = self.hood.register_callback(self._handle_state)

        try:
            await self.hood.connect()
        except Exception as err:  # noqa: BLE001 - bleak raises a wide range
            raise ConfigEntryNotReady(
                f"Could not connect to Thermex hood at {self.address}: {err}"
            ) from err

    async def async_shutdown(self) -> None:
        if self._unregister is not None:
            self._unregister()
            self._unregister = None
        if self.hood is not None:
            await self.hood.disconnect()
            self.hood = None
        await super().async_shutdown()

    @callback
    def _handle_state(self, state: HoodState) -> None:
        # Locked frames carry no state. They arrive once per connection, before
        # the unlock write lands; publishing them would blink every entity off.
        if not state.unlocked:
            return
        self.async_set_updated_data(state)

    async def async_set_fan(self, speed: int) -> None:
        assert self.hood is not None
        await self.hood.set_fan(speed)

    async def async_set_light(self, brightness: int) -> None:
        assert self.hood is not None
        await self.hood.set_light(brightness)
