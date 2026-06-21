import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class BotConfig:
    # константы
    poweron_cooldown: int = 20 * 60  # 20 минут в секундах
    poweroff_cooldown: int = 1 * 60  # 1 минута
    status_cooldown: int = 5  # запрос статуса
    authorized_file: str = "authorized.json"
    telegram_token: str | None = None
    admin_chat_id: int | None = None


def load_config() -> BotConfig:
    admin_chat_id = os.getenv("ADMIN_CHAT_ID")

    return BotConfig(
        telegram_token=os.getenv("TELEGRAM_TOKEN"),
        admin_chat_id=int(admin_chat_id) if admin_chat_id else None,
    )


bot_config = load_config()