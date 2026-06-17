"""Датакласс для хранения состояния Telegram бота"""
import os
from dataclasses import dataclass, field

@dataclass
class BotState:
    maintenance_mode: bool = False
    active_chats: set[int] = field(default_factory=set)  # Список чатов, в которые шлются уведомления

bot_state = BotState() # Общий shared instance состояния телеграм бота
