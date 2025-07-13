import asyncio
import logging
import time
import os
from dotenv import load_dotenv
from mcstatus import JavaServer
from typing import Optional

load_dotenv()

SERVER_ADDRESS = os.getenv("SERVER_ADDRESS")  # или IP
QUERY_PORT = 25565
CHECK_INTERVAL = 60  # секунд между проверками
WD_POWEROFF_COOLDOWN = 10 * 60 # 10 минут


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)


logger = logging.getLogger("watchdog")
logging.getLogger("watchdog").setLevel(logging.DEBUG)

async def get_players_list():
    return await check_server_players(SERVER_ADDRESS, QUERY_PORT)


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

async def check_server_players(server_address: str, port: int):
    is_open = await fast_check(server_address, port, timeout=2)
    if is_open:
        try:
            logger.debug("Watchdog: mcstatus trying async_lookup...")
            server = await JavaServer.async_lookup(f"{server_address}:{port}", timeout=3)
            logger.debug("Watchdog: mcstatus trying async_status...")
            status = await asyncio.wait_for(server.async_status(), timeout=6)
            players_online = status.players.online
            logger.debug(f"Watchdog: ONLINE {players_online} players online.")
            return players_online

        except Exception as e:
            logger.debug(f"Watchdog: OFFLINE Minecraft server unreachable. {type(e).__name__}: {e}")
            return None
    else:
        return None

empty_since: Optional[float] = None  # Когда сервер стал пустым
notified = False # Флаги для уведомлений
is_fresh_start = True
crashed = 0 # Сервер упал или ещё не запустился.


async def watchdog_tick(shutdown_callback, notify_callback=None):
    logger.debug("Watchdog tick.")
    global empty_since, notified, is_fresh_start, crashed
    players = await check_server_players(SERVER_ADDRESS, QUERY_PORT)
    now = time.time()

    if players is not None:
        crashed = 0
        if is_fresh_start:
            if notify_callback:
                await notify_callback("✅ Minecraft сервер доступен для подключения.")
            is_fresh_start = False

    if players == 0:
        if empty_since is None:
            empty_since = now
            logger.info("Watchdog: server is empty, starting shutdown timer")
        elif now - empty_since >= WD_POWEROFF_COOLDOWN:
            logger.warning("Watchdog: server remained empty, cooldown passed — shutting down VPS")
            if notify_callback:
                await notify_callback(f"🔴 На сервере не было игроков больше {WD_POWEROFF_COOLDOWN // 60} минут."
                                      f" Сервер выключен.")
            await shutdown_callback()
            empty_since = None  # Reset after shutdown
            notified = False  # сбрасываем флаг после выключения
            is_fresh_start = True # следующий запуск будет новым
        else:
            remaining = int(WD_POWEROFF_COOLDOWN - (now - empty_since))
            logger.info(f"Watchdog: server still empty, {remaining} seconds left until shutdown")
            if notify_callback and not notified:
                await notify_callback(f"ℹ️ На сервере нет игроков. "
                                      f"Сервер будет выключен через {WD_POWEROFF_COOLDOWN // 60} минут.")
                notified = True  # для однократного вывода

    elif players is not None:
        if empty_since is not None:
            logger.info("Watchdog: players joined — resetting shutdown timer")
            empty_since = None  # Reset timer because players are online
            notified = False
    else: # случай с падением minecraft или первым запуском.
        if not is_fresh_start:
            logger.warning("Watchdog: looks like minecraft server is crashed or unreachable.")
        else:
            logger.info("Watchdog: Minecraft server is offline and probably starting.")
        if notify_callback and crashed > 1 and not is_fresh_start:
            await notify_callback("⚠️ Minecraft сервер временно недоступен или аварийно завершил работу.")
            notified = False
            is_fresh_start = True # для вывода уведомления о запуске
        elif notify_callback and crashed == 0 and is_fresh_start:
            await notify_callback("⏳ Minecraft сервер запускается...")
        crashed += 1
        empty_since = None #  сброс таймера до корректного восстановления работы
