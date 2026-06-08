import logging

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


def flat_preview_keyboard(flat_id: int, slug: str, page: int, category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Детальніше", callback_data=f"{CB_FLAT}:{flat_id}:{slug}:{page}:{category}")]
    ])


def flats_nav_keyboard(slug: str, page: int, category: str, total: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="« Назад", callback_data=f"{CB_LIST}:{slug}:{page - 1}:{category}"))
    if (page + 1) * FLATS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="Далі »", callback_data=f"{CB_LIST}:{slug}:{page + 1}:{category}"))

    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="‹ До списку об'єктів", callback_data=f"{CB_BACK_COMPLEXES}:{category}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def flat_detail_keyboard(slug: str, page: int, category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Написати в Telegram", url=f"https://t.me/{CONTACT_TELEGRAM.lstrip('@')}"),
                InlineKeyboardButton(text="📞 Подзвонити", callback_data=CB_SHOW_PHONE),
            ],
            [InlineKeyboardButton(text="‹ До списку квартир", callback_data=f"{CB_LIST}:{slug}:{page}:{category}")],
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


async def send_flats_page(message: Message, slug: str, page: int, category: str, edit: bool = False):
    flats = flats_in_category(slug, category)
    if not flats:
        await message.answer("На жаль, у цьому об'єкті зараз немає вільних приміщень цього типу")
        return

    name = flats[0]["complex_name"]
    start = page * FLATS_PER_PAGE
    chunk = flats[start:start + FLATS_PER_PAGE]

    header = f"<b>{name}</b>\nЗнайдено приміщень: {len(flats)}\n\nОберіть один з варіантів нижче 👇"
    if edit:
        try:
            await message.edit_text(header)
        except Exception:
            await message.answer(header)
    else:
        await message.answer(header)

    for flat in chunk:
        caption = flat_preview_caption(flat)
        keyboard = flat_preview_keyboard(flat["id"], slug, page, category)
        if flat.get("image_url"):
            try:
                await message.answer_photo(photo=flat["image_url"], caption=caption, reply_markup=keyboard)
                continue
            except Exception as e:
                log.warning("Не вдалось надіслати фото квартири %s: %s", flat["id"], e)
        await message.answer(caption, reply_markup=keyboard)

    await message.answer(
        "Гортайте список або поверніться назад:",
        reply_markup=flats_nav_keyboard(slug, page, category, len(flats)),
    )


@router.callback_query(F.data.startswith(f"{CB_COMPLEX}:"))
async def show_complex(call: CallbackQuery):
    _, slug, category = call.data.split(":")
    await call.bot.send_chat_action(call.message.chat.id, "upload_photo")
    await send_flats_page(call.message, slug, 0, category, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_LIST}:"))
async def show_flats_page(call: CallbackQuery):
    _, slug, page, category = call.data.split(":")
    await call.bot.send_chat_action(call.message.chat.id, "upload_photo")
    await send_flats_page(call.message, slug, int(page), category, edit=False)
    await call.answer()


@router.callback_query(F.data.startswith(f"{CB_FLAT}:"))
async def show_flat_detail(call: CallbackQuery):
    _, flat_id, slug, page, category = call.data.split(":")
    flat = db.get_flat(int(flat_id))
    if not flat:
        await call.answer("Цю квартиру вже знято з продажу", show_alert=True)
        return

    caption = flat_caption(flat)
    keyboard = flat_detail_keyboard(slug, int(page), category)

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


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
