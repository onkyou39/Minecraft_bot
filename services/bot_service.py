from functools import wraps
from telegram.ext import ContextTypes
from config.config import bot_config
import json
import logging
from telegram import Update

logger = logging.getLogger(__name__)

def log_command(command_name):
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            logger.info(f"{get_user_name(update)} sent COMMAND {command_name}")
            return await func(update, context, *args, **kwargs)

        return wrapper

    return decorator

def load_auth_data():
    try:
        with open(bot_config.authorized_file, "r") as f:
            data = json.load(f)
            # Преобразуем список пользователей в словарь с int ключами
            users = {int(user["id"]): user.get("username", "")
                     for user in data.get("users", [])}
            return users, set(data.get("groups", []))
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Authorization file not found or corrupted. Using empty sets.")
        return {}, set()


def save_auth_data():
    data = {
        "users": [{"id": uid, "username": name}
                  for uid, name in authorized_users.items()],
        "groups": list(authorized_groups)
    }
    with open(bot_config.authorized_file, "w") as f:
        json.dump(data, f, indent=2)


authorized_users, authorized_groups = load_auth_data()


def is_authorized(chat_id: int) -> bool:
    return (
            chat_id in authorized_users
            or chat_id in authorized_groups
            or chat_id == bot_config.admin_chat_id
    )


def get_user_name(update: Update) -> str:
    return update.effective_user.username or update.effective_user.full_name or "Неизвестный пользователь"


async def notify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    user_name = get_user_name(update)
    message = f"Пользователь @{user_name} {action}."
    await context.bot.send_message(chat_id=bot_config.admin_chat_id, text=message)


async def log_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = get_user_name(update)
    message = update.message
    if message:
        logger.info(f"[{user_name}] написал: {message.text or '[нет текста]'}")