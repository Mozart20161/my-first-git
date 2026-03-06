import asyncio
import logging

from football_bot.app import create_app
from football_bot.config import load_config
from football_bot.state import BotState
from football_bot.storage import load_state


async def main() -> None:
    cfg = load_config()
    state = BotState()
    load_state(cfg.data_file, state)

    bot, dp, scheduler = create_app(cfg, state)
    scheduler.start()
    logging.info("✅ Планировщик запущен")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
