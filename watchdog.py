import asyncio
import logging
from mcstatus import JavaServer

# === Настройки ===
SERVER_ADDRESS = "example.com"  # или IP
QUERY_PORT = 25565
CHECK_INTERVAL = 60  # секунд между проверками

#LOG_FILE = "/var/log/mc_query_watchdog.log"

# === Логгирование ===
logging.basicConfig(
    #filename=LOG_FILE,
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)

async def check_server_players(server_address: str, port: int):
    try:
        server = await JavaServer.async_lookup(f"{server_address}:{port}")
        status = await server.async_query()  # Query-запрос

        players_online = status.players.online
        player_names = status.players.list
        logging.info(f"🟢 Онлайн {players_online} игроков: {player_names}")
        return players_online, player_names

    except Exception as e:
        logging.warning(f"🔴 Сервер недоступен: {e}")
        return None, []

async def main():
    while True:
        players, names = await check_server_players(SERVER_ADDRESS, QUERY_PORT)

        # Пример реакции: если сервер доступен и 0 игроков
        if players == 0:
            logging.info("Никого нет на сервере.")
            # Тут можно вызвать shutdown API или слать уведомление

        await asyncio.sleep(CHECK_INTERVAL)

asyncio.run(main())
