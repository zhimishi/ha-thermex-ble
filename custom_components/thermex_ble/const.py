"""Constants for the Thermex BLE integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "thermex_ble"

CONF_ADDRESS: Final = "address"

#: The hood stops advertising as soon as anything connects to it, and it takes
#: only one connection at a time. Home Assistant therefore holds the link open
#: and listens for notifications instead of polling - which is also what gives
#: us state changes made on the hood's own control panel.
UPDATE_METHOD: Final = "push"
