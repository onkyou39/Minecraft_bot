import asyncio
import logging
import time
import os
from dotenv import load_dotenv
from mcstatus import JavaServer
from typing import Optional
from dataclasses import dataclass, fields

load_dotenv()

@dataclass
class MinecraftServer:
    server_address: str = os.getenv("SERVER_ADDRESS")  # или IP
    query_port: int = 25565
    check_interval: int = 60  # секунд между проверками
    wd_poweroff_cooldown: int = 10 * 60  # 10 минут
    version: str = ""

MINECRAFT_SERVER = MinecraftServer()


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)


logger = logging.getLogger("watchdog")
logger.setLevel(logging.INFO)

async def get_players_list():
    return await check_server_players()


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

async def get_server_status(server_address: str = MINECRAFT_SERVER.server_address,
                            port: int = MINECRAFT_SERVER.query_port):
    is_open = await fast_check(server_address, port, timeout=2)
    if is_open:
        try:
            logger.debug("Watchdog: mcstatus trying async_lookup...")
            server = await JavaServer.async_lookup(f"{server_address}:{port}", timeout=3)
            logger.debug("Watchdog: mcstatus trying async_status...")
            status = await asyncio.wait_for(server.async_status(), timeout=6)
            logger.debug(f"Watchdog: ONLINE Successfully get Minecraft server status.")
            if not MINECRAFT_SERVER.version:
                MINECRAFT_SERVER.version = status.version.name
            return status

        except Exception as e:
            logger.debug(f"Watchdog: OFFLINE Minecraft server unreachable. {type(e).__name__}: {e}")
            return None
    else:
        return None

async def check_server_players():
    status = await get_server_status()
    if status:
        # noinspection PyUnresolvedReferences
        # для подавления warning в pycharm
        players_online = status.players.online
        logger.debug(f"Watchdog: ONLINE {players_online} players online.")
        return players_online
    else:
        logger.debug(f"Watchdog: OFFLINE Failed to get list of players online.")
        return None

@dataclass
class WatchdogState:
    empty_since: Optional[float] = None  # Когда сервер стал пустым
    notified: bool = False  # Флаги для уведомлений
    is_fresh_start: bool = True
    crashed: int = 0  # Сервер упал или ещё не запустился.

    def reset(self):
        for f in fields(self):
            setattr(self, f.name, f.default)

WATCHDOG_STATE = WatchdogState()


def reset_watchdog_state():
    WATCHDOG_STATE.reset()


async def watchdog_tick(shutdown_callback, notify_callback=None):
    logger.debug("Watchdog tick.")
    players = await check_server_players()
    now = time.time()

    if players is not None:
        WATCHDOG_STATE.crashed = 0
        if WATCHDOG_STATE.is_fresh_start:
            if notify_callback:
                await notify_callback(f"✅ Minecraft сервер доступен для подключения."
                                      f"\nВерсия сервера: {MINECRAFT_SERVER.version}")
            WATCHDOG_STATE.is_fresh_start = False

    if players == 0:
        if WATCHDOG_STATE.empty_since is None:
            WATCHDOG_STATE.empty_since = now
            logger.info("Watchdog: server is empty, starting shutdown timer")
        elif now - WATCHDOG_STATE.empty_since >= MINECRAFT_SERVER.wd_poweroff_cooldown:
            logger.warning("Watchdog: server remained empty, cooldown passed — shutting down VPS")
            if notify_callback:
                await notify_callback(f"🔴 На сервере не было игроков больше "
                                      f"{MINECRAFT_SERVER.wd_poweroff_cooldown // 60} минут."
                                      f" Сервер выключен.")
            await shutdown_callback()
            WATCHDOG_STATE.empty_since = None  # Reset after shutdown
            WATCHDOG_STATE.notified = False  # сбрасываем флаг после выключения
            WATCHDOG_STATE.is_fresh_start = True # следующий запуск будет новым
        else:
            remaining = int(MINECRAFT_SERVER.wd_poweroff_cooldown - (now - WATCHDOG_STATE.empty_since))
            logger.info(f"Watchdog: server still empty, {remaining} seconds left until shutdown")
            if notify_callback and not WATCHDOG_STATE.notified:
                await notify_callback(f"ℹ️ На сервере нет игроков. "
                                      f"Сервер будет выключен через "
                                      f"{MINECRAFT_SERVER.wd_poweroff_cooldown // 60} минут.")
                WATCHDOG_STATE.notified = True  # для однократного вывода

    elif players is not None:
        if WATCHDOG_STATE.empty_since is not None:
            logger.info("Watchdog: players joined — resetting shutdown timer")
            WATCHDOG_STATE.empty_since = None  # Reset timer because players are online
            WATCHDOG_STATE.notified = False
    else: # случай с падением minecraft или первым запуском.
        if not WATCHDOG_STATE.is_fresh_start:
            logger.warning("Watchdog: looks like minecraft server is crashed or unreachable.")
        else:
            logger.info("Watchdog: Minecraft server is offline and probably starting.")
        if notify_callback and WATCHDOG_STATE.crashed > 1 and not WATCHDOG_STATE.is_fresh_start:
            await notify_callback("⚠️ Minecraft сервер временно недоступен или аварийно завершил работу.")
            WATCHDOG_STATE.notified = False
            WATCHDOG_STATE.is_fresh_start = True # для вывода уведомления о запуске
        elif notify_callback and WATCHDOG_STATE.crashed == 0 and WATCHDOG_STATE.is_fresh_start:
            await notify_callback("⏳ Minecraft сервер запускается...")
        WATCHDOG_STATE.crashed += 1
        WATCHDOG_STATE.empty_since = None #  сброс таймера до корректного восстановления работы
