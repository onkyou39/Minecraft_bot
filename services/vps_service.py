"""Функции управления VPS сервером"""
import logging
import time
from integrations import api
from dataclasses import dataclass

logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)

@dataclass
class VPSState:
    # Время последнего успешного запуска VPS (в секундах с эпохи)
    last_poweron_time: float = 0
    last_poweroff_time: float = 0
    # Время последнего запроса статуса сервера
    last_status_time: float = 0

vps_state = VPSState()


async def shutdown_vps():
    now = time.time()
    result = await api.api_request("ShutDownGuestOS")
    logger.debug(f"shutdown_vps_API_result = {result}")
    if "error" in result:
        return result  # ничего не трогаем
    # считаем, что shutdown инициирован успешно
    vps_state.last_poweron_time = now  # предотвращение быстрого запуска VPS после включения
    return result

async def poweron_vps():
    # TODO вынести сюда логику из /poweron хендлера
    pass