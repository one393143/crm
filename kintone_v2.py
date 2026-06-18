"""
kintone_v2.py — 客戶 360 度檢索系統（本地 DB 全量同步版）

使用流程：
  1. 先同步：python kintone_v2.py --sync
             （App 71: ~3次, App 69: ~2次, App 310: ~30次 API，全量寫入本地 DB）
  2. 查詢：  python kintone_v2.py 長榮超音波
             （直接查本地 DB，0 次 API）

指令：
  python kintone_v2.py --sync          全量同步所有 App 到本地 DB
  python kintone_v2.py --sync 310      只同步 App 310
  python kintone_v2.py --status        顯示 DB 同步狀態
  python kintone_v2.py 長榮超音波       查詢客戶（查本地 DB）
"""

import requests
import urllib.parse
import sys
import io
import argparse
from datetime import datetime, timezone

# Windows cp950 終端機 UTF-8 修正
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import db

# ==========================================
# 1. 基本設定
# ==========================================
import os
DOMAIN = os.environ.get("KINTONE_DOMAIN", "effintech.cybozu.com")

APPS = {
    71:  {"token": os.environ.get("KINTONE_TOKEN_71", "NZ0ASFsMqm4av7H79AfmfputTyJmPoRc57D7sdxq"), "name": "聯絡人"},
    69:  {"token": os.environ.get("KINTONE_TOKEN_69", "K8mGvvtNMrBMbl1O3lYC9HCn1gfY7Pb5GRHOt0Hu"), "name": "客戶訂購單"},
    310: {"token": os.environ.get("KINTONE_TOKEN_310", "wfaKjqgiaMuj7nrez48pRISlCUJ3LNWuT81H8Mea"), "name": "POS 歷史"},
}

# ==========================================
# 2. API 抓取函數（含分頁）
# ==========================================

def fetch_all_records(app_id: int) -> list:
    """
    全量抓取指定 App 的所有 Records（游標分頁，無筆數上限）。
    使用 $id > last_id 繞過 Kintone 的 offset 10,000 上限。
    等同於 @kintone/rest-api-client 的 getAllRecords()。
    """
    token = APPS[app_id]["token"]
    headers = {"X-Cybozu-API-Token": token}
    all_records = []
    last_id = 0
    batch_size = 500

    while True:
        # 用 $id > last_id 做游標，避免 offset 超過 10,000 的 400 錯誤
        q = f"$id > {last_id} order by $id asc limit {batch_size}"
        query = urllib.parse.quote(q)
        url = f"https://{DOMAIN}/k/v1/records.json?app={app_id}&query={query}"

        try:
            res = requests.get(url, headers=headers, timeout=30)
            if res.status_code != 200:
                print(f"  [錯誤] App {app_id} last_id={last_id}: HTTP {res.status_code} {res.text[:100]}")
                break
            batch = res.json().get("records", [])
            if not batch:
                break  # 沒有更多資料

            all_records.extend(batch)
            last_id = int(batch[-1].get("$id", {}).get("value", 0))
            print(f"  ... 已取得 {len(all_records)} 筆 (last $id={last_id})", end="\r")

            if len(batch) < batch_size:
                break  # 最後一批

        except Exception as e:
            print(f"  [錯誤] {e}")
            break

    return all_records



# ==========================================
# 3. 同步功能
# ==========================================

def sync_app(app_id: int):
    """同步單一 App 的全量資料到本地 DB"""
    name = APPS[app_id]["name"]
    print(f"\n[同步] App {app_id} ({name})...")

    records = fetch_all_records(app_id)
    count = len(records)
    print(f"  抓取完成：共 {count} 筆                    ")

    if count == 0:
        print("  [警告] 沒有取到資料，跳過寫入")
        return

    print(f"  寫入本地 DB...")
    if app_id == 71:
        _sync_contacts(records)
    elif app_id == 69:
        _sync_orders(records)
    elif app_id == 310:
        _sync_pos(records)

    db.update_sync_log(app_id, name, count)
    print(f"  [完成] {count} 筆已同步")


def _sync_contacts(records: list):
    """App 71 聯絡人 — 解析並寫入 DB"""
    import json

    def val(r, *codes):
        for code in codes:
            field = r.get(code, {})
            v = field.get("value")
            if v is None:
                continue
            if isinstance(v, list):
                if v and isinstance(v[0], dict) and "name" in v[0]:
                    return ", ".join(i["name"] for i in v)
                return ", ".join(str(i) for i in v)
            if isinstance(v, dict) and "name" in v:
                return v["name"]
            s = str(v).strip()
            if s:
                return s
        return ""

    rows = []
    for r in records:
        kid = int(r.get("$id", {}).get("value", 0) or r.get("記錄號碼", {}).get("value", 0))
        rows.append({
            "kintone_id":   kid,
            "customer":     val(r, "客戶_供應商名稱", "客戶名稱"),          # 確認的 field code
            "contact_name": val(r, "客戶_廠商聯絡人姓名", "聯絡人姓名", "姓名"),  # 確認的 field code
            "title":        val(r, "職稱", "聯絡人職稱"),                    # 確認的 field code
            "phone":        val(r, "聯絡人電話", "聯絡人手機", "手機", "電話"), # 確認的 field code
            "email":        val(r, "聯絡人Email", "Email"),
            "raw_json":     json.dumps(r, ensure_ascii=False),
        })

    with db.get_conn() as conn:
        conn.executemany("""
            INSERT INTO contacts
                (kintone_id, customer, contact_name, title, phone, email, raw_json)
            VALUES (:kintone_id, :customer, :contact_name, :title, :phone, :email, :raw_json)
            ON CONFLICT(kintone_id) DO UPDATE SET
                customer=excluded.customer, contact_name=excluded.contact_name,
                title=excluded.title, phone=excluded.phone, email=excluded.email,
                raw_json=excluded.raw_json
        """, rows)
        conn.commit()


def _sync_orders(records: list):
    """App 69 訂購單 — 解析並寫入 DB"""
    import json

    def val(r, *codes):
        for code in codes:
            field = r.get(code, {})
            v = field.get("value")
            if v is None:
                continue
            if isinstance(v, dict) and "name" in v:
                return v["name"]
            s = str(v).strip() if v is not None else ""
            if s:
                return s
        return ""

    rows = []
    for r in records:
        kid = int(r.get("$id", {}).get("value", 0) or r.get("記錄號碼", {}).get("value", 0))
        rows.append({
            "kintone_id":  kid,
            "customer":    val(r, "客戶名稱", "客戶名稱_lookup"),  # App 69 客戶名稱
            "order_no":    val(r, "訂購單號"),
            "order_date":  val(r, "訂購日期"),
            "contact":     val(r, "聯絡人"),
            "status":      val(r, "銷貨狀態", "狀態"),
            "amount_twd":  val(r, "本幣金額合計", "金額合計"),
            "raw_json":    json.dumps(r, ensure_ascii=False),
        })

    with db.get_conn() as conn:
        conn.executemany("""
            INSERT INTO orders
                (kintone_id, customer, order_no, order_date, contact, status, amount_twd, raw_json)
            VALUES (:kintone_id, :customer, :order_no, :order_date, :contact, :status, :amount_twd, :raw_json)
            ON CONFLICT(kintone_id) DO UPDATE SET
                customer=excluded.customer, order_no=excluded.order_no,
                order_date=excluded.order_date, contact=excluded.contact,
                status=excluded.status, amount_twd=excluded.amount_twd,
                raw_json=excluded.raw_json
        """, rows)
        conn.commit()


def _sync_pos(records: list):
    """App 310 POS 歷史 — 解析並寫入 DB（使用確認的 Field Code）"""
    import json

    def val(r, code):
        field = r.get(code, {})
        v = field.get("value")
        if v is None:
            return ""
        return str(v).strip()

    rows = []
    for r in records:
        kid = int(r.get("$id", {}).get("value", 0) or r.get("記錄號碼", {}).get("value", 0))
        rows.append({
            "kintone_id":    kid,
            "customer":      val(r, "單行文字方塊_2"),    # Customer Name
            "po_date":       val(r, "日期"),             # PO Date
            "shipping_date": val(r, "Shipping_Date"),   # Shipping Date
            "product_type":  val(r, "單行文字方塊_8"),    # Product Type
            "product_no":    val(r, "單行文字方塊_9"),    # Product No.
            "qty":           val(r, "Qty_"),            # Qty.
            "sales_total":   val(r, "Sales_Total_Price___NT__"),  # NT$
            "eit_po_no":     val(r, "單行文字方塊_4"),    # EIT PO No.
            "raw_json":      json.dumps(r, ensure_ascii=False),
        })

    with db.get_conn() as conn:
        conn.executemany("""
            INSERT INTO pos_records
                (kintone_id, customer, po_date, shipping_date,
                 product_type, product_no, qty, sales_total, eit_po_no, raw_json)
            VALUES (:kintone_id, :customer, :po_date, :shipping_date,
                    :product_type, :product_no, :qty, :sales_total, :eit_po_no, :raw_json)
            ON CONFLICT(kintone_id) DO UPDATE SET
                customer=excluded.customer, po_date=excluded.po_date,
                shipping_date=excluded.shipping_date, product_type=excluded.product_type,
                product_no=excluded.product_no, qty=excluded.qty,
                sales_total=excluded.sales_total, eit_po_no=excluded.eit_po_no,
                raw_json=excluded.raw_json
        """, rows)
        conn.commit()


def sync_all(app_filter: int | None = None):
    """全量同步（預設全部三個 App）"""
    targets = [app_filter] if app_filter else [71, 69, 310]
    print("\n" + "="*50)
    print("開始全量同步...")
    print("="*50)
    start = datetime.now()
    for app_id in targets:
        sync_app(app_id)
    elapsed = (datetime.now() - start).seconds
    print(f"\n全部同步完成！耗時 {elapsed} 秒")
    show_status()


# ── 各 App 的 Field Code → 中文 Label 對照表 ──────────────
LABELS_71 = {
    "客戶_廠商聯絡人姓名": "聯絡人姓名",
    "客戶_供應商名稱":    "客戶/供應商名稱",
    "客戶_廠商聯絡人代號": "聯絡人代號",
    "廠商代號":          "廠商代號",
    "職稱":             "職稱",
    "聯絡人電話":        "電話",
    "聯絡人地址":        "地址",
    "聯絡人Email":      "Email",
    "類型":             "類型",
}

LABELS_69 = {
    "客戶名稱":     "客戶名稱",
    "訂購單號":     "訂購單號",
    "訂購日期":     "訂購日期",
    "客戶訂單號碼": "客戶PO號碼",
    "客戶需求日":   "客戶需求日",
    "聯絡人":       "聯絡人",
    "銷貨狀態":     "銷貨狀態",
    "帳務歸屬":     "帳務歸屬",
    "業績歸屬":     "業績歸屬",
    "負責業務":     "負責業務",
    "幣別":         "幣別",
    "金額合計":     "訂單金額合計",
    "本幣金額合計": "金額合計(TWD)",
    "數量合計":     "數量合計",
    "耀迅回復交期": "回復交期",
    "收貨地址":     "收貨地址",
    "訂購明細":     "訂購明細",      # SUBTABLE
}

LABELS_310 = {
    "單行文字方塊_2":              "Customer Name",
    "日期":                       "PO Date",
    "Shipping_Date":             "Shipping Date",
    "Payment_Date":              "Payment Date",
    "單行文字方塊_8":              "Product Type",
    "單行文字方塊_9":              "Product No.",
    "單行文字方塊_1":              "Type",
    "Qty_":                      "Qty.",
    "Sales_Total_Price___NT__":  "Sales Total (NT$)",
    "Sales_Unit_Price__NT__":    "Sales Unit Price (NT$)",
    "Cost_Total_Price__NT__":    "Cost Total (NT$)",
    "Cost_Unit_Price___NT__":    "Cost Unit Price (NT$)",
    "單行文字方塊_4":              "EIT PO No.",
    "單行文字方塊_3":              "Customer PO No.",
    "單行文字方塊_6":              "Invoice No.",
    "單行文字方塊_5":              "PI(PL) No.",
    "單行文字方塊":                "No.",
    "單行文字方塊_0":              "Sales",
    "單行文字方塊_16":             "Country",
    "單行文字方塊_18":             "Remark",
    "單行文字方塊_19":             "Margin",
    "單行文字方塊_15":             "Due Date",
    "數值_1":                     "Exchange Rate (NT$:US$)",
}

# 永遠略過的系統欄位
_SKIP_CODES = {
    "$id", "$revision", "記錄號碼", "建立人", "更新人",
    "建立時間", "更新時間", "執行者", "類別", "狀態",
}

# 訂購明細 subtable 內的欄位 label
LABELS_69_DETAIL = {
    "產品名稱":       "產品名稱",
    "產品型號":       "產品型號",
    "產品名稱_lookup": "產品名稱(lookup)",
    "數量":           "數量",
    "未稅單價":       "未稅單價",
    "未稅金額":       "未稅金額",
    "本幣未稅金額":   "本幣未稅金額(TWD)",
    "交期":           "交期",
    "出貨日期":       "出貨日期",
    "備註":           "備註",
}


def _extract_value(v):
    """從 Kintone field value 提取可顯示的字串"""
    if v is None:
        return None
    if isinstance(v, list):
        if not v:
            return None
        if isinstance(v[0], dict) and "name" in v[0]:
            return ", ".join(i["name"] for i in v)
        return ", ".join(str(i) for i in v if str(i).strip())
    if isinstance(v, dict) and "name" in v:
        return v["name"] or None
    s = str(v).strip()
    return s if s else None


def _print_record(raw: dict, label_map: dict, indent: str = "  "):
    """列出一筆 record 所有有值的欄位"""
    for code, field in raw.items():
        if code in _SKIP_CODES:
            continue
        if not isinstance(field, dict):
            continue

        ftype = field.get("type", "")
        label = label_map.get(code, code)   # 有 label 用 label，否則顯示 code

        # SUBTABLE：展開每一列
        if ftype == "SUBTABLE":
            rows = field.get("value", [])
            if not rows:
                continue
            print(f"{indent}[ {label} ]")
            for i, row in enumerate(rows, 1):
                print(f"{indent}  -- 明細 {i} --")
                for sub_code, sub_field in row.get("value", {}).items():
                    sub_label = LABELS_69_DETAIL.get(sub_code, sub_code)
                    sub_val = _extract_value(sub_field.get("value"))
                    if sub_val:
                        print(f"{indent}    {sub_label}: {sub_val}")
            continue

        val = _extract_value(field.get("value"))
        if val:
            print(f"{indent}{label}: {val}")


def fetch_customer_360(keyword: str):
    import json as _json

    counts = db.get_db_counts()
    if all(v == 0 for v in counts.values()):
        print("\n[警告] 本地 DB 尚無資料，請先執行：python kintone_v2.py --sync")
        return

    print(f"\n{'='*60}")
    print(f"  查詢關鍵字：【{keyword}】")
    print("="*60)

    # ── 1. 聯絡人 (App 71) ───────────────────────────────────
    contacts = db.search_contacts(keyword, limit=500)
    print(f"\n[聯絡人]  共 {len(contacts)} 筆")
    print("-"*60)
    if contacts:
        for c in contacts:
            rec = _json.loads(c["raw_json"])
            print(f"  (ID: {c['kintone_id']})")
            _print_record(rec, LABELS_71)
            print()
    else:
        print("  查無聯絡人紀錄")

    # ── 2. 訂購單 (App 69) ───────────────────────────────────
    orders = db.search_orders(keyword, limit=500)
    print(f"\n[訂購單]  共 {len(orders)} 筆")
    print("-"*60)
    if orders:
        for o in orders:
            rec = _json.loads(o["raw_json"])
            print(f"  (ID: {o['kintone_id']})")
            _print_record(rec, LABELS_69)
            print()
    else:
        print("  查無訂購單")

    # ── 3. POS 歷史 (App 310) ────────────────────────────────
    pos = db.search_pos(keyword, limit=500)
    print(f"\n[POS 交易]  共 {len(pos)} 筆")
    print("-"*60)
    if pos:
        for p in pos:
            rec = _json.loads(p["raw_json"])
            print(f"  (ID: {p['kintone_id']})")
            _print_record(rec, LABELS_310)
            print()
    else:
        print("  查無 POS 紀錄")

    print("="*60)
    print("查詢完畢！")
    print("="*60 + "\n")


def show_status():
    """顯示 DB 同步狀態"""
    print("\n[本地 DB 狀態]")
    print("="*50)

    counts = db.get_db_counts()
    logs = {s["app_id"]: s for s in db.get_sync_status()}

    for app_id, info in APPS.items():
        log = logs.get(app_id)
        table_map = {71: "contacts", 69: "orders", 310: "pos_records"}
        local_count = counts.get(table_map[app_id], 0)
        if log:
            dt = datetime.fromisoformat(log["synced_at"]).astimezone()
            synced_str = dt.strftime("%Y-%m-%d %H:%M")
            print(f"  App {app_id} ({info['name']:12s}) : {local_count:6,d} 筆  (上次同步: {synced_str})")
        else:
            print(f"  App {app_id} ({info['name']:12s}) : {local_count:6,d} 筆  [尚未同步]")
    print("="*50 + "\n")


# ==========================================
# 5. 執行入口
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="客戶 360 度戰情報告（本地 DB 版）")
    parser.add_argument("customer", nargs="?", help="客戶名稱關鍵字")
    parser.add_argument("--sync",   nargs="?", const="all", metavar="APP_ID",
                        help="全量同步（--sync 全部；--sync 310 只同步 App 310）")
    parser.add_argument("--status", action="store_true", help="顯示 DB 狀態")
    args = parser.parse_args()

    if args.sync:
        app_filter = None
        if args.sync != "all":
            try:
                app_filter = int(args.sync)
            except ValueError:
                print(f"無效的 App ID: {args.sync}")
                sys.exit(1)
        sync_all(app_filter)

    elif args.status:
        show_status()

    elif args.customer:
        fetch_customer_360(args.customer.strip())

    else:
        try:
            keyword = input("請輸入要查詢的客戶名稱: ").strip()
            if keyword:
                fetch_customer_360(keyword)
            else:
                print("未輸入關鍵字。")
        except KeyboardInterrupt:
            print("\n已取消。")

    if not args.sync and not args.status:
        input("\n請按 Enter 鍵結束程式...")
