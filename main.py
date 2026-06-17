import logging
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder
from config.config import bot_config
from services.watchdog import watchdog_state
from handlers.handlers import register_handlers

# Enable logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# set higher logging level for httpx to avoid all GET and POST requests being logged

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if __name__ == "__main__":
    application = ApplicationBuilder().token(bot_config.telegram_token).build()
    if watchdog_state.job_queue is None:
        watchdog_state.job_queue = application.job_queue
    register_handlers(application)
    application.run_polling(poll_interval=1, timeout=30)
    #application.run_polling()
