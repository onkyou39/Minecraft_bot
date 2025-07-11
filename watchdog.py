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


async def check_server_players(server_address: str, port: int):
    try:
        server = await JavaServer.async_lookup(f"{server_address}:{port}", timeout=2)
        status = await server.async_status()  # Query-запрос

        players_online = status.players.online
        logger.debug(f"Watchdog: ONLINE {players_online} players online.")
        return players_online

    except Exception as e:
        logger.debug(f"Watchdog: OFFLINE  Minecraft server unreachable. {e}")
        return None


empty_since: Optional[float] = None  # Когда сервер стал пустым
notified = False # Флаги для уведомлений
is_fresh_start = True


async def watchdog_tick(shutdown_callback, notify_callback=None):
    global empty_since, notified, is_fresh_start
    players = await check_server_players(SERVER_ADDRESS, QUERY_PORT)
    now = time.time()

    if players is not None and is_fresh_start:
        if notify_callback:
            await notify_callback(f"✅ Minecraft сервер запущен.")
        is_fresh_start = False

    if players == 0:
        if empty_since is None:
            empty_since = now
            logger.info("Watchdog: server is empty, starting shutdown timer")
        elif now - empty_since >= WD_POWEROFF_COOLDOWN:
            logger.warning("Watchdog: server remained empty, cooldown passed — shutting down VPS")
            if notify_callback:
                await notify_callback(f"🛑 На сервере не было игроков больше {WD_POWEROFF_COOLDOWN // 60} минут."
                                      f" Отправлена команда на выключение VPS.")
            await shutdown_callback()
            empty_since = None  # Reset after shutdown
            notified = False  # сбрасываем флаг после выключения
            is_fresh_start = True # следующий запуск будет новым
        else:
            remaining = int(WD_POWEROFF_COOLDOWN - (now - empty_since))
            logger.info(f"Watchdog: server still empty, {remaining} seconds left until shutdown")
            if notify_callback and not notified:
                await notify_callback(f"ℹ️ На сервере нет игроков. "
                                      f"Сервер будет выключен через {(remaining + 60) // 60} минут.")
                                     # поправка на задержку вызова задачи
                notified = True  # для однократного вывода

    else:
        if empty_since is not None:
            logger.info("Watchdog: players joined — resetting shutdown timer")
            empty_since = None  # Reset timer because players are online
