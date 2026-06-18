"""
export_static.py — 匯出 Kintone 本地 SQLite 資料至靜態 JSON 檔案供 GitHub Pages 使用
"""
import os
import json
from pathlib import Path
import db
import server

API_DIR = Path(__file__).parent / "api"

def main():
    print("=" * 60)
    print("  匯出 SQLite 快取資料為靜態 JSON 檔案...")
    print("=" * 60)
    
    # 確保 api/ 目錄存在
    API_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. status.json
    print("匯出 status.json...")
    status_data = {
        "sync_logs": db.get_sync_status(),
        "counts": db.get_db_counts()
    }
    with open(API_DIR / "status.json", "w", encoding="utf-8") as f:
        json.dump(status_data, f, ensure_ascii=False, indent=2)
        
    # 2. contacts.json
    print("匯出 contacts.json...")
    contacts = db.search_contacts("", limit=5000)
    contacts_data = {
        "columns": list(server.SCHEMA_71.values()),
        "rows": [server.to_row(r["raw_json"], server.SCHEMA_71) for r in contacts]
    }
    with open(API_DIR / "contacts.json", "w", encoding="utf-8") as f:
        json.dump(contacts_data, f, ensure_ascii=False, indent=2)
        
    # 3. orders.json
    print("匯出 orders.json...")
    orders = db.search_orders("", limit=5000)
    order_rows = []
    for r in orders:
        order_rows.extend(server.orders_to_rows(r["raw_json"]))
    orders_data = {
        "columns": server.SCHEMA_69_COLS,
        "rows": order_rows
    }
    with open(API_DIR / "orders.json", "w", encoding="utf-8") as f:
        json.dump(orders_data, f, ensure_ascii=False, indent=2)
        
    # 4. pos.json
    print("匯出 pos.json...")
    pos = db.search_pos("", limit=20000)
    pos_data = {
        "columns": list(server.SCHEMA_310.values()),
        "rows": [server.to_row(r["raw_json"], server.SCHEMA_310) for r in pos]
    }
    with open(API_DIR / "pos.json", "w", encoding="utf-8") as f:
        json.dump(pos_data, f, ensure_ascii=False, indent=2)
        
    # 5. eit_logs.json
    print("匯出 eit_logs.json...")
    eit_logs = server.read_eit_logs()
    with open(API_DIR / "eit_logs.json", "w", encoding="utf-8") as f:
        json.dump(eit_logs, f, ensure_ascii=False, indent=2)
        
    # 6. tw_opp.json
    print("匯出 tw_opp.json...")
    tw_opp = server.read_tw_opp()
    with open(API_DIR / "tw_opp.json", "w", encoding="utf-8") as f:
        json.dump(tw_opp, f, ensure_ascii=False, indent=2)
        
    print("=" * 60)
    print("  匯出完成！所有 JSON 檔案已儲存於 api/ 目錄。")
    print("=" * 60)

if __name__ == "__main__":
    main()
