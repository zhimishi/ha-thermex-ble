# Thermex Range Hood (BLE) for Home Assistant

Local control of a Thermex range hood over Bluetooth LE. No cloud, no account,
and no VoiceLink firmware requirement — this talks directly to the hood's BLE
module.

Built on [thermex-ble](https://github.com/srydning/thermex-ble), an unofficial
reverse engineered library. See its
[PROTOCOL.md](https://github.com/srydning/thermex-ble/blob/main/PROTOCOL.md)
for how the protocol was worked out.

## Entities

| Entity | Notes |
|---|---|
| Fan | Four speed steps |
| Light | Dimmable, 0–100% |

State changes made on the hood's own control panel show up in Home Assistant,
because the hood pushes a status frame whenever anything changes.

## Tested with

**Thermex Design Line 8002 (TDL8002W80BK)**, firmware 1.28.

Other models with the same BLE module are likely to work. If yours does — or
doesn't — please open an issue.

## Install

### HACS

1. HACS → three-dot menu → **Custom repositories**
2. Add `https://github.com/zhimishi/ha-thermex-ble`, category **Integration**
3. Install, then restart Home Assistant
4. **Settings → Devices & services → Add integration → Thermex**

### Manual

Copy `custom_components/thermex_ble` into your `config/custom_components/`
directory and restart.

## Setup

You will need the hood's Bluetooth address. The hood **stops advertising while
anything is connected to it**, and it accepts only one connection at a time, so
automatic discovery usually finds nothing.

To find the address:

1. Disconnect the Thermex app — turn off Bluetooth on your phone
2. Power-cycle the hood
3. Immediately run `bluetoothctl scan le` on the Home Assistant host

Then enter the address in the config flow.

## Range

If Home Assistant is too far from the kitchen, flash any ESP32 with
[ESPHome Bluetooth Proxy](https://esphome.github.io/bluetooth-proxies/) and put
it nearby. No configuration needed on this integration's side — Home Assistant
routes the connection automatically.

## Known limitations

While Home Assistant holds the connection, the Thermex phone app cannot
connect. The hood's own control panel always works.

## Licence

MIT. Not affiliated with or endorsed by Thermex.
