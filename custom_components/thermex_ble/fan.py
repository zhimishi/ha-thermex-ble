"""Fan platform for the Thermex hood."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)
from thermex_ble import MAX_SPEED

from . import ThermexConfigEntry
from .entity import ThermexEntity

SPEED_RANGE = (1, MAX_SPEED)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThermexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ThermexFan(entry.runtime_data)])


class ThermexFan(ThermexEntity, FanEntity):
    """The extraction fan, exposed as four speed steps."""

    _attr_name = None  # the device name is enough
    _attr_translation_key = "hood_fan"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_speed_count = MAX_SPEED

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.address}_fan"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.fan_on

    @property
    def percentage(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return ranged_value_to_percentage(SPEED_RANGE, self.coordinator.data.speed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw protocol fields - useful while the decode is young."""
        state = self.coordinator.data
        if state is None:
            return {}
        return {
            "speed_step": state.speed,
            "duty_cycle": state.fan_duty,
            # Airflow feedback from the hood. It lags the setpoint by roughly
            # 15 seconds on spin-down, so do not build automations that treat
            # a non-zero value here as "the fan is running".
            "measured_airflow": state.measured,
        }

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.coordinator.async_set_fan(0)
            return
        speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        await self.coordinator.async_set_fan(speed)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        await self.async_set_percentage(percentage or 25)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_fan(0)
