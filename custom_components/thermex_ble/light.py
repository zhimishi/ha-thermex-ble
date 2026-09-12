"""Light platform for the Thermex hood."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from . import ThermexConfigEntry
from .entity import ThermexEntity

# Home Assistant uses 0-255 for brightness; the hood uses 0-100.
HOOD_RANGE = (1, 100)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThermexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ThermexLight(entry.runtime_data)])


class ThermexLight(ThermexEntity, LightEntity):
    """The hood's dimmable work light."""

    _attr_translation_key = "hood_light"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.address}_light"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.light_on

    @property
    def brightness(self) -> int | None:
        state = self.coordinator.data
        if state is None or not state.light_on:
            return None
        return round(state.brightness * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            level = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            level = max(1, min(100, level))
        else:
            # Restore the previous level if we know it, otherwise go full.
            state = self.coordinator.data
            level = state.brightness if state and state.brightness else 100
        await self.coordinator.async_set_light(level)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_light(0)
