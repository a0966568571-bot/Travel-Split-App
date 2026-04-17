import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date

# ==========================================
# 1. 資料庫核心 (Database Core)
# ==========================================

def init_db():
    conn = sqlite3.connect('travel_expense.db')
    c = conn.cursor()
    # 新增 members 欄位來儲存成員名單 (存成文字，如 "我,朋友A,朋友B")
    c.execute('''CREATE TABLE IF NOT EXISTS trips
                 (id INTEGER PRIMARY KEY, 
                  name TEXT, 
                  start_date TEXT, 
                  base_currency TEXT, 
                  target_currency TEXT, 
                  fixed_rate REAL,
                  members TEXT)''')
    
    # expenses 表保持大部分一樣，但 payer 現在是存名字
    c.execute('''CREATE TABLE IF NOT EXISTS expenses
                 (id INTEGER PRIMARY KEY, 
                  trip_id INTEGER, 
                  date TEXT, 
                  item TEXT, 
                  amount REAL, 
                  currency TEXT, 
                  payer TEXT, 
                  category TEXT, 
                  split_method TEXT, 
                  my_cost_twd REAL,
                  note TEXT,
                  FOREIGN KEY(trip_id) REFERENCES trips(id))''')
    conn.commit()
    conn.close()

def run_query(query, params=()):
    conn = sqlite3.connect('travel_expense.db')
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def execute_db(query, params=()):
    conn = sqlite3.connect('travel_expense.db')
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. 介面設定與側邊欄 (UI & Sidebar)
# ==========================================

# 讓介面更寬一點，方便看表格
st.set_page_config(page_title="分帳系統 V2", layout="wide")

# 初始化 Session State (用來做"修改模式")
if 'edit_mode' not in st.session_state:
    st.session_state.edit_mode = False
    st.session_state.edit_data = None

# --- 側邊欄 ---
# 需求 1: 不要有按鈕感，改用簡單的 Radio (Gemini 風格是單純的清單，Radio 是最接近的)
st.sidebar.header("功能選單")
trips = run_query("SELECT * FROM trips")
trip_options = {row['name']: row for index, row in trips.iterrows()}

if not trip_options:
    nav = "建立新旅程" # 強制跳轉
else:
    nav = st.sidebar.radio("前往", ["記帳看板", "建立新旅程"], label_visibility="collapsed")

# ==========================================
# 3. 建立新旅程 (支援多人設定)
# ==========================================
if nav == "建立新旅程":
    st.title("✈️ 建立新旅程")
    with st.container(border=True):
        st.info("💡 提示：在此設定這次旅行的所有夥伴，後續分帳會自動計算。")
        
        new_trip_name = st.text_input("旅程名稱", placeholder="例如: 2026 澳洲行")
        
        # 需求 4: 多人設定
        members_input = st.text_input("成員名單 (請用逗號隔開)", value="我, 朋友A", help="例如: 我, Jack, Rose")
        
        c1, c2 = st.columns(2)
        target_curr = c1.text_input("外幣代號", value="AUD")
        fixed_rate = c2.number_input(f"設定匯率 (1 {target_curr} = ? TWD)", value=20.45)
        
        if st.button("建立並開始", type="primary"):
            # 簡單處理成員字串：去除空白
            clean_members = ",".join([m.strip() for m in members_input.split(",") if m.strip()])
            
            execute_db("INSERT INTO trips (name, start_date, base_currency, target_currency, fixed_rate, members) VALUES (?, ?, ?, ?, ?, ?)",
                       (new_trip_name, datetime.today().strftime('%Y-%m-%d'), "TWD", target_curr, fixed_rate, clean_members))
            st.success("建立成功！請切換至「記帳看板」。")

# ==========================================
# 4. 記帳看板 (核心功能)
# ==========================================
elif nav == "記帳看板" and trip_options:
    selected_trip_name = st.sidebar.selectbox("切換旅程", list(trip_options.keys()))
    current_trip = trip_options[selected_trip_name]
    
    # 解析成員名單
    member_list = current_trip['members'].split(',')
    rate = current_trip['fixed_rate']
    
    st.title(f"💰 {current_trip['name']}")
    st.caption(f"成員: {', '.join(member_list)} | 匯率: {rate}")

    # --- 記帳/修改 表單 ---
    # 判斷標題
    form_title = "✏️ 修改消費紀錄" if st.session_state.edit_mode else "➕ 新增一筆消費"
    
    with st.expander(form_title, expanded=True):
        # 如果是修改模式，預填資料
        default_data = st.session_state.edit_data if st.session_state.edit_mode else {}
        
        # 第一排：日期 (需求 3) & 項目
        c1, c2 = st.columns([1, 2])
        # 日期預設邏輯：如果是修改，用舊日期；如果是新增，用今天
        default_date = datetime.strptime(default_data['date'], '%Y-%m-%d').date() if st.session_state.edit_mode else date.today()
        selected_date = c1.date_input("日期", value=default_date)
        
        item = c2.text_input("消費項目", value=default_data.get('item', ''))
        
        # 第二排：誰付錢 (需求 4)、幣別、金額
        c3, c4, c5 = st.columns([1, 1, 1.5])
        
        # 付款人選單：從資料庫成員名單抓
        payer_idx = member_list.index(default_data.get('payer')) if st.session_state.edit_mode and default_data.get('payer') in member_list else 0
        payer = c3.selectbox("誰先墊錢?", member_list, index=payer_idx)
        
        curr_idx = 1 if (st.session_state.edit_mode and default_data.get('currency') != 'TWD') else 1 # 預設外幣
        currency = c4.selectbox("幣別", ["TWD", current_trip['target_currency']], index=curr_idx)
        
        amount = c5.number_input("金額", min_value=0.0, step=1.0, value=default_data.get('amount', 0.0))
        
        st.divider()
        
        # 第三排：分帳邏輯 (需求 4)
        # 這裡我們簡化為兩種核心模式，適合大多數情境
        split_options = ["平分 (所有人)", "指定某人全額 (例如自用)", "自訂我的成本"]
        
        # 還原分帳選項的顯示 (這比較複雜，簡單做)
        default_split_idx = 0 
        if st.session_state.edit_mode:
            if "平分" in default_data.get('split_method', ''): default_split_idx = 0
            elif "指定" in default_data.get('split_method', ''): default_split_idx = 1
            else: default_split_idx = 2
            
        split_type = st.radio("分帳方式", split_options, index=default_split_idx, horizontal=True)
        
        # 額外邏輯
        target_person = None
        custom_val = 0.0
        
        if split_type == "指定某人全額 (例如自用)":
            target_person = st.selectbox("是誰的消費?", member_list)
        elif split_type == "自訂我的成本":
            custom_val = st.number_input("輸入「我 (User)」應負擔的金額 (原幣別)", min_value=0.0)

        # 按鈕邏輯
        btn_text = "更新紀錄" if st.session_state.edit_mode else "確認儲存"
        if st.button(btn_text, type="primary"):
            if amount == 0:
                st.warning("金額不能為 0")
            else:
                # 計算邏輯
                calc_rate = 1.0 if currency == "TWD" else rate
                my_cost_twd = 0.0
                
                # 計算歸屬於「我」的成本 (這決定儀表板的債務)
                # 假設 "我" 是 member_list 的第一個，或者名字就叫 "我"
                # 這裡我們約定：member_list[0] 是 App 的主要使用者
                myself_name = member_list[0] 
                
                if split_type == "平分 (所有人)":
                    my_cost_twd = (amount * calc_rate) / len(member_list)
                elif split_type == "指定某人全額 (例如自用)":
                    if target_person == myself_name:
                        my_cost_twd = amount * calc_rate
                    else:
                        my_cost_twd = 0.0
                elif split_type == "自訂我的成本":
                    my_cost_twd = custom_val * calc_rate

                # 寫入資料庫
                final_date_str = selected_date.strftime('%Y-%m-%d')
                
                if st.session_state.edit_mode:
                    # 更新模式：直接 UPDATE
                    execute_db('''UPDATE expenses SET date=?, item=?, amount=?, currency=?, payer=?, split_method=?, my_cost_twd=? WHERE id=?''',
                               (final_date_str, item, amount, currency, payer, split_type, my_cost_twd, st.session_state.edit_data['id']))
                    st.toast("✅ 修改成功！")
                    # 退出修改模式
                    st.session_state.edit_mode = False
                    st.session_state.edit_data = None
                else:
                    # 新增模式：INSERT
                    execute_db('''INSERT INTO expenses (trip_id, date, item, amount, currency, payer, split_method, my_cost_twd)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                               (current_trip['id'], final_date_str, item, amount, currency, payer, split_type, my_cost_twd))
                    st.toast("✅ 新增成功！")
                
                st.rerun()
                
        # 取消修改按鈕
        if st.session_state.edit_mode:
            if st.button("取消修改"):
                st.session_state.edit_mode = False
                st.session_state.edit_data = None
                st.rerun()

    # --- 歷史列表 & 編輯/刪除 (需求 2) ---
    st.subheader("📝 帳務明細")
    expenses = run_query("SELECT * FROM expenses WHERE trip_id = ? ORDER BY date DESC", (current_trip['id'],))
    
    if not expenses.empty:
        # 手機版優化顯示
        for index, row in expenses.iterrows():
            with st.container(border=True):
                # 第一行：標題與金額
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"**{row['date']} - {row['item']}**")
                c2.markdown(f"**{row['amount']} {row['currency']}**")
                
                # 第二行：細節
                st.caption(f"由 {row['payer']} 支付 | {row['split_method']} | 我應付: {row['my_cost_twd']:.1f} TWD")
                
                # 第三行：操作按鈕 (編輯 & 刪除)
                b1, b2 = st.columns([1, 1])
                if b1.button("✏️ 修改", key=f"edit_{row['id']}"):
                    st.session_state.edit_mode = True
                    st.session_state.edit_data = row.to_dict()
                    st.rerun()
                    
                if b2.button("🗑️ 刪除", key=f"del_{row['id']}"):
                    execute_db("DELETE FROM expenses WHERE id=?", (row['id'],))
                    st.toast("已刪除")
                    st.rerun()
                    
    # --- 簡易儀表板 ---
    if not expenses.empty:
        st.divider()
        st.subheader("📊 個人的收支狀況 (beta)")
        # 簡單計算：我墊付的 - 我該付的 = 別人欠我的
        # 這裡假設使用者是 member_list 裡有包含 "我" 這個字，或是名單第一位
        myself = member_list[0] # 預設第一位是使用者
        
        # 算出所有交易換算回台幣的總值
        def get_twd(r): return r['amount'] if r['currency']=='TWD' else r['amount']*rate
        expenses['real_twd'] = expenses.apply(get_twd, axis=1)
        
        total_paid = expenses[expenses['payer'] == myself]['real_twd'].sum()
        total_cost = expenses['my_cost_twd'].sum()
        balance = total_paid - total_cost
        
        col1, col2, col3 = st.columns(3)
        col1.metric("我墊付 (TWD)", f"{total_paid:,.0f}")
        col2.metric("我應付 (TWD)", f"{total_cost:,.0f}")
        col3.metric("結餘 (正=收錢)", f"{balance:,.0f}", delta_color="normal")