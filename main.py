import logging

import random
import os
import aiohttp
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
            logger.info(f"{get_user_name(update)} sent COMMAND {command_name}")
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AUTHORIZED_CHAT_ID = int(os.getenv("AUTHORIZED_CHAT_ID"))
API_URL = os.getenv("API_URL")
API_TOKEN = os.getenv("API_TOKEN")

# Время последнего успешного запуска VPS (в секундах с эпохи)
LAST_POWERON_TIME = 0
LAST_POWEROFF_TIME = 0
# Время последнего запроса статуса сервера
LAST_STATUS_TIME = 0
POWERON_COOLDOWN = 20 * 60  # 20 минут в секундах
POWEROFF_COOLDOWN = 30
STATUS_COOLDOWN = 30 # 30 секунд на запрос статуса


def get_user_name(update: Update) -> str:
    return update.effective_user.username or update.effective_user.full_name or "Неизвестный пользователь"

async def get_server_status():
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL, headers=headers) as response:
            if response.status == 200:
                return await response.json()
            return {"error": f"{response.status}: {await response.text()}"}

async def notify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    user_name = get_user_name(update)
    message = f"Пользователь @{user_name} {action}."
    await context.bot.send_message(chat_id=AUTHORIZED_CHAT_ID, text=message)

async def log_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = get_user_name(update)
    message = update.message
    if message:
        logger.info(f"[{user_name}] написал: {message.text or '[нет текста]'}")

async def api_request(action: str):
    """Общая функция для API-запросов"""
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }
    json_data = {"Type": action}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/Action", headers=headers, json=json_data) as response:
                if response.status == 200:
                    return await response.json()
                error_text = await response.text()
                return {"error": f"API error {response.status}: {error_text}"}
    except Exception as e:
        return {"error": f"Connection error: {str(e)}"}

async def shutdown_vps():
    return await api_request("ShutDownGuestOS")

@log_command("/start")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_name = update.effective_user.username or update.effective_user.full_name

    await context.bot.send_message(chat_id=AUTHORIZED_CHAT_ID,
        text=f"Новый пользователь @{user_name} с chat_id {chat_id} запустил бота.")
    await update.message.reply_text("Привет!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #await update.message.reply_text(update.message.text)
    user_name = get_user_name(update)
    message_text = update.message.text
    logger.info(f"Message from {user_name}: {message_text}")
    await update.message.reply_text(random.choice(["🌚", "🌝"]))

@log_command("/poweron")
async def poweron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_POWERON_TIME, LAST_STATUS_TIME

    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        await update.message.reply_text("⛔ У тебя нет доступа.")
        return

    now = time.time()
    if now - LAST_POWERON_TIME < POWERON_COOLDOWN:
        remaining = int(POWERON_COOLDOWN - (now - LAST_POWERON_TIME))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд перед повторным включением сервера.")
        return

    if now - LAST_STATUS_TIME < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - LAST_STATUS_TIME))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд перед повторным запросом.")
        return

    try:
        # Запрос текущего статуса
        server_status = await get_server_status()

        if "error" in server_status:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {server_status['error']}")
            return
        is_power_on = server_status.get("IsPowerOn")

        if is_power_on is True:
            await update.message.reply_text("✅ Сервер уже включен.")
            LAST_STATUS_TIME = now
            return

        elif is_power_on is False:
            # Отправка запроса на включение
            result = await api_request("PowerOn")

            if "error" in result:
                await update.message.reply_text(f"⚠️ Ошибка: {result['error']}")
                return

            state = result.get("State", "Unknown")
            if state == "InProgress":
                await update.message.reply_text("✅ Сервер запускается, пожалуйста, подождите...")
            else:
                await update.message.reply_text(f"✅ Запрос отправлен. Статус: {state}")

            LAST_POWERON_TIME = now
            await notify_admin(update, context, "отправил запрос на включение сервера")

        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.exception(f"Error in poweron command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")


@log_command("/poweroff")
async def poweroff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /poweroff"""
    global LAST_POWEROFF_TIME, LAST_STATUS_TIME  # Аналогично poweron

    # Проверка прав
    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        await update.message.reply_text("⛔ У тебя нет доступа.")
        return

    # Проверка кулдауна
    now = time.time()
    if now - LAST_POWEROFF_TIME < POWEROFF_COOLDOWN:
        remaining = int(POWEROFF_COOLDOWN - (now - LAST_POWEROFF_TIME))
        await update.message.reply_text(f"⏳ Подождите {remaining} сек. перед повторным выключением.")
        return

    if now - LAST_STATUS_TIME < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - LAST_STATUS_TIME))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд перед повторным запросом.")
        return

    try:
        # Запрос текущего статуса
        server_status = await get_server_status()

        if "error" in server_status:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {server_status['error']}")
            return
        is_power_on = server_status.get("IsPowerOn")

        if is_power_on is False:
            await update.message.reply_text("✅ Сервер уже выключен.")
            LAST_STATUS_TIME = now
            return

        elif is_power_on is True:
            # Отправка запроса на выключение
            result = await shutdown_vps()

            if "error" in result:
                await update.message.reply_text(f"⚠️ Ошибка: {result['error']}")
                return

            state = result.get("State", "Unknown")
            if state == "InProgress":
                await update.message.reply_text("✅ Сервер выключается, пожалуйста, подождите...")
            else:
                await update.message.reply_text(f"✅ Запрос отправлен. Статус: {state}")

            LAST_POWEROFF_TIME = now
            await notify_admin(update, context, "отправил запрос на выключение сервера")

        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.exception(f"Error in poweroff command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")


@log_command("/status")
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global LAST_STATUS_TIME

    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        await update.message.reply_text("⛔ У тебя нет доступа.")
        return

    now = time.time()
    if now - LAST_STATUS_TIME < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - LAST_STATUS_TIME))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд перед повторным запросом статуса сервера.")
        return

    try:

        # Запрос текущего статуса
        server_status = await get_server_status()

        if "error" in server_status:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {server_status['error']}")
            return
        LAST_STATUS_TIME = now  # обновляем время успешного запроса статуса
        is_power_on = server_status.get("IsPowerOn")
        if is_power_on is True:
            await update.message.reply_text("🟢 Сервер включен.")
        elif is_power_on is False:
            await update.message.reply_text("🔴 Сервер выключен.")
        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.error(f"Error in status command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")

if __name__ == "__main__":
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("poweron", poweron))
    application.add_handler(CommandHandler("poweroff", poweroff))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, echo))
    #application.add_handler(MessageHandler(filters.ALL, log_all), group=0) # для логирования всего
    application.run_polling()
