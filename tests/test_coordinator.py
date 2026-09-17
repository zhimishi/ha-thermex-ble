"""Recovery regressions with real HA coordinators and a simulated BLE hood."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from thermex_ble import HoodState

from custom_components.thermex_ble import coordinator as module
from custom_components.thermex_ble.coordinator import ThermexCoordinator
from custom_components.thermex_ble.entity import ThermexEntity

STATE = HoodState(2, 45, 80, 10, 0, 930, True, b"")


class Hood:
    def __init__(self, device):
        self.device = device
        self.state = None
        self.is_connected = False
        self.state_callbacks = []
        self.disconnect_callbacks = []
        self.connect = AsyncMock(side_effect=self.open)
        self.disconnect = AsyncMock(side_effect=self.close)
        self.set_fan = AsyncMock()
        self.set_light = AsyncMock()

    def register_callback(self, callback):
        self.state_callbacks.append(callback)
        return lambda: self.state_callbacks.remove(callback)

    def register_disconnect_callback(self, callback):
        self.disconnect_callbacks.append(callback)
        return lambda: self.disconnect_callbacks.remove(callback)

    def open(self):
        self.is_connected = True
        self.state = STATE
        for callback in tuple(self.state_callbacks):
            callback(self.state)

    def close(self):
        self.is_connected = False
        for callback in tuple(self.disconnect_callbacks):
            callback()


async def eventually(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "HEALTH_CHECK_INTERVAL", 0.01)
    monkeypatch.setattr(module, "RETRY_INITIAL", 0.03)
    monkeypatch.setattr(module, "RETRY_MAX", 0.06)
    monkeypatch.setattr(module, "COMMAND_TIMEOUT", 0.02)
    monkeypatch.setattr(module, "CONNECT_TIMEOUT", 0.05)
    monkeypatch.setattr(module, "DISCONNECT_TIMEOUT", 0.05)
    hass = HomeAssistant(str(tmp_path))
    coordinator = ThermexCoordinator(hass, "AA:BB:CC:DD:EE:FF")
    hoods = []

    def create(device):
        hood = Hood(device)
        hoods.append(hood)
        return hood

    factory = Mock(side_effect=create)
    with (
        patch.object(module, "ThermexHood", factory),
        patch.object(
            module.bluetooth, "async_ble_device_from_address", side_effect=lambda *a, **kw: object()
        ) as resolve,
    ):
        yield coordinator, hoods, factory, resolve
        await coordinator.async_shutdown()


async def test_setup_and_disconnect_publish_availability_and_recover(setup):
    coordinator, hoods, factory, resolve = setup
    listener = Mock()
    coordinator.async_add_listener(listener)
    entity = ThermexEntity(coordinator)
    await coordinator.async_setup()
    assert entity.available
    old = hoods[0]
    old.close()
    assert not entity.available
    assert not coordinator.last_update_success
    await eventually(lambda: len(hoods) == 2 and entity.available)
    assert factory.call_count == resolve.call_count == 2
    assert hoods[1].device is not old.device
    assert coordinator.data == STATE
    assert listener.call_count >= 3


async def test_missing_disconnect_callback_is_detected(setup):
    coordinator, hoods, _, _ = setup
    await coordinator.async_setup()
    hoods[0].is_connected = False
    await eventually(lambda: len(hoods) == 2 and coordinator.last_update_success)


async def test_silent_but_connected_link_stays_available(setup):
    coordinator, hoods, _, _ = setup
    await coordinator.async_setup()
    old = hoods[0]
    coordinator._last_state_at -= 3600  # an hour without a notification
    await asyncio.sleep(module.HEALTH_CHECK_INTERVAL * 3)
    assert len(hoods) == 1
    assert coordinator.last_update_success
    assert ThermexEntity(coordinator).available
    old.disconnect.assert_not_awaited()


async def test_retries_continue_with_capped_backoff(setup):
    coordinator, hoods, factory, _ = setup
    await coordinator.async_setup()
    create = factory.side_effect
    attempts = []

    def fail_then_recover(device):
        attempts.append(coordinator.hass.loop.time())
        hood = create(device)
        if len(attempts) <= 4:
            hood.connect.side_effect = ConnectionError("proxy offline")
        return hood

    factory.side_effect = fail_then_recover
    hoods[0].close()
    await eventually(lambda: len(attempts) == 5 and coordinator.last_update_success)
    gaps = [b - a for a, b in zip(attempts, attempts[1:])]
    assert gaps[0] >= 0.025
    assert all(gap >= 0.055 for gap in gaps[1:])
    assert all(gap < 0.3 for gap in gaps)


async def test_missing_route_recovers_when_proxy_returns(setup):
    coordinator, hoods, _, resolve = setup
    await coordinator.async_setup()
    resolve.side_effect = None
    resolve.return_value = None
    hoods[0].close()
    await eventually(lambda: resolve.call_count >= 3)
    assert not coordinator.last_update_success
    resolve.return_value = object()
    await eventually(lambda: len(hoods) == 2 and coordinator.last_update_success)


@pytest.mark.parametrize("hang", [False, True])
async def test_command_failure_recovers_without_replaying(setup, hang):
    coordinator, hoods, _, _ = setup
    await coordinator.async_setup()
    old = hoods[0]

    async def never_finishes(*args):
        await asyncio.Event().wait()

    old.set_fan.side_effect = never_finishes if hang else ConnectionError("lost ack")
    with pytest.raises(HomeAssistantError, match="command failed"):
        await coordinator.async_set_fan(3)
    assert not coordinator.last_update_success
    await eventually(lambda: len(hoods) == 2 and coordinator.last_update_success)
    old.set_fan.assert_awaited_once_with(3)
    hoods[1].set_fan.assert_not_awaited()


async def test_cleanup_failure_does_not_open_another_link(setup):
    coordinator, hoods, _, _ = setup
    await coordinator.async_setup()
    old = hoods[0]
    old.disconnect.side_effect = TimeoutError("old proxy still owns link")
    old.is_connected = False  # callback was missed
    await eventually(lambda: old.disconnect.await_count >= 2)
    assert coordinator.hood is old
    assert len(hoods) == 1
    assert not coordinator.last_update_success
    old.disconnect.side_effect = old.close
    await eventually(lambda: len(hoods) == 2 and coordinator.last_update_success)


async def test_late_callbacks_from_old_link_do_not_affect_current_link(setup):
    coordinator, hoods, _, _ = setup
    await coordinator.async_setup()
    old_state = hoods[0].state_callbacks[0]
    old_disconnect = hoods[0].disconnect_callbacks[0]
    hoods[0].close()
    await eventually(lambda: len(hoods) == 2 and coordinator.last_update_success)
    old_state(replace(STATE, speed=4))
    old_disconnect()
    assert coordinator.last_update_success
    assert coordinator.data.speed == 2


async def test_shutdown_cancels_reconnect_and_prevents_further_attempts(setup):
    coordinator, hoods, factory, _ = setup
    await coordinator.async_setup()
    create = factory.side_effect
    connecting = asyncio.Event()

    async def never_connects():
        connecting.set()
        await asyncio.Event().wait()

    def hang(device):
        hood = create(device)
        hood.connect.side_effect = never_connects
        return hood

    factory.side_effect = hang
    hoods[0].close()
    await connecting.wait()
    task = coordinator._monitor_task
    await coordinator.async_shutdown()
    await coordinator.async_shutdown()
    assert task.done()
    assert coordinator.hood is None
    await asyncio.sleep(0.08)
    assert factory.call_count == 2
    hoods[1].disconnect.assert_awaited_once()


async def test_setup_failure_cleans_up_for_ha_retry(setup):
    coordinator, hoods, factory, _ = setup
    create = factory.side_effect

    def fail(device):
        hood = create(device)
        hood.connect.side_effect = ConnectionError("proxy offline")
        return hood

    factory.side_effect = fail
    with pytest.raises(ConfigEntryNotReady):
        await coordinator.async_setup()
    assert coordinator._monitor_task is None
    assert coordinator.hood is None
    hoods[0].disconnect.assert_awaited_once()


async def test_connection_without_status_is_not_available(setup):
    coordinator, hoods, factory, _ = setup
    create = factory.side_effect

    def no_status(device):
        hood = create(device)
        hood.connect.side_effect = lambda: setattr(hood, "is_connected", True)
        return hood

    factory.side_effect = no_status
    with pytest.raises(ConfigEntryNotReady, match="No unlocked status"):
        await coordinator.async_setup()
    assert coordinator.hood is None


async def test_no_commands_sent_while_disconnected(setup):
    coordinator, hoods, _, _ = setup
    await coordinator.async_setup()
    hoods[0].close()
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await coordinator.async_set_light(80)
    hoods[0].set_light.assert_not_awaited()


async def test_commands_fail_promptly_during_connection_attempt(setup):
    coordinator, hoods, _, _ = setup
    await coordinator.async_setup()
    coordinator._mark_unavailable("reconnecting")
    async with coordinator._operation_lock:
        async with asyncio.timeout(0.1):
            with pytest.raises(HomeAssistantError, match="unavailable"):
                await coordinator.async_set_light(80)
    hoods[0].set_light.assert_not_awaited()


async def test_legacy_library_without_disconnect_subscription_recovers(setup):
    coordinator, hoods, factory, _ = setup
    create = factory.side_effect

    def legacy(device):
        hood = create(device)
        hood.register_disconnect_callback = None
        return hood

    factory.side_effect = legacy
    await coordinator.async_setup()
    hoods[0].is_connected = False
    await eventually(lambda: len(hoods) == 2 and coordinator.last_update_success)


async def test_locked_frames_do_not_replace_known_state(setup):
    coordinator, hoods, _, _ = setup
    await coordinator.async_setup()
    prior_report = coordinator._last_state_at
    hoods[0].state_callbacks[0](replace(STATE, speed=4, unlocked=False))
    assert coordinator.data == STATE
    assert coordinator._last_state_at == prior_report
    assert coordinator.last_update_success


@pytest.mark.parametrize("with_disconnect_callback", [False, True])
async def test_real_library_recovers_proxy_loss(tmp_path, monkeypatch, with_disconnect_callback):
    """Exercise HA, the actual BLE library and decoding together with fake radio I/O."""
    from bleak.backends.device import BLEDevice
    from thermex_ble import hood as library

    frame = bytes.fromhex(
        "00042d0000640000000064020006a00000000000000000007821000000009c00"
        "0b0300b003000000000001aabbccddeeff00"
    )
    clients = []

    class RadioClient:
        def __init__(self, callback):
            self.callback = callback
            self.is_connected = True
            self.notify = None

        async def start_notify(self, characteristic, callback):
            self.notify = callback

        async def write_gatt_char(self, characteristic, payload, **kwargs):
            if payload == library.UNLOCK:
                self.notify(None, bytearray(frame))

        async def disconnect(self):
            self.is_connected = False
            if with_disconnect_callback:
                self.callback(self)

    async def establish(client_type, device, address, callback):
        client = RadioClient(callback)
        clients.append(client)
        return client

    monkeypatch.setattr(module, "HEALTH_CHECK_INTERVAL", 0.01)
    monkeypatch.setattr(library, "DISCONNECT_GRACE", 0)
    monkeypatch.setattr(library, "establish_connection", establish)
    monkeypatch.setattr(
        module.bluetooth,
        "async_ble_device_from_address",
        lambda *a, **kw: BLEDevice("AA:BB:CC:DD:EE:FF", "Thermex", {}),
    )
    hass = HomeAssistant(str(tmp_path))
    coordinator = ThermexCoordinator(hass, "AA:BB:CC:DD:EE:FF")
    entity = ThermexEntity(coordinator)
    try:
        await coordinator.async_setup()
        assert entity.available
        assert coordinator.data.speed == 2
        await clients[0].disconnect()
        assert not entity.available
        await eventually(lambda: len(clients) == 2 and entity.available)
        assert coordinator.data.speed == 2
    finally:
        await coordinator.async_shutdown()
