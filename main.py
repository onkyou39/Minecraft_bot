import logging
import json
import random
import os
from functools import wraps

import aiohttp
import time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, Job, JobQueue
from watchdog import watchdog_tick, get_players_list, reset_watchdog_state
from typing import Optional

# Enable logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# set higher logging level for httpx to avoid all GET and POST requests being logged

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

notify_logger = logging.getLogger("notify")
logging.getLogger("notify").setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)


def log_command(command_name):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs): # type: ignore
            logger.info(f"{get_user_name(update)} sent COMMAND {command_name}")
            return await func(update, context, *args, **kwargs)

        return wrapper

    return decorator


load_dotenv()

AUTHORIZED_FILE = "authorized.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
API_URL = os.getenv("API_URL")
API_TOKEN = os.getenv("API_TOKEN")


MAINTENANCE_MODE = False

def check_maintenance(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
        if MAINTENANCE_MODE:
            await update.message.reply_text("🚧 Сервер на обслуживании. Попробуйте выполнить запрос позже.")
            return None
        return await func(update, context)
    return wrapper

# Время последнего успешного запуска VPS (в секундах с эпохи)
last_poweron_time = 0
last_poweroff_time = 0
# Время последнего запроса статуса сервера
last_status_time = 0
POWERON_COOLDOWN = 20 * 60  # 20 минут в секундах
POWEROFF_COOLDOWN = 1 * 60 # 1 минута
STATUS_COOLDOWN = 5  # запрос статуса

watchdog_job: Optional[Job] = None
job_queue: Optional[JobQueue] = None

active_chats = set()


def load_auth_data():
    try:
        with open(AUTHORIZED_FILE, "r") as f:
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
    with open(AUTHORIZED_FILE, "w") as f:
        json.dump(data, f, indent=2)


authorized_users, authorized_groups = load_auth_data()


def is_authorized(chat_id: int) -> bool:
    return (
            chat_id in authorized_users
            or chat_id in authorized_groups
            or chat_id == ADMIN_CHAT_ID
    )


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


async def notify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str): # type: ignore
    user_name = get_user_name(update)
    message = f"Пользователь @{user_name} {action}."
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)


async def watchdog_notifyer(message: str):
    try:
        #for chat_id in list(authorized_groups.union(authorized_users.keys())):
        for chat_id in active_chats:
            if chat_id:
                await application.bot.send_message(chat_id=chat_id, text=message) # type: ignore
        notify_logger.debug(f"Watchdog sent notification: {message}")
    except Exception as e:
        notify_logger.debug(f"Watchdog notification failed: {str(e)}")


async def log_all(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
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


def watchdog_stop():
    global watchdog_job
    if watchdog_job is not None:
        watchdog_job.schedule_removal()
        watchdog_job = None
        logger.info("Removed watchdog job")

async def shutdown_vps():
    now = time.time()
    active_chats.clear() # сброс активных чатов для уведомлений после выключения сервера
    global last_poweron_time, watchdog_job
    last_poweron_time = now  # предотвращение быстрого запуска VPS после включения
    # после выключения VPS сбрасываем задачу и состояние watchdog
    watchdog_stop()
    reset_watchdog_state()
    return await api_request("ShutDownGuestOS")


async def watchdog_task(context: ContextTypes.DEFAULT_TYPE): # type: ignore # Стандартная сигнатура для job_queue
    await watchdog_tick(shutdown_vps, watchdog_notifyer)


def watchdog_run():
    global watchdog_job
    if watchdog_job is None and not MAINTENANCE_MODE:
        watchdog_job = job_queue.run_repeating(watchdog_task, interval=60, first=10, name="minecraft_watchdog",
                                               job_kwargs={'misfire_grace_time': 2})
        logger.info("Started watchdog job")


@log_command("/start")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    chat_type = update.effective_chat.type  # 'private', 'group', 'supergroup', 'channel'
    if chat_type != 'private':
        return  # Не отвечаем на start в группе
    chat_id = update.effective_chat.id
    user_name = get_user_name(update)

    await context.bot.send_message(chat_id=ADMIN_CHAT_ID,
                                   text=f"Новый пользователь @{user_name} с chat_id {chat_id} запустил бота.")
    await update.message.reply_text("👋 Бот запущен.")



async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    sticker_pack_id = "Yobba"
    sticker_ids = [
        "CAACAgIAAxkBAAE3z4lodieCM47W6bHinF93tjxkGRqDmQACKgEAAhIWYQqnJ3JCb4AUqDYE",
        "CAACAgIAAxkBAAE3z_9odi8c9MbVLn3hs_hLG3fj4wLn5AACzgADEhZhCh-R7LyxoN4zNgQ",
        "CAACAgIAAxkBAAE30dBodlRhY-fEYqe9JK9cvU7qH_1CWwACLgADEhZhCh35t0GGHuwUNgQ",
        "CAACAgIAAxkBAAE30dNodlSWqH2v0VfOyDRhCxLFkIczgwACRwADEhZhCrRQN4OAC7NgNgQ",
        "CAACAgIAAxkBAAE30dVodlSkh25IexHxy8993PW2kddXggACQQADEhZhCsA0AlL-qBT-NgQ",
        "CAACAgIAAxkBAAE30dlodlVdvCKXjmHqshQnMlsWWBQ2hwACkAADEhZhCrZOJci98N_TNgQ",
        "CAACAgIAAxkBAAE30dtodlWgCk4M8LoEDC7-y99EJYEhagACEwEAAhIWYQpLBK0xp4kFOzYE",
        "CAACAgIAAxkBAAE30d1odlW8VXM4X4_8mUXrYpgZeHzbBQACzAADEhZhCiZG0nB7WA-qNgQ",
    ]
    #await update.message.reply_text(update.message.text)
    """chat_type = update.effective_chat.type  # 'private', 'group', 'supergroup', 'channel'
    if chat_type != 'private':
        return  # Не отвечаем на некомандные сообщения в группе"""

    """user_name = get_user_name(update)
    message_text = update.message.text
    logger.info(f"Message from {user_name}: {message_text}")"""
    random_sticker = random.choice(sticker_ids)
    await update.message.reply_sticker(random_sticker)
    #await update.message.reply_text(random.choice(["🌚", "🌝"]))


@log_command("/addgroup")
async def addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❗ Эта команда работает только в группе.")
        return

    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Только администратор может добавить группу.")
        return

    if update.effective_chat.id in authorized_groups:
        await update.message.reply_text("ℹ️ Группа уже добавлена.")
        return

    authorized_groups.add(update.effective_chat.id)
    save_auth_data()
    await update.message.reply_text("✅ Группа успешно добавлена в список разрешённых.")


@log_command("/adduser")
async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Только администратор может добавлять пользователей.")
        return

    if not context.args or len(context.args) > 2:
        await update.message.reply_text(
            "ℹ️ Использование: /adduser user_id [@username]\n"
            "Пример: /adduser 123456 @user"
        )
        return

    user_id = context.args[0]
    if not user_id.isdigit():
        await update.message.reply_text("⛔ user_id должен быть числом.")
        return

    username = context.args[1].lstrip("@") if len(context.args) == 2 else ""

    if int(user_id) in authorized_users:
        await update.message.reply_text(f"ℹ️ Пользователь {user_id} уже в списке.")
        return

    authorized_users[int(user_id)] = username
    save_auth_data()

    await update.message.reply_text(
        f"✅ Добавлен пользователь {user_id} (@{username})" if username else f"✅ Добавлен пользователь {user_id}")


@log_command("/removegroup")
async def removegroup(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❗ Эта команда работает только в группе.")
        return

    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Только администратор может удалить группу.")
        return

    if update.effective_chat.id in authorized_groups:
        authorized_groups.remove(update.effective_chat.id)
        save_auth_data()
        await update.message.reply_text("✅ Группа удалена из списка разрешённых.")
    else:
        await update.message.reply_text("ℹ️ Группа не была в списке.")


@log_command("/removeuser")
async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    # Проверка прав администратора
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Только администратор может удалять пользователей.")
        return

    # Проверка наличия ровно одного аргумента
    if len(context.args) != 1:
        await update.message.reply_text(
            "ℹ️ Использование: /removeuser user_id\n"
            "Пример: /removeuser 12345"
        )
        return

    user_id = context.args[0]
    if not user_id.isdigit():
        await update.message.reply_text("⛔ user_id должен быть числом.")
        return

    if int(user_id) not in authorized_users:
        await update.message.reply_text(f"ℹ️ Пользователь {user_id} не найден в списке.")
        return

    # Удаляем пользователя
    authorized_users.pop(int(user_id))

    # Сохраняем изменения
    save_auth_data()

    await update.message.reply_text(f"✅ Пользователь {user_id} удалён.")


@log_command("/authorized")
async def list_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    # Проверка прав администратора
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Только администратор может просматривать этот список.")
        return

    message = ["📋 Список авторизованных:"]

    # Список пользователей с именами, если есть
    if authorized_users:
        users_list = "\n".join(
            f"👤 {user_id}" + (f" (@{username})" if username else "")
            for user_id, username in sorted(authorized_users.items(), key=lambda x: int(x[0]))
        )
        message.append(f"\n🔹 Пользователи ({len(authorized_users)}):\n{users_list}")
    else:
        message.append("\n🔹 Пользователи: список пуст")

    # Список групп
    if authorized_groups:
        groups_list = "\n".join(f"👥 {group_id}" for group_id in sorted(authorized_groups))
        message.append(f"\n🔹 Группы ({len(authorized_groups)}):\n{groups_list}")
    else:
        message.append("\n🔹 Группы: список пуст")

    # Инструкция по управлению
    message.append("\nℹ️ Используйте /adduser, /removeuser, /addgroup, /removegroup для управления")

    await update.message.reply_text("".join(message))


@check_maintenance
@log_command("/poweron")
async def poweron(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    global last_poweron_time, last_status_time, active_chats

    if not is_authorized(update.effective_chat.id):
        await update.message.reply_text("⛔ Недостаточно прав для выполнения команды.")
        return

    active_chats.add(update.effective_chat.id)

    now = time.time()

    if now - last_status_time < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - last_status_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд перед повторным запросом.")
        return

    try:
        # Запрос текущего статуса
        server_status = await get_server_status()

        if "error" in server_status:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {server_status['error']}")
            return

        is_power_on = server_status.get("IsPowerOn")
        if is_power_on:
            await update.message.reply_text("✅ Сервер уже включен.")
            watchdog_run()
            last_status_time = now
            return
        elif is_power_on is False:
            if now - last_poweron_time < POWERON_COOLDOWN:
                remaining = int(POWERON_COOLDOWN - (now - last_poweron_time))
                await update.message.reply_text(f"⏳ Подождите {(remaining / 60):.2f} минут(у)"
                                                f" перед повторным включением сервера.")
                return
            # Отправка запроса на включение
            result = await api_request("PowerOn")

            if "error" in result:
                await update.message.reply_text(f"⚠️ Ошибка: {result['error']}")
                return

            watchdog_run()

            state = result.get("State", "Unknown")
            if state == "InProgress":
                await update.message.reply_text("✅ Запрос на включение отправлен, пожалуйста, подождите...")
            else:
                await update.message.reply_text(f"✅ Запрос отправлен. Статус: {state}")

            last_poweron_time = now
            last_status_time = now

            chat_type = update.effective_chat.type  # 'private', 'group', 'supergroup', 'channel'
            if chat_type == 'private':
                await notify_admin(update, context, "отправил запрос на включение сервера")

        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.exception(f"Error in poweron command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")


@log_command("/poweroff")
async def poweroff(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    """Обработчик команды /poweroff"""
    global last_poweroff_time, last_status_time  # Аналогично poweron

    # Проверка прав
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Недостаточно прав для выполнения команды.")
        return

    # Проверка кулдауна
    now = time.time()
    if now - last_poweroff_time < POWEROFF_COOLDOWN:
        remaining = int(POWEROFF_COOLDOWN - (now - last_poweroff_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} сек. перед повторным выключением.")
        return

    if now - last_status_time < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - last_status_time))
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
            last_status_time = now
            return

        elif is_power_on:
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

            last_poweroff_time = now
            last_status_time = now

            #await notify_admin(update, context, "отправил запрос на выключение сервера")

        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.exception(f"Error in poweroff command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")


@check_maintenance
@log_command("/status")
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    global last_status_time

    if not is_authorized(update.effective_chat.id):
        await update.message.reply_text("⛔ Недостаточно прав для выполнения команды.")
        return

    now = time.time()
    if now - last_status_time < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - last_status_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд перед повторным запросом статуса сервера.")
        return

    try:

        # Запрос текущего статуса
        server_status = await get_server_status()

        if "error" in server_status:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {server_status['error']}")
            return
        last_status_time = now  # обновляем время успешного запроса статуса
        is_power_on = server_status.get("IsPowerOn")
        if is_power_on:
            active_chats.add(update.effective_chat.id) # добавляем чат для уведомлений только если сервер активен
            players = await get_players_list()
            if players is not None:
                await update.message.reply_text(f"🟢 Сервер включен. На сервере {players} игрок(ов).")
                watchdog_run()
            else:
                await update.message.reply_text("🟡 Linux cервер включен. Minecraft сервер не запущен.")
        elif is_power_on is False:
            await update.message.reply_text("🔴 Сервер выключен.")
            watchdog_stop()
        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.error(f"Error in status command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")


@log_command("/maintain")
async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE): # type: ignore
    global MAINTENANCE_MODE
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Недостаточно прав для выполнения команды.")
        return

    MAINTENANCE_MODE = not MAINTENANCE_MODE

    if MAINTENANCE_MODE:
        watchdog_stop()
        await update.message.reply_text(f"🚧 Режим обслуживания включен.")
    else:
        await update.message.reply_text(f"🎮 Режим обслуживания выключен.")


if __name__ == "__main__":
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    if job_queue is None:
        job_queue = application.job_queue
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("poweron", poweron))
    application.add_handler(CommandHandler("poweroff", poweroff))
    application.add_handler(CommandHandler("addgroup", addgroup))
    application.add_handler(CommandHandler("removegroup", removegroup))
    application.add_handler(CommandHandler("adduser", adduser))
    application.add_handler(CommandHandler("removeuser", removeuser))
    application.add_handler(CommandHandler("authorized", list_authorized))
    application.add_handler(CommandHandler("maintain", maintenance))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, echo))
    #application.add_handler(MessageHandler(filters.ALL, log_all), group=0) # для логирования всего
    application.run_polling(poll_interval=1, timeout=30)
    #application.run_polling()