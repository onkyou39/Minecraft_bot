from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import time
from services import watchdog
from state.minecraft_server import mc_server


# для будущих тестов
@pytest.fixture(autouse=True)
def clean_state():
    watchdog.watchdog_state.reset()
    mc_server.reset_runtime()
    yield
    watchdog.watchdog_state.reset()


@pytest.fixture
def h(monkeypatch):
    """Стенд: управляем сервером и временем, записываем все уведомления."""
    clock = {"now": 1_700_000_000.0}
    server = {"online": True, "players": 0}
    h = SimpleNamespace(notifications=[], shutdowns=0)

    async def refresh():
        watchdog.mc_server.online = server["online"]
        watchdog.mc_server.players_online = server["players"]

    async def notify(msg): h.notifications.append(msg)
    async def shutdown(): h.shutdowns += 1

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", refresh)
    monkeypatch.setattr(watchdog, "time", SimpleNamespace(time=lambda: clock["now"]))

    h.set_server = lambda online, players: server.update(online=online, players=players)
    h.advance = lambda seconds: clock.__setitem__("now", clock["now"] + seconds)
    h.now = lambda: clock["now"]
    h.tick = lambda cb=notify: watchdog.watchdog_tick(shutdown, cb)
    return h


@pytest.mark.asyncio
async def test_online_with_players(monkeypatch):
    state = {"notified": False, "shutdown": False}

    # игроки есть
    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = True
        watchdog.mc_server.players_online = 3

    async def notify_cb(msg): state["notified"] = msg

    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)

    # Сбрасываем состояние датакласса перед тестом
    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.is_fresh_start = True

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "✅ Minecraft сервер доступен" in state["notified"]
    assert not state["shutdown"]


@pytest.mark.asyncio
async def test_empty_server_timer_not_expired(monkeypatch):
    state = {"notified": None, "shutdown": False}

    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = True
        watchdog.mc_server.players_online = 0

    async def notify_cb(msg): state["notified"] = msg

    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)

    # Подготавливаем состояние датакласса
    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.empty_since = time.time() - watchdog.mc_server.wd_poweroff_cooldown + 120
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_remaining_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "никого нет" in state["notified"]
    assert not state["shutdown"]


@pytest.mark.asyncio
async def test_empty_server_shutdown(monkeypatch):
    state = {"notified": None, "shutdown": False}

    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = True
        watchdog.mc_server.players_online = 0

    async def notify_cb(msg): state["notified"] = msg

    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.empty_since = time.time() - watchdog.mc_server.wd_poweroff_cooldown - 5
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_remaining_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "выключен" in state["notified"]
    assert state["shutdown"]


@pytest.mark.asyncio
async def test_server_crashed(monkeypatch):
    state = {"notified": None, "shutdown": False}
    crashes = {"count": 2}

    # сервер упал
    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = False
        watchdog.mc_server.players_online = None

    async def notify_cb(msg): state["notified"] = msg

    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.crashed = crashes["count"]
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_remaining_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "временно недоступен" in state["notified"]


@pytest.mark.asyncio
async def test_first_start(monkeypatch):
    state = {"notified": None, "shutdown": False}

    # сервер недоступен, первый запуск
    async def mock_refresh_mc_server_status():
        watchdog.mc_server.online = False
        watchdog.mc_server.players_online = None

    async def notify_cb(msg): state["notified"] = msg

    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_status)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.crashed = 0
    watchdog.watchdog_state.is_fresh_start = True
    watchdog.watchdog_state.warning_remaining_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "запускается" in state["notified"]


@pytest.mark.asyncio
async def test_failed_server_status(monkeypatch):
    state = {"notified": None, "shutdown": False}
    crashes = {"count": 1}

    async def mock_fast_check(host, port, timeout=2.0):
        return True  # порт открыт

    class MockServer:
        async def async_status(self):
            raise TimeoutError("Сервер завис")

    async def mock_lookup(address_port, timeout=3):
        return MockServer()

    async def notify_cb(msg): state["notified"] = msg

    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "fast_check", mock_fast_check)
    # noinspection PyUnresolvedReferences
    monkeypatch.setattr(watchdog.JavaServer, "async_lookup", mock_lookup)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.crashed = crashes["count"]
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_remaining_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert state["notified"] is None


def test_watchdog_run_creates_job():
    job_queue = Mock()
    watchdog_job = Mock()
    job_queue.run_repeating.return_value = watchdog_job
    watchdog.watchdog_state.reset()
    watchdog.watchdog_run(job_queue)
    job_queue.run_repeating.assert_called_once()
    assert watchdog.watchdog_state.watchdog_job is watchdog_job


def test_watchdog_run_does_not_create_second_job():
    job_queue = Mock()
    watchdog_job = Mock()
    job_queue.run_repeating.return_value = watchdog_job
    watchdog.watchdog_state.watchdog_job = watchdog_job
    watchdog.watchdog_run(job_queue)
    job_queue.run_repeating.assert_not_called()


def test_watchdog_can_restart_after_shutdown():
    job_queue = Mock()
    watchdog_job = Mock()
    job_queue.run_repeating.return_value = watchdog_job
    watchdog.watchdog_state.reset()

    # первый запуск
    watchdog.watchdog_run(job_queue)

    # эмулируем shutdown
    watchdog.watchdog_state.watchdog_job = None
    watchdog.reset_watchdog_state()

    # повторный запуск
    watchdog.watchdog_run(job_queue)

    assert watchdog.watchdog_state.watchdog_job is watchdog_job


@pytest.mark.asyncio
async def test_empty_server_remaining_uses_deadline_for_fractional_seconds(monkeypatch):
    state = {"notified": None, "shutdown": False}
    now = 1700000000.0

    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = True
        watchdog.mc_server.players_online = 0

    async def notify_cb(msg):
        state["notified"] = msg

    async def shutdown_cb():
        state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)
    monkeypatch.setattr(watchdog.time, "time", lambda: now)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.empty_since = now - watchdog.mc_server.wd_poweroff_cooldown + 0.1
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_shutdown_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)

    assert "никого нет" in state["notified"]
    assert watchdog.mc_server.shutdown_remaining == 1
    assert not state["shutdown"]


@pytest.mark.asyncio
async def test_empty_server_shutdown_at_exact_deadline(monkeypatch):
    state = {"notified": None, "shutdown": False}
    now = 1700000000.0

    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = True
        watchdog.mc_server.players_online = 0

    async def notify_cb(msg):
        state["notified"] = msg

    async def shutdown_cb():
        state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)
    monkeypatch.setattr(watchdog.time, "time", lambda: now)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.empty_since = now - watchdog.mc_server.wd_poweroff_cooldown
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_shutdown_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)

    assert "выключен" in state["notified"]
    assert state["shutdown"]
    assert watchdog.mc_server.shutdown_remaining is None


@pytest.mark.asyncio
async def test_warning_sent_once(h):
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.empty_since = (
        h.now() - watchdog.mc_server.wd_poweroff_cooldown + watchdog.WATCHDOG_WARN_SECONDS - 1
    )
    await h.tick()
    h.advance(watchdog.TICK_INTERVAL)
    await h.tick()

    assert sum("никого нет" in m for m in h.notifications) == 1


@pytest.mark.asyncio
async def test_warning_resent_after_server_blip(h):
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_shutdown_sent = True
    watchdog.watchdog_state.empty_since = h.now() - 100

    h.set_server(online=False, players=None)
    await h.tick()                      # одно пропадание, crashed == 1
    h.set_server(online=True, players=0)
    await h.tick()                      # таймер стартует заново
    h.advance(watchdog.mc_server.wd_poweroff_cooldown - watchdog.WATCHDOG_WARN_SECONDS + 1)
    await h.tick()

    assert any("никого нет" in m for m in h.notifications)