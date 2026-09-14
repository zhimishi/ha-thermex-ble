"""The Thermex Range Hood (BLE) integration."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .coordinator import ThermexCoordinator

PLATFORMS: list[Platform] = [Platform.FAN, Platform.LIGHT]

type ThermexConfigEntry = ConfigEntry[ThermexCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ThermexConfigEntry) -> bool:
    """Set up a hood from a config entry."""
    coordinator = ThermexCoordinator(hass, entry.data[CONF_ADDRESS])
    await coordinator.async_setup()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ThermexConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
        # Give the proxy and hood time to resume advertising before reload.
        await asyncio.sleep(1.5)
    return unloaded
