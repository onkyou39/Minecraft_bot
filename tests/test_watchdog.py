from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from services import watchdog
from state.minecraft_server import mc_server

state = watchdog.watchdog_state

COOLDOWN = 600  # фиксируем, чтобы тесты не зависели от значения по умолчанию


# ---------------------------------------------------------------------------
# Фикстуры и помощники
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_state():
    state.reset()
    mc_server.reset_runtime()
    yield
    state.reset()
    mc_server.reset_runtime()


@pytest.fixture
def wd(monkeypatch):
    """Стенд: управляем сервером и временем, записываем все уведомления."""
    clock = {"now": 1_700_000_000.0}
    server = {"online": True, "players": 0}
    wd = SimpleNamespace(notifications=[], shutdowns=0, fail_shutdown=False)

    async def refresh():
        mc_server.online = server["online"]
        mc_server.players_online = server["players"]

    async def notify(msg):
        wd.notifications.append(msg)

    async def shutdown():
        if wd.fail_shutdown:
            raise RuntimeError("shutdown failed")
        wd.shutdowns += 1

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", refresh)
    # noinspection PyUnresolvedReferences
    monkeypatch.setattr(watchdog, "time", SimpleNamespace(time=lambda: clock["now"]))
    # noinspection PyUnresolvedReferences
    monkeypatch.setattr(mc_server, "wd_poweroff_cooldown", COOLDOWN)

    wd.set_server = lambda online, players: server.update(online=online, players=players)
    wd.advance = lambda seconds: clock.__setitem__("now", clock["now"] + seconds)
    wd.now = lambda: clock["now"]
    wd.tick = lambda cb=notify: watchdog.watchdog_tick(shutdown, cb)
    return wd


def set_empty(h, remaining):
    """Сервер пуст, до выключения осталось `remaining` секунд, «свежий старт» уже прошёл."""
    state.is_fresh_start = False
    state.empty_since = h.now() - COOLDOWN + remaining


def set_crashed(h, count):
    state.is_fresh_start = False
    state.crashed = count


def set_unreachable(h, ago):
    state.unreachable_since = h.now() - ago


async def run_ticks(h, n):
    for _ in range(n):
        await h.tick()
        h.advance(watchdog.TICK_INTERVAL)


def count(h, text):
    return sum(text in m for m in h.notifications)


# ---------------------------------------------------------------------------
# watchdog_tick: основные сценарии
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_online_with_players(wd):
    wd.set_server(online=True, players=3)

    await wd.tick()

    assert any("✅ Minecraft сервер доступен" in m for m in wd.notifications)
    assert wd.shutdowns == 0


@pytest.mark.asyncio
async def test_empty_server_warning_in_window(wd):
    set_empty(wd, 120)

    await wd.tick()

    assert any("никого нет" in m for m in wd.notifications)
    assert mc_server.shutdown_remaining == 120
    assert wd.shutdowns == 0


@pytest.mark.asyncio
async def test_empty_server_shutdown(wd):
    state.is_fresh_start = False
    state.empty_since = wd.now() - COOLDOWN - 5

    await wd.tick()

    assert any("выключен" in m for m in wd.notifications)
    assert wd.shutdowns == 1


@pytest.mark.asyncio
async def test_server_crashed(wd):
    set_crashed(wd, 2)
    wd.set_server(online=False, players=None)

    await wd.tick()

    assert any("временно недоступен" in m for m in wd.notifications)


@pytest.mark.asyncio
async def test_first_start(wd):
    wd.set_server(online=False, players=None)

    await wd.tick()

    assert any("запускается" in m for m in wd.notifications)


@pytest.mark.asyncio
async def test_empty_server_remaining_uses_deadline_for_fractional_seconds(wd):
    state.is_fresh_start = False
    state.empty_since = wd.now() - COOLDOWN + 0.1

    await wd.tick()

    assert any("никого нет" in m for m in wd.notifications)
    assert mc_server.shutdown_remaining == 1
    assert wd.shutdowns == 0


@pytest.mark.asyncio
async def test_empty_server_shutdown_at_exact_deadline(wd):
    state.is_fresh_start = False
    state.empty_since = wd.now() - COOLDOWN

    await wd.tick()

    assert any("выключен" in m for m in wd.notifications)
    assert wd.shutdowns == 1
    assert mc_server.shutdown_remaining is None


# ---------------------------------------------------------------------------
# watchdog_tick: таймер простоя
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_first_tick_starts_timer_silently(wd):
    assert COOLDOWN > watchdog.WATCHDOG_WARN_SECONDS  # иначе предупреждение придёт сразу
    state.is_fresh_start = False

    await wd.tick()

    assert state.empty_since == wd.now()
    assert mc_server.shutdown_remaining == COOLDOWN
    assert wd.notifications == []


@pytest.mark.asyncio
async def test_warning_sent_once(wd):
    set_empty(wd, watchdog.WATCHDOG_WARN_SECONDS - 1)

    await wd.tick()
    wd.advance(watchdog.TICK_INTERVAL)
    await wd.tick()

    assert count(wd, "никого нет") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining, expect_warning", [
    (watchdog.WATCHDOG_WARN_SECONDS, True),
    (watchdog.WATCHDOG_WARN_SECONDS + 1, False),
])
async def test_warning_window_boundary(wd, remaining, expect_warning):
    set_empty(wd, remaining)

    await wd.tick()

    assert any("никого нет" in m for m in wd.notifications) is expect_warning


@pytest.mark.asyncio
async def test_player_joining_resets_countdown(wd):
    set_empty(wd, 120)
    state.warning_shutdown_sent = True
    mc_server.shutdown_remaining = 120
    wd.set_server(online=True, players=2)

    await wd.tick()

    assert state.empty_since is None
    assert state.warning_shutdown_sent is False
    assert mc_server.shutdown_remaining is None
    assert wd.shutdowns == 0


@pytest.mark.asyncio
async def test_server_disappearing_mid_countdown_resets_timer(wd):
    set_empty(wd, 120)
    state.warning_shutdown_sent = True
    mc_server.shutdown_remaining = 120
    wd.set_server(online=False, players=None)

    await wd.tick()

    assert state.empty_since is None
    assert state.warning_shutdown_sent is False
    assert mc_server.shutdown_remaining is None
    assert wd.shutdowns == 0


@pytest.mark.asyncio
async def test_state_after_idle_shutdown(wd):
    set_empty(wd, 0)

    await wd.tick()

    assert wd.shutdowns == 1
    assert "выключен" in wd.notifications[-1]
    assert state.empty_since is None
    assert state.warning_shutdown_sent is False
    assert state.is_fresh_start is True
    assert mc_server.shutdown_remaining is None


@pytest.mark.asyncio
async def test_available_message_repeats_after_idle_shutdown(wd):
    set_empty(wd, 0)
    await wd.tick()  # выключение
    wd.notifications.clear()

    wd.set_server(online=True, players=1)
    await wd.tick()

    assert count(wd, "доступен для подключения") == 1


@pytest.mark.asyncio
async def test_warning_resent_after_server_blip(wd):
    state.is_fresh_start = False
    state.warning_shutdown_sent = True
    state.empty_since = wd.now() - 100

    wd.set_server(online=False, players=None)
    await wd.tick()                      # одно пропадание, crashed == 1
    wd.set_server(online=True, players=0)
    await wd.tick()                      # таймер стартует заново
    wd.advance(COOLDOWN - watchdog.WATCHDOG_WARN_SECONDS + 1)
    await wd.tick()

    assert any("никого нет" in m for m in wd.notifications)


# ---------------------------------------------------------------------------
# watchdog_tick: запуск, сбой, недоступность
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_startup_sequence_notifies_once_each(wd, monkeypatch):
    # noinspection PyUnresolvedReferences
    monkeypatch.setattr(mc_server, "version_number", "1.21.4")
    wd.set_server(online=False, players=None)

    await run_ticks(wd, 3)               # сервер ещё поднимается
    assert wd.notifications == ["⏳ Minecraft сервер запускается..."]

    wd.set_server(online=True, players=1)
    await run_ticks(wd, 2)               # поднялся, второй тик без сообщений

    assert len(wd.notifications) == 2
    assert "доступен для подключения" in wd.notifications[1]
    assert "1.21.4" in wd.notifications[1]
    assert state.crashed == 0


@pytest.mark.asyncio
async def test_crash_sequence_alerts_once_and_announces_recovery(wd):
    wd.set_server(online=True, players=1)
    await run_ticks(wd, 1)               # «доступен», is_fresh_start сброшен

    wd.set_server(online=False, players=None)
    await run_ticks(wd, 2)               # первые два неудачных опроса молчат
    assert count(wd, "временно недоступен") == 0

    await run_ticks(wd, 3)               # алерт приходит на третьем, дальше без повторов
    assert count(wd, "временно недоступен") == 1

    wd.set_server(online=True, players=1)
    await run_ticks(wd, 1)

    assert count(wd, "доступен для подключения") == 2
    assert count(wd, "запускается") == 0


@pytest.mark.asyncio
async def test_unreachable_shutdown_after_limit(wd):
    wd.set_server(online=False, players=None)
    limit = watchdog.WATCHDOG_UNREACHABLE_SECONDS

    await wd.tick()
    wd.advance(limit - 1)
    await wd.tick()
    assert wd.shutdowns == 0

    wd.advance(1)
    await wd.tick()

    assert wd.shutdowns == 1
    assert any("недоступен более" in m for m in wd.notifications)
    assert state.is_fresh_start is True
    assert state.crashed == 0
    assert state.unreachable_since is None


@pytest.mark.asyncio
async def test_unreachable_timer_resets_when_server_returns(wd):
    limit = watchdog.WATCHDOG_UNREACHABLE_SECONDS

    wd.set_server(online=False, players=None)
    await wd.tick()
    wd.advance(limit - 60)

    wd.set_server(online=True, players=1)
    await wd.tick()                       # сервер ответил, таймер сброшен

    wd.set_server(online=False, players=None)
    await wd.tick()                       # новый отсчёт
    wd.advance(limit - 60)
    await wd.tick()

    assert wd.shutdowns == 0


@pytest.mark.asyncio
async def test_starting_message_after_unreachable_shutdown(wd):
    wd.set_server(online=False, players=None)
    await wd.tick()
    wd.advance(watchdog.WATCHDOG_UNREACHABLE_SECONDS)
    await wd.tick()                       # выключение

    wd.notifications.clear()
    await wd.tick()                       # следующий запуск

    assert any("запускается" in m for m in wd.notifications)


# ---------------------------------------------------------------------------
# watchdog_tick: колбэки
# ---------------------------------------------------------------------------

NO_NOTIFY_CASES = [
    pytest.param(True, 3, lambda h: None, 0, id="players_online_fresh_start"),
    pytest.param(True, 0, lambda h: set_empty(h, 120), 0, id="warning_window"),
    pytest.param(True, 0, lambda h: set_empty(h, 0), 1, id="idle_deadline"),
    pytest.param(False, None, lambda h: None, 0, id="starting"),
    pytest.param(False, None, lambda h: set_crashed(h, 2), 0, id="crashed"),
    pytest.param(
        False, None,
        lambda h: set_unreachable(h, watchdog.WATCHDOG_UNREACHABLE_SECONDS), 1,
        id="unreachable_limit",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("online, players, setup, expected_shutdowns", NO_NOTIFY_CASES)
async def test_no_notify_callback_in_every_branch(wd, online, players, setup, expected_shutdowns):
    setup(wd)
    wd.set_server(online=online, players=players)

    await wd.tick(None)

    assert wd.shutdowns == expected_shutdowns
    assert wd.notifications == []


@pytest.mark.asyncio
async def test_failed_shutdown_is_retried_on_next_tick(wd):
    set_empty(wd, 0)
    wd.fail_shutdown = True

    with pytest.raises(RuntimeError):
        await wd.tick()
    assert wd.shutdowns == 0
    assert state.empty_since is not None  # таймер не сброшен, выключение повторится

    wd.fail_shutdown = False
    wd.advance(watchdog.TICK_INTERVAL)
    await wd.tick()

    assert wd.shutdowns == 1
    assert state.empty_since is None
    assert state.is_fresh_start is True


# ---------------------------------------------------------------------------
# refresh_mc_server_state
# ---------------------------------------------------------------------------

def patch_status(monkeypatch, version_name, players=2):
    async def fast_check(host, port, timeout=2.0):
        return True

    status = SimpleNamespace(
        players=SimpleNamespace(online=players),
        version=SimpleNamespace(name=version_name),
    )

    class FakeServer:
        async def async_status(self):
            return status

    async def lookup(address_port, timeout=3):
        return FakeServer()

    monkeypatch.setattr(watchdog, "fast_check", fast_check)
    # noinspection PyUnresolvedReferences
    monkeypatch.setattr(watchdog.JavaServer, "async_lookup", lookup)
    monkeypatch.setattr(mc_server, "version", "")
    monkeypatch.setattr(mc_server, "version_number", "")


@pytest.mark.asyncio
async def test_refresh_parses_version_number(monkeypatch):
    patch_status(monkeypatch, "Paper 1.21.4")

    await watchdog.refresh_mc_server_state("localhost", 25565)

    assert mc_server.online is True
    assert mc_server.players_online == 2
    assert mc_server.version_number == "1.21.4"


@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="версия без цифр (например, снапшот) ломает опрос")
async def test_refresh_survives_version_without_digits(monkeypatch):
    patch_status(monkeypatch, "24w14a")

    await watchdog.refresh_mc_server_state("localhost", 25565)

    assert mc_server.online is True
    assert mc_server.players_online == 2
    assert mc_server.version_number


@pytest.mark.asyncio
async def test_refresh_marks_offline_when_port_closed(monkeypatch):
    async def fast_check(host, port, timeout=2.0):
        return False

    monkeypatch.setattr(watchdog, "fast_check", fast_check)
    mc_server.online = True
    mc_server.players_online = 5

    await watchdog.refresh_mc_server_state("localhost", 25565)

    assert mc_server.online is False
    assert mc_server.players_online is None


@pytest.mark.asyncio
async def test_hung_server_status_does_not_alert_on_first_failure(monkeypatch):
    notified = []

    async def mock_fast_check(host, port, timeout=2.0):
        return True  # порт открыт

    class MockServer:
        async def async_status(self):
            raise TimeoutError("Сервер завис")

    async def mock_lookup(address_port, timeout=3):
        return MockServer()

    async def notify_cb(msg): notified.append(msg)

    async def shutdown_cb(): pass

    monkeypatch.setattr(watchdog, "fast_check", mock_fast_check)
    # noinspection PyUnresolvedReferences
    monkeypatch.setattr(watchdog.JavaServer, "async_lookup", mock_lookup)

    state.crashed = 1
    state.is_fresh_start = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)

    assert mc_server.online is False
    assert mc_server.players_online is None
    assert notified == []


# ---------------------------------------------------------------------------
# watchdog_run / watchdog_stop
# ---------------------------------------------------------------------------

def test_watchdog_run_creates_job():
    job_queue = Mock()
    watchdog_job = Mock()
    job_queue.run_repeating.return_value = watchdog_job

    watchdog.watchdog_run(job_queue)

    job_queue.run_repeating.assert_called_once()
    assert state.watchdog_job is watchdog_job


def test_watchdog_run_does_not_create_second_job():
    job_queue = Mock()
    watchdog_job = Mock()
    job_queue.run_repeating.return_value = watchdog_job
    state.watchdog_job = watchdog_job

    watchdog.watchdog_run(job_queue)

    job_queue.run_repeating.assert_not_called()


def test_watchdog_run_skipped_in_maintenance_mode(monkeypatch):
    # noinspection PyUnresolvedReferences
    monkeypatch.setattr(watchdog.bot_state, "maintenance_mode", True)
    job_queue = Mock()

    watchdog.watchdog_run(job_queue)

    job_queue.run_repeating.assert_not_called()
    assert state.watchdog_job is None


def test_watchdog_can_restart_after_shutdown():
    job_queue = Mock()
    watchdog_job = Mock()
    job_queue.run_repeating.return_value = watchdog_job

    # первый запуск
    watchdog.watchdog_run(job_queue)

    # эмулируем shutdown
    state.watchdog_job = None
    watchdog.reset_watchdog_state()

    # повторный запуск
    watchdog.watchdog_run(job_queue)

    assert state.watchdog_job is watchdog_job


def test_watchdog_stop_removes_job():
    job = Mock()
    state.watchdog_job = job

    watchdog.watchdog_stop()

    job.schedule_removal.assert_called_once()
    assert state.watchdog_job is None


def test_watchdog_stop_clears_timers():
    state.empty_since = 1.0
    state.unreachable_since = 1.0
    state.warning_shutdown_sent = True
    mc_server.shutdown_remaining = 42

    watchdog.watchdog_stop()

    assert state.empty_since is None
    assert state.unreachable_since is None
    assert state.warning_shutdown_sent is False
    assert mc_server.shutdown_remaining is None