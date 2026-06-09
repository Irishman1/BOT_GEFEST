import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import database as db
import scraper
from bot import create_bot, create_dispatcher
from config import BOT_TOKEN, PARSE_INTERVAL_HOURS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("main")


async def update_catalog():
    log.info("Запуск оновлення каталогу квартир...")
    try:
        flats = await asyncio.to_thread(scraper.crawl_all, True)
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

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        update_catalog,
        "interval",
        hours=PARSE_INTERVAL_HOURS,
        id="update_catalog",
    )
    scheduler.start()
    log.info("Планувальник запущено, оновлення кожні %s год.", PARSE_INTERVAL_HOURS)

    bot = create_bot(BOT_TOKEN)
    dp = create_dispatcher()

    # Запускаємо парсинг у фоні — бот одразу доступний,
    # а якщо база порожня, відповідає "Дані ще завантажуються"
    if db.count_flats() == 0:
        asyncio.create_task(update_catalog())
        log.info("База порожня — запущено фоновий парсинг")

    log.info("Бот запущено")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
