import argparse
import logging
from telegram.ext import ApplicationBuilder
import config.config as config
from services.watchdog import watchdog_state
from handlers.handlers import register_handlers


parser = argparse.ArgumentParser()
parser.add_argument(
    "--debug",
    action="store_true",
    help="Enable debug logging"
)
args = parser.parse_args()

# Enable logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG if args.debug else logging.INFO, force=True)

# set higher logging level for httpx to avoid all GET and POST requests being logged

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    if not config.bot_config.telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")
    application = ApplicationBuilder().token(config.bot_config.telegram_token).build()
    watchdog_state.job_queue = application.job_queue
    register_handlers(application)
    application.run_polling(poll_interval=1, timeout=30)
    #application.run_polling()
