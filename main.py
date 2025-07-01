import logging

import os
import requests
import time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# Enable logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# set higher logging level for httpx to avoid all GET and POST requests being logged

logging.getLogger("httpx").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)

def log_command(command_name):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            logger.warning(f"{get_user_name(update)} sent COMMAND {command_name}")
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AUTHORIZED_CHAT_ID = int(os.getenv("AUTHORIZED_CHAT_ID"))
API_URL = os.getenv("API_URL")
API_TOKEN = os.getenv("API_TOKEN")

# Время последнего успешного запуска VPS (в секундах с эпохи)
last_poweron_time = 0
# Время последнего запроса статуса сервера
last_status_time = 0
POWERON_COOLDOWN = 20 * 60  # 20 минут в секундах
STATUS_COOLDOWN = 30 # 30 секунд на запрос статуса


def get_user_name(update: Update) -> str:
    return update.effective_user.username or update.effective_user.full_name or "Неизвестный пользователь"

async def notify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    user_name = get_user_name(update)
    message = f"Пользователь @{user_name} {action}."
    await context.bot.send_message(chat_id=AUTHORIZED_CHAT_ID, text=message)

@log_command("/start")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_name = update.effective_user.username or update.effective_user.full_name

    await context.bot.send_message(chat_id=AUTHORIZED_CHAT_ID,
        text=f"Новый пользователь @{user_name} с chat_id {chat_id} запустил бота.")
    await update.message.reply_text("Привет!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #await update.message.reply_text(update.message.text)
    await update.message.reply_text("Я пока ещё не умею отвечать на сообщения 😐")

@log_command("/poweron")
async def poweron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_poweron_time

    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        await update.message.reply_text("⛔ У тебя нет доступа.")
        return

    now = time.time()
    if now - last_poweron_time < POWERON_COOLDOWN:
        remaining = int(POWERON_COOLDOWN - (now - last_poweron_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд перед повторным включением сервера.")
        return

    try:
        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json"
        }

        response = requests.get(API_URL, headers=headers)
        if response.ok:
            data = response.json()
            is_power_on = data.get("IsPowerOn")
            if is_power_on is True:
                await update.message.reply_text("✅ Сервер уже включен.")
                last_poweron_time = now  # обновляем время успешного запуска
                return
            elif is_power_on is False:
                url = f"{API_URL}/Action"
                json_data = {"Type": "PowerOn"}

                response = requests.post(url, headers=headers, json=json_data)

                if response.ok:
                    data = response.json()
                    state = data.get("State", "Unknown")
                    if state == "InProgress":
                        await update.message.reply_text("✅ Сервер запускается, пожалуйста, подождите...")
                        last_poweron_time = now  # обновляем время успешного запуска
                    else:
                        await update.message.reply_text(f"✅ Запрос отправлен. Статус: {state}")
                        last_poweron_time = now  # обновляем время успешного запуска

                    await notify_admin(update, context, "отправил запрос на включение сервера")

                else:
                    await update.message.reply_text(f"⚠️ Ошибка: {response.status_code}\n{response.text}")

    except Exception as e:
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")

@log_command("/status")
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global last_status_time

    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        await update.message.reply_text("⛔ У тебя нет доступа.")
        return

    now = time.time()
    if now - last_status_time < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - last_status_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд перед повторным запросом статуса сервера.")
        return

    try:

        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json"
        }
        response = requests.get(API_URL, headers=headers)
        if response.ok:
            last_status_time = now  # обновляем время успешного запроса статуса
            data = response.json()
            is_power_on = data.get("IsPowerOn")
            if is_power_on is True:
                await update.message.reply_text("🟢 Сервер включен.")
            elif is_power_on is False:
                await update.message.reply_text("🔴 Сервер выключен.")
            else:
                await update.message.reply_text("❓ Не удалось определить состояние сервера.")
        else:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {response.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")

if __name__ == "__main__":
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("poweron", poweron))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.run_polling()
