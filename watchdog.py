import logging
import time
from mcstatus import JavaServer
from typing import Optional

SERVER_ADDRESS = "example.com"  # или IP
QUERY_PORT = 25565
CHECK_INTERVAL = 60  # секунд между проверками
WD_POWEROFF_COOLDOWN = 10 * 60 # 10 минут


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)

async def check_server_players(server_address: str, port: int):
    try:
        server = await JavaServer.async_lookup(f"{server_address}:{port}")
        status = await server.async_query()  # Query-запрос

        players_online = status.players.online
        player_names = status.players.list
        logging.info(f"Watchdog: ONLINE {players_online} players online: {player_names}")
        return players_online, player_names

    except Exception as e:
        logging.info(f"Watchdog: OFFLINE  Minecraft server unreachable. {e}")
        return None, None


empty_since: Optional[float] = None  # Когда сервер стал пустым
notified = False # Флаг для уведомлений

async def watchdog_tick(shutdown_callback, notify_callback=None):
    global empty_since, notified
    players, names = await check_server_players(SERVER_ADDRESS, QUERY_PORT)
    now = time.time()

    if players == 0:
        if empty_since is None:
            empty_since = now
            logging.info("Watchdog: server is empty, starting shutdown timer")
        elif now - empty_since >= WD_POWEROFF_COOLDOWN:
            logging.info("Watchdog: server remained empty, cooldown passed — shutting down VPS")
            if notify_callback:
                await notify_callback(f"🛑 На сервере не было игроков больше {WD_POWEROFF_COOLDOWN // 60} минут."
                                      f" Отправлена команда на выключение VPS.")
            await shutdown_callback()
            empty_since = None  # Reset after shutdown
            notified = False  # сбрасываем флаг после выключения
        else:
            remaining = int(WD_POWEROFF_COOLDOWN - (now - empty_since))
            logging.info(f"Watchdog: server still empty, {remaining} seconds left until shutdown")
            if notify_callback and not notified:
                await notify_callback(f"ℹ️ На сервере нет игроков. "
                                      f"Сервер будет выключен через {remaining // 60} минут")
                notified = True  # для однократного вывода

    else:
        if empty_since is not None:
            logging.info("Watchdog: players joined — resetting shutdown timer")
            empty_since = None  # Reset timer because players are online