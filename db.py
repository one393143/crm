"""
db.py — CRM 本地 SQLite 資料庫模組（全量同步版）

資料表設計：
  sync_log    : 記錄每個 App 最後同步時間
  contacts    : App 71 聯絡人（1,060 筆）
  orders      : App 69 客戶訂購單（743 筆）
  pos_records : App 310 POS 歷史（14,852 筆）
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "crp_cache.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # 讀寫並發更好
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection):
    conn.executescript("""
        -- 同步紀錄
        CREATE TABLE IF NOT EXISTS sync_log (
            app_id      INTEGER PRIMARY KEY,
            app_name    TEXT,
            total_rows  INTEGER,
            synced_at   TEXT
        );

        -- App 71 聯絡人
        CREATE TABLE IF NOT EXISTS contacts (
            kintone_id   INTEGER PRIMARY KEY,
            customer     TEXT,     -- 客戶/供應商名稱
            contact_name TEXT,     -- 聯絡人姓名
            title        TEXT,     -- 職稱
            phone        TEXT,     -- 手機/電話
            email        TEXT,     -- Email
            raw_json     TEXT      -- 原始 record JSON（備用）
        );
        CREATE INDEX IF NOT EXISTS idx_contacts_customer ON contacts(customer);

        -- App 69 客戶訂購單
        CREATE TABLE IF NOT EXISTS orders (
            kintone_id   INTEGER PRIMARY KEY,
            customer     TEXT,     -- 客戶名稱
            order_no     TEXT,     -- 訂購單號
            order_date   TEXT,     -- 訂購日期
            contact      TEXT,     -- 聯絡人
            status       TEXT,     -- 銷貨狀態
            amount_twd   TEXT,     -- 金額合計(TWD)
            raw_json     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer);

        -- App 310 POS 歷史
        CREATE TABLE IF NOT EXISTS pos_records (
            kintone_id   INTEGER PRIMARY KEY,
            customer     TEXT,     -- Customer Name
            po_date      TEXT,     -- PO Date
            shipping_date TEXT,    -- Shipping Date
            product_type TEXT,     -- Product Type
            product_no   TEXT,     -- Product No.
            qty          TEXT,     -- Qty.
            sales_total  TEXT,     -- Sales Total Price (NT$)
            eit_po_no    TEXT,     -- EIT PO No.
            raw_json     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pos_customer ON pos_records(customer);
    """)
    conn.commit()


# ──────────────────────────────────────────────
# 同步寫入 API
# ──────────────────────────────────────────────

def _val(record: dict, code: str, default="") -> str:
    """從 Kintone record dict 取出指定 field code 的值"""
    field = record.get(code, {})
    v = field.get("value")
    if v is None:
        return default
    if isinstance(v, list):
        if v and isinstance(v[0], dict) and "name" in v[0]:
            return ", ".join(item["name"] for item in v)
        return ", ".join(str(i) for i in v)
    if isinstance(v, dict) and "name" in v:
        return v["name"]
    return str(v)


def upsert_contacts(records: list):
    """批次寫入 App 71 聯絡人"""
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO contacts
                (kintone_id, customer, contact_name, title, phone, email, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(kintone_id) DO UPDATE SET
                customer=excluded.customer,
                contact_name=excluded.contact_name,
                title=excluded.title,
                phone=excluded.phone,
                email=excluded.email,
                raw_json=excluded.raw_json
        """, [
            (
                int(_val(r, "$id") or _val(r, "記錄號碼") or 0),
                _val(r, "撱箄疏菜"),           # 客戶/供應商名稱（code 已從實際執行確認）
                _val(r, "聯絡人姓名") or _val(r, "姓名") or _val(r, "聯絡人"),
                _val(r, "聯絡人職稱") or _val(r, "職稱") or _val(r, "憿?") ,
                _val(r, "聯絡人手機") or _val(r, "聯絡人電話") or _val(r, "手機") or _val(r, "電話") or _val(r, "??"),
                _val(r, "聯絡人Email") or _val(r, "Email") or _val(r, "舐窗鈭慟mail"),
                json.dumps(r, ensure_ascii=False),
            )
            for r in records
        ])
        conn.commit()


def upsert_orders(records: list):
    """批次寫入 App 69 訂購單"""
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO orders
                (kintone_id, customer, order_no, order_date, contact, status, amount_twd, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(kintone_id) DO UPDATE SET
                customer=excluded.customer,
                order_no=excluded.order_no,
                order_date=excluded.order_date,
                contact=excluded.contact,
                status=excluded.status,
                amount_twd=excluded.amount_twd,
                raw_json=excluded.raw_json
        """, [
            (
                int(_val(r, "$id") or _val(r, "記錄號碼") or 0),
                _val(r, "客戶名稱"),
                _val(r, "訂購單號"),
                _val(r, "訂購日期"),
                _val(r, "聯絡人"),
                _val(r, "銷貨狀態") or _val(r, "狀態"),
                _val(r, "本幣金額合計") or _val(r, "金額合計"),
                json.dumps(r, ensure_ascii=False),
            )
            for r in records
        ])
        conn.commit()


def upsert_pos(records: list):
    """批次寫入 App 310 POS 歷史"""
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO pos_records
                (kintone_id, customer, po_date, shipping_date,
                 product_type, product_no, qty, sales_total, eit_po_no, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(kintone_id) DO UPDATE SET
                customer=excluded.customer,
                po_date=excluded.po_date,
                shipping_date=excluded.shipping_date,
                product_type=excluded.product_type,
                product_no=excluded.product_no,
                qty=excluded.qty,
                sales_total=excluded.sales_total,
                eit_po_no=excluded.eit_po_no,
                raw_json=excluded.raw_json
        """, [
            (
                int(_val(r, "$id") or _val(r, "記錄號碼") or 0),
                _val(r, "單行文字方塊_2"),    # Customer Name
                _val(r, "日期"),             # PO Date
                _val(r, "Shipping_Date"),   # Shipping Date
                _val(r, "單行文字方塊_8"),    # Product Type
                _val(r, "單行文字方塊_9"),    # Product No.
                _val(r, "Qty_"),            # Qty.
                _val(r, "Sales_Total_Price___NT__"),  # Sales Total (NT$)
                _val(r, "單行文字方塊_4"),    # EIT PO No.
                json.dumps(r, ensure_ascii=False),
            )
            for r in records
        ])
        conn.commit()


def update_sync_log(app_id: int, app_name: str, total_rows: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO sync_log (app_id, app_name, total_rows, synced_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(app_id) DO UPDATE SET
                app_name=excluded.app_name,
                total_rows=excluded.total_rows,
                synced_at=excluded.synced_at
        """, (app_id, app_name, total_rows, _now_iso()))
        conn.commit()


# ──────────────────────────────────────────────
# 查詢 API
# ──────────────────────────────────────────────

def search_contacts(keyword: str, limit: int = 1000) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE customer LIKE ? ORDER BY kintone_id DESC LIMIT ?",
            (f"%{keyword}%", limit)
        ).fetchall()
    return [dict(r) for r in rows]


def search_orders(keyword: str, limit: int = 1000) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM orders WHERE customer LIKE ?
               ORDER BY order_date DESC LIMIT ?""",
            (f"%{keyword}%", limit)
        ).fetchall()
    return [dict(r) for r in rows]


def search_pos(keyword: str, limit: int = 1000) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM pos_records WHERE customer LIKE ?
               ORDER BY po_date DESC LIMIT ?""",
            (f"%{keyword}%", limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_sync_status() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT app_id, app_name, total_rows, synced_at FROM sync_log ORDER BY app_id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_db_counts() -> dict:
    with get_conn() as conn:
        return {
            "contacts":    conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
            "orders":      conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "pos_records": conn.execute("SELECT COUNT(*) FROM pos_records").fetchone()[0],
        }
