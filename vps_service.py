"""Функции управления VPS сервером"""
import logging
import time
import api
import watchdog
from minecraft_server import mc_server
from telegram_bot import tg_bot

logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)

# Время последнего успешного запуска VPS (в секундах с эпохи)
last_poweron_time = 0
last_poweroff_time = 0
# Время последнего запроса статуса сервера
last_status_time = 0

async def shutdown_vps():
    global last_poweron_time
    now = time.time()
    result = await api.api_request("ShutDownGuestOS")
    logger.debug(f"shutdown_vps_API_result = {result}")
    if "error" in result:
        return result  # ничего не трогаем
    # считаем, что shutdown инициирован успешно
    last_poweron_time = now  # предотвращение быстрого запуска VPS после включения
    # после выключения VPS сбрасываем задачу и состояние watchdog
    watchdog.watchdog_stop()
    watchdog.reset_watchdog_state()
    mc_server.reset_runtime()  # сброс runtime состояния MC сервера
    tg_bot.active_chats.clear()  # сброс активных чатов для уведомлений после выключения сервера
    logger.info("Shutdown VPS initiated successfully")
    return result