import logging
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    LinkPreviewOptions,
    Message,
)

import database as db
from config import CONTACT_PHONE, CONTACT_TELEGRAM, FLATS_PER_PAGE

log = logging.getLogger(__name__)

router = Router()

CAT_RESIDENTIAL = "res"
CAT_OFFICE = "office"

CAT_TITLES = {
    CAT_RESIDENTIAL: "🏠 Квартири",
    CAT_OFFICE: "🏢 Офіси та комерційні приміщення",
}

CB_CATEGORY = "cat"     # cat:<res|office>
CB_COMPLEX = "cx"       # cx:<slug>:<cat>
CB_LIST = "ls"          # ls:<slug>:<page>:<cat>
CB_FLAT = "fl"          # fl:<id>:<slug>:<page>:<cat>
CB_BACK_CATEGORIES = "back_cat"
CB_BACK_COMPLEXES = "back_cx"  # back_cx:<cat>
CB_SHOW_PHONE = "phone"
CB_CX_ROOM = "cxr"    # cxr:<slug>:<cat>          — вибір типу кімнат
CB_CX_ROOM_SEL = "cxrs"  # cxrs:<slug>:<cat>:<room>  — обраний тип

# --- Підбір варіанту за параметрами (майстер з питань) ---
CB_WIZ_START = "wiz_start"
CB_WIZ_ROOM = "wizr"        # wizr:<room_code>
CB_WIZ_BUDGET = "wizb"      # wizb:<room_code>:<budget_code>
CB_WIZ_AREA = "wiza"        # wiza:<room_code>:<budget_code>:<area_code>
CB_WIZ_RESULTS = "wizres"   # wizres:<room_code>:<budget_code>:<area_code>:<page>
CB_WIZ_FLAT = "wizfl"       # wizfl:<id>:<room_code>:<budget_code>:<area_code>:<page>

WIZ_ROOM_OPTIONS = [
    ("any", "Будь-який тип", None),
    ("studio", "Студія", "Студія"),
    ("1k", "1-кімнатна", "1-кімнатна"),
    ("2k", "2-кімнатна", "2-кімнатна"),
    ("3k", "3-кімнатна", "3-кімнатна"),
    ("office", "Офіс", "Офіс"),
]

WIZ_BUDGET_OPTIONS = [
    ("any", "Будь-який бюджет", None, None),
    ("b1", "до $50 000", None, 50_000),
    ("b2", "$50 000 – $80 000", 50_000, 80_000),
    ("b3", "$80 000 – $120 000", 80_000, 120_000),
    ("b4", "понад $120 000", 120_000, None),
]

WIZ_AREA_OPTIONS = [
    ("any", "Будь-яка площа", None, None),
    ("a1", "до 35 м²", None, 35),
    ("a2", "35–55 м²", 35, 55),
    ("a3", "55–80 м²", 55, 80),
    ("a4", "понад 80 м²", 80, None),
]

WIZ_ROOM_LABELS = {code: label for code, label, _ in WIZ_ROOM_OPTIONS}
WIZ_BUDGET_LABELS = {code: label for code, label, _, _ in WIZ_BUDGET_OPTIONS}
WIZ_AREA_LABELS = {code: label for code, label, _, _ in WIZ_AREA_OPTIONS}


def parse_price(price_str: str):
    digits = re.sub(r"[^\d]", "", price_str or "")
    return int(digits) if digits else None


def parse_area(area_str: str):
    m = re.search(r"([\d]+(?:[.,]\d+)?)", area_str or "")
    return float(m.group(1).replace(",", ".")) if m else None


def wiz_filter_flats(room_code: str, budget_code: str, area_code: str) -> list[dict]:
    room_value = dict((c, v) for c, _, v in WIZ_ROOM_OPTIONS)[room_code]
    _, _, budget_min, budget_max = next(o for o in WIZ_BUDGET_OPTIONS if o[0] == budget_code)
    _, _, area_min, area_max = next(o for o in WIZ_AREA_OPTIONS if o[0] == area_code)

    result = []
    for c in db.get_complexes():
        for flat in db.get_flats_by_complex(c["complex_slug"]):
            if room_value is not None:
                flat_type = (flat.get("flat_type") or flat.get("rooms") or "").strip()
                if flat_type != room_value:
                    continue

            if budget_min is not None or budget_max is not None:
                price = parse_price(flat.get("price", ""))
                if price is None:
                    continue
                if budget_min is not None and price < budget_min:
                    continue
                if budget_max is not None and price >= budget_max:
                    continue

            if area_min is not None or area_max is not None:
                area = parse_area(flat.get("area", ""))
                if area is None:
                    continue
                if area_min is not None and area < area_min:
                    continue
                if area_max is not None and area >= area_max:
                    continue

            result.append(flat)

    result.sort(key=lambda f: parse_price(f.get("price", "")) or 0)
    return result


def wiz_room_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f"{CB_WIZ_ROOM}:{code}")] for code, label, _ in WIZ_ROOM_OPTIONS]
    rows.append([InlineKeyboardButton(text="‹ На головну", callback_data=CB_BACK_CATEGORIES)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wiz_budget_keyboard(room_code: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"{CB_WIZ_BUDGET}:{room_code}:{code}")]
        for code, label, _, _ in WIZ_BUDGET_OPTIONS
    ]
    rows.append([InlineKeyboardButton(text="‹ Назад", callback_data=CB_WIZ_START)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wiz_area_keyboard(room_code: str, budget_code: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"{CB_WIZ_AREA}:{room_code}:{budget_code}:{code}")]
        for code, label, _, _ in WIZ_AREA_OPTIONS
    ]
    rows.append([InlineKeyboardButton(text="‹ Назад", callback_data=f"{CB_WIZ_ROOM}:{room_code}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wiz_flat_preview_keyboard(flat_id: int, room_code: str, budget_code: str, area_code: str, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Детальніше",
            callback_data=f"{CB_WIZ_FLAT}:{flat_id}:{room_code}:{budget_code}:{area_code}:{page}",
        )]
    ])


def wiz_results_nav_keyboard(room_code: str, budget_code: str, area_code: str, page: int, total: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="« Назад",
            callback_data=f"{CB_WIZ_RESULTS}:{room_code}:{budget_code}:{area_code}:{page - 1}",
        ))
    if (page + 1) * FLATS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(
            text="Далі »",
            callback_data=f"{CB_WIZ_RESULTS}:{room_code}:{budget_code}:{area_code}:{page + 1}",
        ))

    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Новий пошук", callback_data=CB_WIZ_START)])
    rows.append([InlineKeyboardButton(text="‹ На головну", callback_data=CB_BACK_CATEGORIES)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wiz_flat_detail_keyboard(room_code: str, budget_code: str, area_code: str, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Написати в Telegram", url=f"https://t.me/{CONTACT_TELEGRAM.lstrip('@')}"),
                InlineKeyboardButton(text="📞 Подзвонити", callback_data=CB_SHOW_PHONE),
            ],
            [InlineKeyboardButton(
                text="‹ До результатів підбору",
                callback_data=f"{CB_WIZ_RESULTS}:{room_code}:{budget_code}:{area_code}:{page}",
            )],
        ]
    )


def flat_category(flat: dict) -> str:
    flat_type = (flat.get("flat_type") or flat.get("rooms") or "").strip()
    if flat_type == "Офіс" or "Офіс" in flat_type:
        return CAT_OFFICE
    return CAT_RESIDENTIAL


def flats_in_category(slug: str, category: str) -> list[dict]:
    return [f for f in db.get_flats_by_complex(slug) if flat_category(f) == category]


def total_counts() -> dict:
    counts = {CAT_RESIDENTIAL: 0, CAT_OFFICE: 0}
    for c in db.get_complexes():
        for f in db.get_flats_by_complex(c["complex_slug"]):
            counts[flat_category(f)] += 1
    return counts


def complexes_header(category: str) -> str:
    counts = total_counts()
    return (
        f"<b>{CAT_TITLES.get(category, '')}</b>\n"
        f"Усього в каталозі: 🏠 квартир — {counts[CAT_RESIDENTIAL]}, "
        f"🏢 офісів — {counts[CAT_OFFICE]}\n\n"
        f"Оберіть об'єкт:"
    )


def categories_keyboard() -> InlineKeyboardMarkup:
    counts = total_counts()

    rows = []
    for cat in (CAT_RESIDENTIAL, CAT_OFFICE):
        if counts[cat]:
            rows.append([InlineKeyboardButton(
                text=f"{CAT_TITLES[cat]} ({counts[cat]})",
                callback_data=f"{CB_CATEGORY}:{cat}",
            )])
    rows.append([InlineKeyboardButton(text="🔍 Підібрати варіант за параметрами", callback_data=CB_WIZ_START)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def complexes_keyboard(category: str) -> InlineKeyboardMarkup:
    rows = []
    for c in db.get_complexes():
        matching = flats_in_category(c["complex_slug"], category)
        if matching:
            rows.append([InlineKeyboardButton(
                text=f"{c['complex_name']} ({len(matching)})",
                callback_data=f"{CB_COMPLEX}:{c['complex_slug']}:{category}",
            )])
    rows.append([InlineKeyboardButton(text="‹ Назад", callback_data=CB_BACK_CATEGORIES)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def complex_rooms_keyboard(slug: str, category: str) -> InlineKeyboardMarkup:
    flats = flats_in_category(slug, category)
    seen: dict[str, str] = {}
    for f in flats:
        t = (f.get("flat_type") or f.get("rooms") or "").strip()
        if t and t not in seen:
            seen[t] = t
    rows = []
    if len(seen) > 1:
        rows.append([InlineKeyboardButton(
            text=f"Всі варіанти ({len(flats)})",
            callback_data=f"{CB_CX_ROOM_SEL}:{slug}:{category}:any",
        )])
    for t in seen:
        count = sum(1 for f in flats if (f.get("flat_type") or f.get("rooms") or "").strip() == t)
        rows.append([InlineKeyboardButton(
            text=f"{t} ({count})",
            callback_data=f"{CB_CX_ROOM_SEL}:{slug}:{category}:{t}",
        )])
    rows.append([InlineKeyboardButton(text="‹ До списку об'єктів", callback_data=f"{CB_BACK_COMPLEXES}:{category}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def flat_preview_keyboard(flat_id: int, slug: str, page: int, category: str, room: str = "any") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Детальніше", callback_data=f"{CB_FLAT}:{flat_id}:{slug}:{page}:{category}:{room}")]
    ])


def flats_nav_keyboard(slug: str, page: int, category: str, total: int, room: str = "any") -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="« Назад", callback_data=f"{CB_LIST}:{slug}:{page - 1}:{category}:{room}"))
    if (page + 1) * FLATS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="Далі »", callback_data=f"{CB_LIST}:{slug}:{page + 1}:{category}:{room}"))

    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="‹ Змінити тип", callback_data=f"{CB_CX_ROOM}:{slug}:{category}")])
    rows.append([InlineKeyboardButton(text="‹ До списку об'єктів", callback_data=f"{CB_BACK_COMPLEXES}:{category}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def flat_detail_keyboard(slug: str, page: int, category: str, room: str = "any") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Написати в Telegram", url=f"https://t.me/{CONTACT_TELEGRAM.lstrip('@')}"),
                InlineKeyboardButton(text="📞 Подзвонити", callback_data=CB_SHOW_PHONE),
            ],
            [InlineKeyboardButton(text="‹ До списку квартир", callback_data=f"{CB_LIST}:{slug}:{page}:{category}:{room}")],
        ]
    )


def flat_preview_caption(flat: dict) -> str:
    lines = [
        f"<b>{flat['complex_name']}</b>",
        f"№{flat['number']} · {flat.get('flat_type') or flat['rooms']}",
        f"Поверх: {flat['floor']} · Площа: {flat['area']}",
        f"Вартість: {flat['price']}",
        f"Статус: {flat['status']}",
    ]
    return "\n".join(lines)


def flat_caption(flat: dict) -> str:
    lines = [f"<b>{flat['complex_name']}</b>"]
    if flat.get("queue"):
        lines.append(f"Черга: {flat['queue']}")
    if flat.get("section") and flat["section"] != ".":
        lines.append(f"Секція: {flat['section']}")
    lines.append(f"№ {flat['number']}")
    lines.append(f"Поверх: {flat['floor']}")
    if flat.get("flat_type"):
        lines.append(f"Тип: {flat['flat_type']}")
    elif flat.get("rooms"):
        lines.append(f"Тип: {flat['rooms']}")
    lines.append(f"Площа: {flat['area']}")
    lines.append(f"Вартість: {flat['price']}")
    lines.append(f"Статус: {flat['status']}")
    lines.append("")
    lines.append(f"🔗 <a href=\"{flat['url']}\">Сторінка на сайті</a>")
    lines.append("")
    lines.append(f"Зацікавились? Зв'яжіться з нами:\n📱 Telegram: {CONTACT_TELEGRAM}\n☎️ Телефон: {CONTACT_PHONE}")
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message):
    if db.count_flats() == 0:
        await message.answer("Дані ще завантажуються, спробуйте, будь ласка, за хвилину 🙏")
        return

    complexes = db.get_complexes()
    total_objects = len(complexes)
    total_flats = db.count_flats()

    await message.answer(
        "👋 Вітаю! Це бот будівельної компанії «Гефест».\n\n"
        "Тут можна переглянути актуальні квартири та офіси у наших об'єктах: "
        "фото, планування, поверх, площа та вартість.\n\n"
        f"Зараз у каталозі {total_objects} об'єктів та {total_flats} приміщень у продажу.\n\n"
        "Оберіть категорію:",
        reply_markup=categories_keyboard(),
    )


@router.callback_query(F.data == CB_SHOW_PHONE)
async def show_phone(call: CallbackQuery):
    await call.answer(f"☎️ {CONTACT_PHONE}\n\nНаберіть цей номер, щоб зв'язатись з менеджером", show_alert=True)


@router.callback_query(F.data == CB_BACK_CATEGORIES)
async def back_to_categories(call: CallbackQuery):
    await call.message.edit_text("Оберіть категорію:", reply_markup=categories_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_CATEGORY}:"))
async def show_category(call: CallbackQuery):
    _, category = call.data.split(":", 1)
    await call.message.edit_text(
        complexes_header(category),
        reply_markup=complexes_keyboard(category),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_BACK_COMPLEXES}:"))
async def back_to_complexes(call: CallbackQuery):
    _, category = call.data.split(":", 1)
    await call.message.edit_text(
        complexes_header(category),
        reply_markup=complexes_keyboard(category),
    )
    await call.answer()


async def send_flats_page(message: Message, slug: str, page: int, category: str, room: str = "any", edit: bool = False):
    all_flats = flats_in_category(slug, category)
    flats = all_flats if room == "any" else [
        f for f in all_flats
        if (f.get("flat_type") or f.get("rooms") or "").strip() == room
    ]

    if not flats:
        await message.answer("На жаль, за цим типом зараз немає вільних приміщень")
        return

    name = flats[0]["complex_name"]
    room_label = "" if room == "any" else f" · {room}"
    start = page * FLATS_PER_PAGE
    chunk = flats[start:start + FLATS_PER_PAGE]

    header = f"<b>{name}{room_label}</b>\nЗнайдено приміщень: {len(flats)}\n\nОберіть один з варіантів нижче 👇"
    if edit:
        try:
            await message.edit_text(header)
        except Exception:
            await message.answer(header)
    else:
        await message.answer(header)

    for flat in chunk:
        caption = flat_preview_caption(flat)
        keyboard = flat_preview_keyboard(flat["id"], slug, page, category, room)
        if flat.get("image_url"):
            try:
                await message.answer_photo(photo=flat["image_url"], caption=caption, reply_markup=keyboard)
                continue
            except Exception as e:
                log.warning("Не вдалось надіслати фото квартири %s: %s", flat["id"], e)
        await message.answer(caption, reply_markup=keyboard)

    await message.answer(
        "Гортайте список або поверніться назад:",
        reply_markup=flats_nav_keyboard(slug, page, category, len(flats), room),
    )


@router.callback_query(F.data.startswith(f"{CB_COMPLEX}:"))
async def show_complex(call: CallbackQuery):
    _, slug, category = call.data.split(":")
    flats = flats_in_category(slug, category)
    if not flats:
        await call.answer("На жаль, у цьому об'єкті немає вільних приміщень", show_alert=True)
        return
    name = flats[0]["complex_name"]
    await call.message.edit_text(
        f"<b>{name}</b>\nЗнайдено приміщень: {len(flats)}\n\nОберіть тип приміщення:",
        reply_markup=complex_rooms_keyboard(slug, category),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_CX_ROOM}:"))
async def show_complex_room_filter(call: CallbackQuery):
    _, slug, category = call.data.split(":")
    flats = flats_in_category(slug, category)
    name = flats[0]["complex_name"] if flats else ""
    await call.message.edit_text(
        f"<b>{name}</b>\n\nОберіть тип приміщення:",
        reply_markup=complex_rooms_keyboard(slug, category),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_CX_ROOM_SEL}:"))
async def show_complex_room_selected(call: CallbackQuery):
    parts = call.data.split(":")
    _, slug, category, room = parts[0], parts[1], parts[2], parts[3]
    await call.bot.send_chat_action(call.message.chat.id, "upload_photo")
    await send_flats_page(call.message, slug, 0, category, room, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_LIST}:"))
async def show_flats_page(call: CallbackQuery):
    parts = call.data.split(":")
    slug, page, category = parts[1], parts[2], parts[3]
    room = parts[4] if len(parts) > 4 else "any"
    await call.bot.send_chat_action(call.message.chat.id, "upload_photo")
    await send_flats_page(call.message, slug, int(page), category, room, edit=False)
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_FLAT}:"))
async def show_flat_detail(call: CallbackQuery):
    parts = call.data.split(":")
    flat_id, slug, page, category = parts[1], parts[2], parts[3], parts[4]
    room = parts[5] if len(parts) > 5 else "any"
    flat = db.get_flat(int(flat_id))
    if not flat:
        await call.answer("Цю квартиру вже знято з продажу", show_alert=True)
        return

    caption = flat_caption(flat)
    keyboard = flat_detail_keyboard(slug, int(page), category, room)

    photos = []
    if flat.get("image_url"):
        photos.append(InputMediaPhoto(media=flat["image_url"]))
    if flat.get("plan_image_url"):
        photos.append(InputMediaPhoto(media=flat["plan_image_url"]))

    await call.bot.send_chat_action(call.message.chat.id, "upload_photo")
    if photos:
        try:
            await call.message.answer_media_group(media=photos)
        except Exception as e:
            log.warning("Не вдалось надіслати медіа для квартири %s: %s", flat_id, e)

    await call.message.answer(
        caption,
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )

    await call.answer()


@router.callback_query(F.data == CB_WIZ_START)
async def wiz_start(call: CallbackQuery):
    await call.message.edit_text(
        "🔍 <b>Підбір варіанту</b>\n\nДопоможу швидко знайти підходящі квартири чи офіси.\n\n"
        "Крок 1 з 3. Який тип приміщення вас цікавить?",
        reply_markup=wiz_room_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_WIZ_ROOM}:"))
async def wiz_choose_room(call: CallbackQuery):
    _, room_code = call.data.split(":", 1)
    await call.message.edit_text(
        f"🔍 <b>Підбір варіанту</b>\nТип: {WIZ_ROOM_LABELS.get(room_code)}\n\n"
        "Крок 2 з 3. Який бюджет вам підходить?",
        reply_markup=wiz_budget_keyboard(room_code),
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_WIZ_BUDGET}:"))
async def wiz_choose_budget(call: CallbackQuery):
    _, room_code, budget_code = call.data.split(":")
    await call.message.edit_text(
        f"🔍 <b>Підбір варіанту</b>\n"
        f"Тип: {WIZ_ROOM_LABELS.get(room_code)} · Бюджет: {WIZ_BUDGET_LABELS.get(budget_code)}\n\n"
        "Крок 3 з 3. Яка площа вам підходить?",
        reply_markup=wiz_area_keyboard(room_code, budget_code),
    )
    await call.answer()


async def send_wiz_results(message: Message, room_code: str, budget_code: str, area_code: str, page: int, edit: bool = False):
    flats = wiz_filter_flats(room_code, budget_code, area_code)

    summary = (
        f"🔍 <b>Результати підбору</b>\n"
        f"Тип: {WIZ_ROOM_LABELS.get(room_code)} · "
        f"Бюджет: {WIZ_BUDGET_LABELS.get(budget_code)} · "
        f"Площа: {WIZ_AREA_LABELS.get(area_code)}\n"
    )

    if not flats:
        text = summary + "\nНа жаль, за такими параметрами зараз нічого не знайдено 😔\nСпробуйте змінити критерії пошуку."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Новий пошук", callback_data=CB_WIZ_START)],
            [InlineKeyboardButton(text="‹ На головну", callback_data=CB_BACK_CATEGORIES)],
        ])
        if edit:
            try:
                await message.edit_text(text, reply_markup=keyboard)
                return
            except Exception:
                pass
        await message.answer(text, reply_markup=keyboard)
        return

    start = page * FLATS_PER_PAGE
    chunk = flats[start:start + FLATS_PER_PAGE]

    header = summary + f"\nЗнайдено варіантів: {len(flats)}\n\nОберіть один з варіантів нижче 👇"
    if edit:
        try:
            await message.edit_text(header)
        except Exception:
            await message.answer(header)
    else:
        await message.answer(header)

    for flat in chunk:
        caption = flat_preview_caption(flat)
        keyboard = wiz_flat_preview_keyboard(flat["id"], room_code, budget_code, area_code, page)
        if flat.get("image_url"):
            try:
                await message.answer_photo(photo=flat["image_url"], caption=caption, reply_markup=keyboard)
                continue
            except Exception as e:
                log.warning("Не вдалось надіслати фото квартири %s: %s", flat["id"], e)
        await message.answer(caption, reply_markup=keyboard)

    await message.answer(
        "Гортайте список або почніть новий пошук:",
        reply_markup=wiz_results_nav_keyboard(room_code, budget_code, area_code, page, len(flats)),
    )


@router.callback_query(F.data.startswith(f"{CB_WIZ_AREA}:"))
async def wiz_choose_area(call: CallbackQuery):
    _, room_code, budget_code, area_code = call.data.split(":")
    await call.bot.send_chat_action(call.message.chat.id, "upload_photo")
    await send_wiz_results(call.message, room_code, budget_code, area_code, 0, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_WIZ_RESULTS}:"))
async def wiz_results_page(call: CallbackQuery):
    _, room_code, budget_code, area_code, page = call.data.split(":")
    await call.bot.send_chat_action(call.message.chat.id, "upload_photo")
    await send_wiz_results(call.message, room_code, budget_code, area_code, int(page), edit=False)
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_WIZ_FLAT}:"))
async def wiz_show_flat_detail(call: CallbackQuery):
    _, flat_id, room_code, budget_code, area_code, page = call.data.split(":")
    flat = db.get_flat(int(flat_id))
    if not flat:
        await call.answer("Цей варіант вже знято з продажу", show_alert=True)
        return

    caption = flat_caption(flat)
    keyboard = wiz_flat_detail_keyboard(room_code, budget_code, area_code, int(page))

    photos = []
    if flat.get("image_url"):
        photos.append(InputMediaPhoto(media=flat["image_url"]))
    if flat.get("plan_image_url"):
        photos.append(InputMediaPhoto(media=flat["plan_image_url"]))

    await call.bot.send_chat_action(call.message.chat.id, "upload_photo")
    if photos:
        try:
            await call.message.answer_media_group(media=photos)
        except Exception as e:
            log.warning("Не вдалось надіслати медіа для варіанту %s: %s", flat_id, e)

    await call.message.answer(
        caption,
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await call.answer()


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
