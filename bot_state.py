"""Датакласс для хранения состояния Telegram бота"""
import os
from dataclasses import dataclass, field

@dataclass
class BotState:
    # константы
    POWERON_COOLDOWN = 20 * 60  # 20 минут в секундах
    POWEROFF_COOLDOWN = 1 * 60  # 1 минута
    STATUS_COOLDOWN = 5  # запрос статуса
    authorized_file: str = "authorized.json"
    telegram_token: str = os.getenv("TELEGRAM_TOKEN")
    admin_chat_id: int = int(os.getenv("ADMIN_CHAT_ID"))  # type: ignore
    #runtime
    maintenance_mode: bool = False
    active_chats: set[int] = field(default_factory=set)  # Список чатов, в которые шлются уведомления


bot_state = BotState() # Общий shared instance состояния телеграм бота
