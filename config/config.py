import os
from dataclasses import dataclass

@dataclass(frozen=True)
class BotConfig:
    # константы
    poweron_cooldown: int = 20 * 60  # 20 минут в секундах
    poweroff_cooldown: int = 1 * 60  # 1 минута
    status_cooldown: int = 5  # запрос статуса
    authorized_file: str = "authorized.json"
    telegram_token: str = os.getenv("TELEGRAM_TOKEN")
    admin_chat_id: int = int(os.getenv("ADMIN_CHAT_ID"))  # type: ignore


bot_config = BotConfig()