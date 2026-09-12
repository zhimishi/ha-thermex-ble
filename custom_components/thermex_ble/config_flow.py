"""Config flow for Thermex BLE.

The hood stops advertising the moment anything connects to it, and it was never
seen advertising its 0xFF00 service UUID at all. Bluetooth discovery is
therefore offered opportunistically but the manual path - typing the MAC - is
the one users will normally take.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import format_mac
from thermex_ble import ThermexHood

from .const import DOMAIN


class ThermexConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Thermex hood."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_address: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a hood that happened to be advertising."""
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._discovered_address = discovery_info.address
        self.context["title_placeholders"] = {"name": discovery_info.name or "Thermex"}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovered_address is not None
        if user_input is not None:
            return await self._async_validate_and_create(self._discovered_address)

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"address": self._discovered_address},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup: the user supplies the MAC address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(format_mac(address), raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self._async_validate_and_create(address, errors)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )

    async def _async_validate_and_create(
        self, address: str, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Prove we can actually talk to the hood before creating the entry."""
        errors = errors if errors is not None else {}
        hood = ThermexHood(address)
        try:
            await hood.connect()
            reachable = hood.state is not None and hood.state.unlocked
        except Exception:  # noqa: BLE001 - bleak raises a wide range here
            reachable = False
        finally:
            await hood.disconnect()

        if not reachable:
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required(CONF_ADDRESS, default=address): str}),
                errors=errors,
            )

        return self.async_create_entry(
            title="Thermex Range Hood",
            data={CONF_ADDRESS: address},
        )
