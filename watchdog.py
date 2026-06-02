import asyncio
import logging
import time
from dotenv import load_dotenv
from mcstatus import JavaServer
from re import search
from dataclasses import dataclass, fields
from minecraft_server import mc_server

load_dotenv()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)


logger = logging.getLogger("watchdog")
logger.setLevel(logging.INFO)



async def fast_check(host: str, port: int, timeout: float = 2.0):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        logger.debug("Watchdog: port fast check — port is open.")
        return True
    except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
        logger.debug("Watchdog: port fast check — server offline or unreachable.")
        return False
    except Exception as e:
        logger.exception(f"Watchdog: port fast check — unknown exception: {e}")
        return None

async def get_mc_server_status(server_address: str = mc_server.server_address,
                               port: int = mc_server.query_port):
    is_open = await fast_check(server_address, port, timeout=2)
    if is_open:
        try:
            logger.debug("Watchdog: mcstatus trying async_lookup...")
            server = await JavaServer.async_lookup(f"{server_address}:{port}", timeout=3)
            logger.debug("Watchdog: mcstatus trying async_status...")
            status = await asyncio.wait_for(server.async_status(), timeout=6)
            logger.debug("Watchdog: ONLINE Successfully get Minecraft server status.")
            if status:
                mc_server.players_online = status.players.online  # Запись в глобальный инстанс
                logger.debug(f"Watchdog: ONLINE {mc_server.players_online} players online.")
                mc_server.online = True
                if not mc_server.version:
                    mc_server.version = status.version.name
                    mc_server.version_number = (search(r"([0-9]+(\.[0-9]+)+)",
                                                       mc_server.version)).group(1)
            else:
                logger.debug(f"Watchdog: OFFLINE Failed to get list of players online.")
                mc_server.online = False
                mc_server.players_online = None

        except Exception as e:
            mc_server.online = False
            mc_server.players_online = None
            logger.debug(f"Watchdog: OFFLINE Minecraft server unreachable. {type(e).__name__}: {e}")
    else:
        mc_server.online = False
        mc_server.players_online = None

@dataclass
class WatchdogState:
    empty_since: float | None = None  # Когда сервер стал пустым
    warning_3m_sent: bool = False  # Предупреждение за 3 минуты до отключения
    is_fresh_start: bool = True
    crashed: int = 0  # Сервер упал или ещё не запустился.

    def reset(self):
        for f in fields(self):
            setattr(self, f.name, f.default)

watchdog_state = WatchdogState()


def reset_watchdog_state():
    watchdog_state.reset()


async def watchdog_tick(shutdown_callback, notify_callback=None):
    logger.debug("Watchdog tick.")
    await get_mc_server_status()
    now = time.time()

    if mc_server.online:
        watchdog_state.crashed = 0
        if watchdog_state.is_fresh_start:
            if notify_callback:
                await notify_callback(f"✅ Minecraft сервер доступен для подключения."
                                      f"\nВерсия сервера: {mc_server.version_number}")
            watchdog_state.is_fresh_start = False

    if mc_server.players_online == 0:
        if watchdog_state.empty_since is None:
            watchdog_state.empty_since = now
            logger.info("Watchdog: server is empty, starting shutdown timer")
        elif now - watchdog_state.empty_since >= mc_server.wd_poweroff_cooldown:
            logger.warning("Watchdog: server remained empty, cooldown passed — shutting down VPS")
            if notify_callback:
                await notify_callback(f"🔴 Сервер выключен после "
                                      f"{mc_server.wd_poweroff_cooldown // 60} минут неактивности.")
            await shutdown_callback()
            watchdog_state.empty_since = None  # Reset after shutdown
            watchdog_state.warning_3m_sent = False  # сбрасываем флаг после выключения
            watchdog_state.is_fresh_start = True # следующий запуск будет новым
        else:
            mc_server.shutdown_remaining = int(mc_server.wd_poweroff_cooldown - (now - watchdog_state.empty_since))
            logger.info(f"Watchdog: server still empty, {mc_server.shutdown_remaining} seconds left until shutdown")
            if mc_server.shutdown_remaining <= 180 and notify_callback and not watchdog_state.warning_3m_sent:
                await notify_callback(f"ℹ️ На сервере никого нет. До выключения осталось 3 минуты.")
                watchdog_state.warning_3m_sent = True  # для однократного вывода

    elif mc_server.players_online is not None:
        if watchdog_state.empty_since is not None:
            logger.info("Watchdog: players joined — resetting shutdown timer")
            watchdog_state.empty_since = None  # Reset timer because players are online
            watchdog_state.warning_3m_sent = False
    else: # случай с падением minecraft или первым запуском.
        if not watchdog_state.is_fresh_start:
            logger.warning("Watchdog: looks like minecraft server is crashed or unreachable.")
        else:
            logger.info("Watchdog: Minecraft server is offline and probably starting.")
        if notify_callback and watchdog_state.crashed > 1 and not watchdog_state.is_fresh_start:
            await notify_callback("⚠️ Minecraft сервер временно недоступен или аварийно завершил работу.")
            watchdog_state.warning_3m_sent = False
            watchdog_state.is_fresh_start = True # для вывода уведомления о запуске
        elif notify_callback and watchdog_state.crashed == 0 and watchdog_state.is_fresh_start:
            await notify_callback("⏳ Minecraft сервер запускается...")
        watchdog_state.crashed += 1
        watchdog_state.empty_since = None #  сброс таймера до корректного восстановления работы
