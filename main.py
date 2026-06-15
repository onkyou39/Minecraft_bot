import logging
import api
import vps_service
import watchdog
import json
import random
from telegram_bot import tg_bot
from functools import wraps
import time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from minecraft_server import mc_server
from watchdog import watchdog_state

# Enable logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# set higher logging level for httpx to avoid all GET and POST requests being logged

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

notify_logger = logging.getLogger("notify")
logging.getLogger("notify").setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def log_command(command_name):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):  # type: ignore
            logger.info(f"{get_user_name(update)} sent COMMAND {command_name}")
            return await func(update, context, *args, **kwargs)

        return wrapper

    return decorator


load_dotenv()



def check_maintenance(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
        if tg_bot.maintenance_mode:
            await update.message.reply_text("🚧 Сервер на обслуживании. Попробуйте выполнить запрос позже.")
            return None
        return await func(update, context)

    return wrapper


def check_permissions(func):
    """Декоратор проверки прав доступа"""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Недостаточно прав для выполнения команды.")
            return None
        return await func(update, context)

    return wrapper


# Кэшированный статус Minecraft-сервера
mc_server.online = False
POWERON_COOLDOWN = 20 * 60  # 20 минут в секундах
POWEROFF_COOLDOWN = 1 * 60  # 1 минута
STATUS_COOLDOWN = 5  # запрос статуса



def load_auth_data():
    try:
        with open(tg_bot.authorized_file, "r") as f:
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
    with open(tg_bot.authorized_file, "w") as f:
        json.dump(data, f, indent=2)


authorized_users, authorized_groups = load_auth_data()


def is_authorized(chat_id: int) -> bool:
    return (
            chat_id in authorized_users
            or chat_id in authorized_groups
            or chat_id == tg_bot.admin_chat_id
    )


def get_user_name(update: Update) -> str:
    return update.effective_user.username or update.effective_user.full_name or "Неизвестный пользователь"


async def notify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):  # type: ignore
    user_name = get_user_name(update)
    message = f"Пользователь @{user_name} {action}."
    await context.bot.send_message(chat_id=tg_bot.admin_chat_id, text=message)


async def log_all(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    user_name = get_user_name(update)
    message = update.message
    if message:
        logger.info(f"[{user_name}] написал: {message.text or '[нет текста]'}")


@log_command("/start")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    chat_type = update.effective_chat.type  # 'private', 'group', 'supergroup', 'channel'
    if chat_type != 'private':
        return  # Не отвечаем на start в группе
    chat_id = update.effective_chat.id
    user_name = get_user_name(update)

    await context.bot.send_message(chat_id=tg_bot.admin_chat_id,
                                   text=f"Новый пользователь @{user_name} с chat_id {chat_id} запустил бота.")
    await update.message.reply_text("👋 Бот запущен.")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
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
async def addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❗ Эта команда работает только в группе.")
        return

    if update.effective_user.id != tg_bot.admin_chat_id:
        await update.message.reply_text("⛔ Только администратор может добавить группу.")
        return

    if update.effective_chat.id in authorized_groups:
        await update.message.reply_text("ℹ️ Группа уже добавлена.")
        return

    authorized_groups.add(update.effective_chat.id)
    save_auth_data()
    await update.message.reply_text("✅ Группа успешно добавлена в список разрешённых.")


@log_command("/adduser")
async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    if update.effective_user.id != tg_bot.admin_chat_id:
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
async def removegroup(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❗ Эта команда работает только в группе.")
        return

    if update.effective_user.id != tg_bot.admin_chat_id:
        await update.message.reply_text("⛔ Только администратор может удалить группу.")
        return

    if update.effective_chat.id in authorized_groups:
        authorized_groups.remove(update.effective_chat.id)
        save_auth_data()
        await update.message.reply_text("✅ Группа удалена из списка разрешённых.")
    else:
        await update.message.reply_text("ℹ️ Группа не была в списке.")


@log_command("/removeuser")
async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    # Проверка прав администратора
    if update.effective_user.id != tg_bot.admin_chat_id:
        await update.message.reply_text("⛔ Только администратор может удалять пользователей.")
        return

    # Проверка наличия ровно одного аргумента
    if len(context.args) != 1:  # type: ignore
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
async def list_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    # Проверка прав администратора
    if update.effective_user.id != tg_bot.admin_chat_id:
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
@check_permissions
@log_command("/poweron")
async def poweron(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    now = time.time()

    if len(context.args) == 1 and context.args[0] == "force":  # type: ignore
        if update.effective_user.id != tg_bot.admin_chat_id:
            await update.message.reply_text("⛔ Недостаточно прав для принудительного включения.")
            return
    elif context.args:
        await update.message.reply_text("⚠️ Неправильно введённая команда.")
        return

    if now - vps_service.vps_state.last_status_time < STATUS_COOLDOWN and not context.args:
        remaining = int(STATUS_COOLDOWN - (now - vps_service.vps_state.last_status_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд(у) перед повторным запросом.")
        return

    try:
        # Запрос текущего статуса VPS
        server_status = await api.get_vps_server_status()
        # Запрос текущего статуса Minecraft
        await watchdog.refresh_mc_server_state()

        if "error" in server_status:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {server_status['error']}")
            return
        tg_bot.active_chats.add(update.effective_chat.id)  # Вывод уведомлений о статусе сервера в текущий чат
        is_power_on = server_status.get("IsPowerOn")
        if is_power_on:
            await update.message.reply_text("✅ Сервер уже включен.")
            watchdog.watchdog_run()
            vps_service.vps_state.last_status_time = now
            return
        elif is_power_on is False:
            if now - vps_service.vps_state.last_poweron_time < POWERON_COOLDOWN and not context.args:
                remaining = int(POWERON_COOLDOWN - (now - vps_service.vps_state.last_poweron_time))
                await update.message.reply_text(
                    f"⏳ Подождите {remaining if remaining < 60 else f'{(remaining / 60):.0f}'} "
                    f"{'секунд(у)' if remaining < 60 else 'минут(у)'} "
                    f"перед повторным включением сервера."
                )
                return
            # Отправка запроса на включение
            result = await api.api_request("PowerOn")

            if "error" in result:
                await update.message.reply_text(f"⚠️ Ошибка: {result['error']}")
                tg_bot.active_chats.discard(update.effective_chat.id)  # Сброс уведомлений при ошибке
                return

            watchdog.watchdog_run()

            state = result.get("State", "Unknown")
            if state == "InProgress":
                await update.message.reply_text("✅ Запрос на включение отправлен, пожалуйста, подождите...")
            else:
                await update.message.reply_text(f"✅ Запрос отправлен. Статус: {state}")

            vps_service.vps_state.last_poweron_time = now
            vps_service.vps_state.last_status_time = now

            chat_type = update.effective_chat.type  # 'private', 'group', 'supergroup', 'channel'
            if chat_type == 'private':
                await notify_admin(update, context, "отправил запрос на включение сервера")

        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.exception(f"Error in poweron command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")


@log_command("/poweroff")
async def poweroff(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    """Обработчик команды /poweroff"""

    # Проверка прав
    if update.effective_user.id != tg_bot.admin_chat_id:
        await update.message.reply_text("⛔ Недостаточно прав для выполнения команды.")
        return

    # Проверка кулдауна
    now = time.time()
    if now - vps_service.vps_state.last_poweroff_time < POWEROFF_COOLDOWN:
        remaining = int(POWEROFF_COOLDOWN - (now - vps_service.vps_state.last_poweroff_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд(у) перед повторным выключением.")
        return

    if now - vps_service.vps_state.last_status_time < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - vps_service.vps_state.last_status_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд(у) перед повторным запросом.")
        return

    try:
        # Запрос текущего статуса
        server_status = await api.get_vps_server_status()

        if "error" in server_status:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {server_status['error']}")
            return
        is_power_on = server_status.get("IsPowerOn")

        if is_power_on is False:
            await update.message.reply_text("✅ Сервер уже выключен.")
            vps_service.vps_state.last_status_time = now
            return

        elif is_power_on:
            # Отправка запроса на выключение
            result = await vps_service.shutdown_vps()
            if "error" in result:
                await update.message.reply_text(f"⚠️ Ошибка: {result['error']}")
                return

            state = result.get("State", "Unknown")
            if state == "InProgress":
                await update.message.reply_text("✅ Сервер выключается, пожалуйста, подождите...")
            else:
                await update.message.reply_text(f"✅ Запрос отправлен. Статус: {state}")

            vps_service.vps_state.last_poweroff_time = now
            vps_service.vps_state.last_status_time = now

            #await notify_admin(update, context, "отправил запрос на выключение сервера")

        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.exception(f"Error in poweroff command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")


@check_maintenance
@check_permissions
@log_command("/status")
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore

    now = time.time()
    if now - vps_service.vps_state.last_status_time < STATUS_COOLDOWN:
        remaining = int(STATUS_COOLDOWN - (now - vps_service.vps_state.last_status_time))
        await update.message.reply_text(f"⏳ Подождите {remaining} секунд(у) перед повторным запросом статуса сервера.")
        return

    try:

        # Запрос текущего статуса VPS сервера
        server_status = await api.get_vps_server_status()

        if "error" in server_status:
            await update.message.reply_text(f"⚠️ Ошибка при запросе статуса: {server_status['error']}")
            return
        vps_service.vps_state.last_status_time = now  # обновляем время успешного запроса статуса
        is_power_on = server_status.get("IsPowerOn")
        logger.debug(f"server_status={server_status}")
        logger.debug(
            f"IsPowerOn={is_power_on}, type={type(is_power_on)}"
        )
        logger.debug(
            f"mc_server.online={mc_server.online}, "
            f"chat_muted={context.chat_data.get('muted', False)}"
        )
        if is_power_on and not context.chat_data.get("muted", False):
            tg_bot.active_chats.add(update.effective_chat.id) # добавляем чат для уведомлений только если сервер активен
            watchdog.watchdog_run()
            if mc_server.online:
                message = (
                    f"🟢 Сервер включен. "
                    f"На сервере {mc_server.players_online} игрок(ов)."
                )

                if mc_server.players_online == 0 and mc_server.shutdown_remaining is not None:
                    remaining = (
                        f"{mc_server.shutdown_remaining} сек."
                        if mc_server.shutdown_remaining < 60
                        else f"{(mc_server.shutdown_remaining / 60):.0f} мин."
                    )

                    message += f"\n⏳ До автовыключения: {remaining}"

                await update.message.reply_text(message)
            else:
                await update.message.reply_text("🟡 Minecraft сервер запускается или ещё недоступен.")
                mc_server.online = False
        elif is_power_on is False:
            await update.message.reply_text("🔴 Сервер выключен.")
            mc_server.online = False
            watchdog.watchdog_stop()
        else:
            await update.message.reply_text("❓ Не удалось определить состояние сервера.")

    except Exception as e:
        logger.error(f"Error in status command: {str(e)}")
        await update.message.reply_text(f"❗ Ошибка подключения: {e}")


@log_command("/maintain")
async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore
    if update.effective_user.id != tg_bot.admin_chat_id:
        await update.message.reply_text("⛔ Недостаточно прав для выполнения команды.")
        return

    tg_bot.maintenance_mode = not tg_bot.maintenance_mode

    if tg_bot.maintenance_mode:
        watchdog.watchdog_stop()
        await update.message.reply_text("🚧 Режим обслуживания включен.")
    else:
        await update.message.reply_text("🎮 Режим обслуживания выключен.")


@check_permissions
@log_command("/mute")
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore

    if update.effective_chat.type != 'private' and update.effective_user.id != tg_bot.admin_chat_id:
        await update.message.reply_text("⛔ В группах и каналах команда доступна только администратору.")
        return

    is_muted = context.chat_data.get("muted", False)
    context.chat_data["muted"] = not is_muted

    if context.chat_data["muted"]:
        tg_bot.active_chats.discard(update.effective_chat.id)
        await update.message.reply_text("🔇 Уведомления в этом чате выключены до перезапуска сервера.")
    else:
        tg_bot.active_chats.add(update.effective_chat.id)
        await update.message.reply_text("🔔 Уведомления включены.")


@check_permissions
@log_command("/version")
async def get_cached_mc_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Хендлер вывода текущей версии Minecraft сервера без запроса к API"""
    if mc_server.version and mc_server.online:
        await update.message.reply_text(f"ℹ️ Версия Minecraft сервера: {mc_server.version_number}")
    else:
        await update.message.reply_text("ℹ️ Версия Minecraft сервера неизвестна или сервер не запущен.")


if __name__ == "__main__":
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()  # type: ignore
    if watchdog_state.job_queue is None:
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
    application.add_handler(CommandHandler("mute", mute))
    application.add_handler(CommandHandler("version", get_cached_mc_version))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, echo))
    #application.add_handler(MessageHandler(filters.ALL, log_all), group=0) # для логирования всего
    application.run_polling(poll_interval=1, timeout=30)
    #application.run_polling()
