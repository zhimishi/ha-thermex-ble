"""Shared entity base for Thermex hood entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ThermexCoordinator


class ThermexEntity(CoordinatorEntity[ThermexCoordinator]):
    """Base class carrying the shared device registry entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ThermexCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer="Thermex",
            model="Design Line 8002",
            name="Thermex Range Hood",
        )

    @property
    def available(self) -> bool:
        """Entities go unavailable when the radio link drops, not on stale data."""
        hood = self.coordinator.hood
        return super().available and hood is not None and hood.is_connected
