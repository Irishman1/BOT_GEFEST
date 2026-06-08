import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS flats (
    id INTEGER PRIMARY KEY,
    complex_name TEXT,
    complex_slug TEXT,
    url TEXT,
    rooms TEXT,
    section TEXT,
    number TEXT,
    floor TEXT,
    queue TEXT,
    flat_type TEXT,
    area TEXT,
    price TEXT,
    status TEXT,
    image_url TEXT,
    plan_image_url TEXT,
    updated_at TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def upsert_flat(flat: dict):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO flats (id, complex_name, complex_slug, url, rooms, section, number,
                               floor, queue, flat_type, area, price, status, image_url,
                               plan_image_url, updated_at)
            VALUES (:id, :complex_name, :complex_slug, :url, :rooms, :section, :number,
                    :floor, :queue, :flat_type, :area, :price, :status, :image_url,
                    :plan_image_url, :updated_at)
            ON CONFLICT(id) DO UPDATE SET
                complex_name=excluded.complex_name,
                complex_slug=excluded.complex_slug,
                url=excluded.url,
                rooms=excluded.rooms,
                section=excluded.section,
                number=excluded.number,
                floor=excluded.floor,
                queue=excluded.queue,
                flat_type=excluded.flat_type,
                area=excluded.area,
                price=excluded.price,
                status=excluded.status,
                image_url=excluded.image_url,
                plan_image_url=excluded.plan_image_url,
                updated_at=excluded.updated_at
            """,
            flat,
        )


def replace_all_flats(flats: list[dict]):
    """Полностью заменяет содержимое таблицы свежими данными парсера."""
    with get_conn() as conn:
        conn.execute("DELETE FROM flats")
        conn.executemany(
            """
            INSERT INTO flats (id, complex_name, complex_slug, url, rooms, section, number,
                               floor, queue, flat_type, area, price, status, image_url,
                               plan_image_url, updated_at)
            VALUES (:id, :complex_name, :complex_slug, :url, :rooms, :section, :number,
                    :floor, :queue, :flat_type, :area, :price, :status, :image_url,
                    :plan_image_url, :updated_at)
            """,
            flats,
        )


def get_complexes():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT complex_name, complex_slug FROM flats ORDER BY complex_name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_flats_by_complex(complex_slug: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM flats WHERE complex_slug = ? ORDER BY price",
            (complex_slug,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_flat(flat_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM flats WHERE id = ?", (flat_id,)).fetchone()
    return dict(row) if row else None


def count_flats():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM flats").fetchone()
    return row["c"]
