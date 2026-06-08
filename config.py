import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

BASE_URL = "https://gefest.ua"
SEARCH_URL = "https://gefest.ua/search"

DB_PATH = os.path.join(os.path.dirname(__file__), "gefest.db")

# Сколько раз в N часов обновлять каталог квартир
PARSE_INTERVAL_HOURS = 12

CONTACT_TELEGRAM = "@romanova_neruhomist"
CONTACT_PHONE = "+380930828903"

FLATS_PER_PAGE = 5
