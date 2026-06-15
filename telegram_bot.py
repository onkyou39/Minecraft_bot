"""Датакласс для хранения состояния Telegram бота"""
import os
from dataclasses import dataclass

@dataclass
class TgBot:
    # константы
    AUTHORIZED_FILE = "authorized.json"
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))  # type: ignore
    #runtime
    MAINTENANCE_MODE = False
    active_chats = set()  # Список чатов, в которые шлются уведомления


tg_bot = TgBot() # Общий shared instance состояния телеграм бота
