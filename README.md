# Thermex Range Hood (BLE) for Home Assistant

Local control of a Thermex range hood over Bluetooth LE. No cloud, no account,
and no VoiceLink firmware requirement — this talks directly to the hood's BLE
module.

Built on [thermex-ble](https://github.com/zhimishi/thermex-ble), an unofficial
reverse engineered library. See its
[PROTOCOL.md](https://github.com/zhimishi/thermex-ble/blob/main/PROTOCOL.md)
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

## Connection recovery

After setup, the integration supervises the persistent BLE connection in the
background. Fan and light become unavailable on disconnect or a failed command.
The 5-second health check also detects a disconnected client if its proxy omits
the disconnect callback. The integration does not disconnect an otherwise live
link merely because no periodic status frame arrives; this was observed to
cause a reconnect loop every 30–40 seconds with a Bluetooth proxy.
If a proxy leaves the link marked connected but silently stops forwarding
notifications, a change made on the hood's panel may remain stale until the
next valid frame or a real disconnect. A read-only GATT probe would need
verification on the physical hood before it can safely detect that case.

Recovery releases the previous link, resolves the current Bluetooth device and
proxy through Home Assistant again, and reconnects. Failed attempts are spaced
5, 10, 20, 40, then at most 60 seconds apart, in addition to the time spent on
connection/cleanup. Entities become available only after a fresh unlocked
status has arrived. Fan and light commands are not replayed during recovery.

The matching `thermex-ble` library changes add immediate disconnect callbacks,
bounded connection/write operations, and cleanup when a proxy clears its
connection flag without sending a disconnect callback. An older cached library
is supported by the watchdog, but update both repositories to get all cleanup
fixes. Publish/pin the library revision before releasing the integration; a
cached Git `main` dependency should not be assumed to refresh automatically.

### Development tests

Check out `ha-thermex-ble` and `thermex-ble` beside each other. Using Python 3.14,
from `ha-thermex-ble`:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
python -m pytest ../thermex-ble/tests
```

Tests use Home Assistant 2026.7.3 and simulated BLE clients; no radio connection
or physical fan/light command is made. They cover proxy loss, stale status,
repeated failed attempts, missing disconnect callbacks, command timeouts, and
shutdown while reconnecting and a live but quiet connection. A physical proxy reboot test remains necessary
before deployment.
