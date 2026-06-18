import requests
import urllib.parse
import json

# ==========================================
# 1. 基本設定區
# ==========================================
DOMAIN = "effintech.cybozu.com"

# 填入您提供的專屬 API Token
TOKENS = {
    "69": "K8mGvvtNMrBMbl1O3lYC9HCn1gfY7Pb5GRHOt0Hu",  # 客戶訂購單 (App 69)
    "71": "NZ0ASFsMqm4av7H79AfmfputTyJmPoRc57D7sdxq",  # 聯絡人 (App 71)
    "310": "wfaKjqgiaMuj7nrez48pRISlCUJ3LNWuT81H8Mea", # POS歷史紀錄 (App 310)
    "67": "",  # 客戶基本資料 (尚未設定)
    "96": ""   # 活動履歷 (尚未設定)
}

# ==========================================
# 2. 核心檢索與智慧抓取函數
# ==========================================
def get_field_code_by_label(app_id, target_labels):
    """【終極殺招】動態取得真實欄位代碼，徹底消滅 400 找不到欄位錯誤。
       先問 Kintone 表單結構，找出 Label 對應的真實 Field Code。
    """
    token = TOKENS.get(str(app_id))
    if not token: return None
    
    url = f"https://{DOMAIN}/k/v1/app/form/fields.json?app={app_id}"
    headers = {"X-Cybozu-API-Token": token}
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            fields = res.json().get("properties", {})
            
            # 1. 優先精準比對 Label (例如 "Customer Name")
            for code, info in fields.items():
                if info.get("label") in target_labels:
                    return code
                    
            # 2. 模糊比對 Label (忽略大小寫、空格與斜線)
            for code, info in fields.items():
                label_clean = info.get("label", "").replace(" ", "").replace("/", "").lower()
                for t in target_labels:
                    t_clean = t.replace(" ", "").replace("/", "").lower()
                    if t_clean in label_clean:
                        return code
        return None
    except:
        return None

def get_kintone_data(app_id, query_string):
    """發送 API 請求到指定的 Kintone App"""
    token = TOKENS.get(str(app_id))
    if not token:
        return {"error": f"App {app_id} 尚未設定 API Token，跳過查詢。"}
        
    encoded_query = urllib.parse.quote(query_string)
    url = f"https://{DOMAIN}/k/v1/records.json?app={app_id}&query={encoded_query}"
    
    headers = {"X-Cybozu-API-Token": token}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("records", [])
        else:
            return {"error": f"API 請求失敗: {response.status_code} - {response.text}"}
    except Exception as e:
        return {"error": str(e)}

def fuzzy_get(record, possible_keys, default="未知"):
    """智慧欄位抓取：自動忽略大小寫、底線、空格進行比對回傳值"""
    def extract_val(v):
        if not v: return default
        if isinstance(v, list):
            # 處理 Kintone 特殊欄位 (如使用者選擇、複選框)
            if len(v) > 0 and isinstance(v[0], dict) and "name" in v[0]:
                return ", ".join([item["name"] for item in v])
            return ", ".join([str(item) for item in v])
        return str(v)

    for pk in possible_keys:
        if pk in record:
            val = record[pk].get("value")
            if val not in [None, ""]: return extract_val(val)
            
    for key, data in record.items():
        normalized_key = key.lower().replace("_", "").replace(" ", "")
        for pk in possible_keys:
            normalized_pk = pk.lower().replace("_", "").replace(" ", "")
            if normalized_pk in normalized_key:
                val = data.get("value")
                if val not in [None, ""]: return extract_val(val)
                
    return default

# ==========================================
# 3. 業務戰情報告組合器
# ==========================================
def fetch_customer_360(customer_name):
    print(f"\n" + "="*50)
    print(f"🚀 正在為您彙整【{customer_name}】的戰情報告...")
    print("="*50 + "\n")

    # --- A. 查詢基本資料 (App 67) ---
    print("🏢 [1/5] 取得客戶基本資料...")
    fc_67 = get_field_code_by_label(67, ["客戶名稱", "公司名稱", "Customer Name"]) or "客戶名稱"
    q_67 = f'{fc_67} like "{customer_name}" order by $id desc limit 1'
    master_records = get_kintone_data(67, q_67)
    
    if isinstance(master_records, list) and master_records:
        rec = master_records[0]
        name = fuzzy_get(rec, ["客戶名稱", "公司名稱", "Customer"])
        vat = fuzzy_get(rec, ["統一編號", "統編", "VAT"])
        print(f"  ✅ 客戶：{name} | 統編：{vat}")
    elif isinstance(master_records, dict) and "error" in master_records:
        print(f"  ⚠️ {master_records['error']}")
    else:
        print("  ⚠️ 找不到該客戶的基本資料。")

    # --- B. 查詢聯絡人 (App 71) ---
    print("\n👤 [2/5] 取得聯絡人清單...")
    fc_71 = get_field_code_by_label(71, ["客戶/供應商名稱", "客戶名稱", "Customer Name"]) or "客戶_供應商名稱"
    q_71 = f'{fc_71} like "{customer_name}" order by $id desc limit 3'
    contacts = get_kintone_data(71, q_71)
    
    if isinstance(contacts, list) and contacts:
        for c in contacts:
            c_name = fuzzy_get(c, ["聯絡人姓名", "姓名", "Name"])
            c_title = fuzzy_get(c, ["聯絡人職稱", "職稱", "Title"])
            c_phone = fuzzy_get(c, ["聯絡人手機", "聯絡人電話", "手機", "電話", "Phone", "Mobile"])
            print(f"  - 👤 {c_name} ({c_title}) / 📱: {c_phone}")
    elif isinstance(contacts, dict) and "error" in contacts:
        print(f"  ⚠️ {contacts['error']}")
    else:
        print("  ⚠️ 無聯絡人紀錄。")

    # --- C. 查詢最近活動/聯絡履歷 (App 96) ---
    print("\n📝 [3/5] 取得最近 3 筆聯絡紀錄...")
    fc_96 = get_field_code_by_label(96, ["客戶名稱", "公司名稱", "Customer Name"]) or "客戶名稱"
    q_96 = f'{fc_96} like "{customer_name}" order by $id desc limit 3'
    activities = get_kintone_data(96, q_96)
    
    if isinstance(activities, list) and activities:
        for a in activities:
            date = fuzzy_get(a, ["拜訪日期", "日期", "Date"])
            notes = fuzzy_get(a, ["紀錄內容", "內容", "備註", "Note"])
            short_notes = (notes[:30] + '...') if len(notes) > 30 else notes
            print(f"  - [{date}] {short_notes}")
    elif isinstance(activities, dict) and "error" in activities:
        print(f"  ⚠️ {activities['error']}")
    else:
        print("  ⚠️ 無聯絡履歷。")

    # --- D. 查詢近期訂單 (App 69) ---
    print("\n🛒 [4/5] 取得最近訂單 (Customer Order)...")
    fc_69 = get_field_code_by_label(69, ["客戶名稱", "公司名稱", "Customer Name"]) or "客戶名稱"
    q_69 = f'{fc_69} like "{customer_name}" order by $id desc limit 3'
    orders = get_kintone_data(69, q_69)
    
    if isinstance(orders, list) and orders:
        for o in orders:
            o_date = fuzzy_get(o, ["訂購日期", "日期", "Date"])
            o_num = fuzzy_get(o, ["訂購單編號", "單號", "No"])
            o_product = fuzzy_get(o, ["產品名稱", "產品", "Product"])
            o_total = fuzzy_get(o, ["金額合計(TWD)", "金額合計", "訂單金額", "Total"])
            print(f"  - 📅 {o_date} | 📄 {o_num}")
            print(f"    📦 {o_product} | 💰 ${o_total}")
    elif isinstance(orders, dict) and "error" in orders:
        print(f"  ⚠️ {orders['error']}")
    else:
        print("  ⚠️ 近期無訂單紀錄。")

    # --- E. 查詢歷史交易 POS (App 310) ---
    print("\n🏪 [5/5] 取得 POS 歷史交易紀錄...")
    # 動態查詢 POS 系統代表客戶名稱的真實 Field Code
    fc_310 = get_field_code_by_label(310, ["Customer Name", "CustomerName", "客戶名稱", "公司名稱"]) or "Customer_Name"
    q_310 = f'{fc_310} like "{customer_name}" order by $id desc limit 3'
    pos_records = get_kintone_data(310, q_310)
    
    if isinstance(pos_records, list) and pos_records:
        for p in pos_records:
            p_date = fuzzy_get(p, ["PO Date", "PO_Date", "PODate", "Shipping Date", "日期", "Date"])
            p_item = fuzzy_get(p, ["Product No", "Product_No", "Product", "產品", "品項", "Type"])
            p_qty = fuzzy_get(p, ["Qty", "數量", "Quantity"])
            p_total = fuzzy_get(p, ["Sales Total Price", "Sales_Total_Price", "Total", "金額", "Price", "Margin"])
            print(f"  - 🕒 {p_date} | 📦 {p_item} (數量: {p_qty}) | 💰 ${p_total}")
    elif isinstance(pos_records, dict) and "error" in pos_records:
        print(f"  ⚠️ {pos_records['error']}")
    else:
        print("  ⚠️ POS 系統無歷史紀錄。")
        
    print("\n" + "="*50)
    print("✨ 報告彙整完畢！祝您拜訪順利！")
    print("="*50 + "\n")

# ==========================================
# 4. 執行區塊
# ==========================================
if __name__ == "__main__":
    try:
        target_customer = input("請輸入要查詢的客戶名稱 (例如: 長榮): ")
        if target_customer.strip():
            fetch_customer_360(target_customer.strip())
        else:
            print("未輸入客戶名稱。")
    except Exception as e:
        print(f"發生未預期的錯誤: {e}")
    
    input("\n請按 Enter 鍵結束程式...")
