import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import database as db
import scraper
from bot import create_bot, create_dispatcher
from config import BOT_TOKEN, PARSE_INTERVAL_HOURS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("main")


def update_catalog():
    log.info("Запуск оновлення каталогу квартир...")
    try:
        flats = scraper.crawl_all(with_details=True)
        if flats:
            db.replace_all_flats(flats)
            log.info("Каталог оновлено, квартир у базі: %s", db.count_flats())
        else:
            log.warning("Парсер не повернув жодної квартири, база лишилась без змін")
    except Exception:
        log.exception("Помилка під час оновлення каталогу")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задано BOT_TOKEN. Створіть файл .env на основі .env.example")

    db.init_db()

    # Если база пуста — наповнюємо її одразу, щоб бот міг одразу відповідати
    if db.count_flats() == 0:
        await asyncio.to_thread(update_catalog)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: asyncio.create_task(asyncio.to_thread(update_catalog)),
        "interval",
        hours=PARSE_INTERVAL_HOURS,
        id="update_catalog",
    )
    scheduler.start()

    bot = create_bot(BOT_TOKEN)
    dp = create_dispatcher()

    log.info("Бот запущено")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
