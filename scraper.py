import logging
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import BASE_URL, SEARCH_URL

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

REQUEST_DELAY = 0.4  # пауза между запросами, чтобы не нагружать сайт


def _get(url: str, params: dict | None = None) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Ошибка запроса %s: %s", url, e)
        return None
    return BeautifulSoup(resp.text, "html.parser")


def _slug_from_url(url: str) -> str:
    """Достаёт слаг ЖК из ссылки вида https://gefest.ua/objects/ellada/turnid-30/floorid-900/flatid-10357"""
    m = re.search(r"/objects/([^/]+)/", url)
    return m.group(1) if m else ""


def _flat_id_from_url(url: str) -> int | None:
    m = re.search(r"flatid-(\d+)", url)
    return int(m.group(1)) if m else None


def _text(el):
    return el.get_text(strip=True) if el else ""


def parse_search_page(soup: BeautifulSoup) -> list[dict]:
    flats = []
    for item in soup.select(".flat_item_inner"):
        link = item.select_one(".flat_item_image")
        title_link = item.select_one(".flat_item_title a")
        if not link or not title_link:
            continue
        url = link.get("href", "")
        flat_id = _flat_id_from_url(url)
        if flat_id is None:
            continue

        img = item.select_one(".flat_item_image img")
        image_url = img.get("src", "") if img else ""
        if image_url and image_url.startswith("/"):
            image_url = BASE_URL + image_url

        smi = {}
        for row in item.select(".flat_item_smi"):
            spans = row.find_all("span")
            if len(spans) >= 2:
                key = _text(spans[0]).rstrip(":")
                val = _text(spans[1])
                smi[key] = val

        label = item.select_one(".flat_item_label")

        flats.append(
            {
                "id": flat_id,
                "complex_name": _text(title_link),
                "complex_slug": _slug_from_url(url),
                "url": url,
                "rooms": _text(item.select_one(".flat_item_rooms")),
                "section": smi.get("Секція", ""),
                "number": smi.get("Номер", ""),
                "floor": smi.get("Поверх", ""),
                "area": smi.get("Площа", ""),
                "price": smi.get("Вартість", ""),
                "status": _text(label),
                "image_url": image_url,
            }
        )
    return flats


def get_total_pages(soup: BeautifulSoup) -> int:
    pages = [
        int(a.get_text(strip=True))
        for a in soup.select(".pagination .page-link")
        if a.get_text(strip=True).isdigit()
    ]
    return max(pages) if pages else 1


def crawl_flat_list() -> list[dict]:
    """Обходит все страницы общего поиска и возвращает базовую информацию по квартирам."""
    soup = _get(SEARCH_URL)
    if soup is None:
        return []

    all_flats = parse_search_page(soup)
    total_pages = get_total_pages(soup)
    log.info("Найдено страниц поиска: %s", total_pages)

    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_DELAY)
        page_soup = _get(SEARCH_URL, params={"page": page})
        if page_soup is None:
            continue
        all_flats.extend(parse_search_page(page_soup))

    return all_flats


def parse_flat_detail(url: str) -> dict:
    """Дотягивает дополнительную информацию со страницы конкретной квартиры."""
    soup = _get(url)
    extra = {"queue": "", "flat_type": "", "plan_image_url": url.rstrip("/") + "/planimage"}
    if soup is None:
        return extra

    info = {}
    for col in soup.select(".flat_info_col"):
        title = _text(col.select_one(".flat_info_title"))
        val = _text(col.select_one(".flat_info_val"))
        if title:
            info[title] = val

    extra["queue"] = info.get("Черга", "")
    extra["flat_type"] = info.get("Тип квартири", "")
    return extra


def crawl_all(with_details: bool = True) -> list[dict]:
    flats = crawl_flat_list()
    now = datetime.now(timezone.utc).isoformat()

    for flat in flats:
        flat["queue"] = ""
        flat["flat_type"] = ""
        flat["plan_image_url"] = flat["url"].rstrip("/") + "/planimage"
        flat["updated_at"] = now

    if with_details:
        for flat in flats:
            time.sleep(REQUEST_DELAY)
            extra = parse_flat_detail(flat["url"])
            flat.update(extra)

    log.info("Спарсено квартир: %s", len(flats))
    return flats
