# -*- coding: utf-8 -*-
import streamlit as st
import pyupbit
import pandas as pd
import sqlite3
import time
from datetime import datetime

st.set_page_config(page_title="1분봉 자가 학습 시스템 (공격형)", layout="wide")
DB = "pattern_learning.db"

# --- DB 초기화 ---
def init_db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    c = conn.cursor()
    
    # 지갑 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS wallet(
            id INTEGER PRIMARY KEY,
            krw REAL,
            btc_qty REAL,
            buy_price REAL,
            buy_rsi REAL,
            buy_ma_gap REAL
        )
    ''')
    # 거래 기록 및 학습 기록
    c.execute('''
        CREATE TABLE IF NOT EXISTS trade_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            rsi REAL,
            ma_gap REAL,
            result INTEGER
        )
    ''')
    # 지갑 초기화
    c.execute("SELECT * FROM wallet WHERE id=1")
    if c.fetchone() is None:
        c.execute("INSERT INTO wallet VALUES(1,10000000,0,0,0,0)")
        conn.commit()
    
    return conn

conn = init_db()
c = conn.cursor()

# --- 지갑 로드/저장 ---
def load_wallet():
    row = c.execute("SELECT * FROM wallet WHERE id=1").fetchone()
    return {
        "krw": row[1],
        "btc_qty": row[2],
        "buy_price": row[3],
        "buy_rsi": row[4],
        "buy_ma_gap": row[5]
    }

def save_wallet(wallet):
    c.execute(
        "UPDATE wallet SET krw=?, btc_qty=?, buy_price=?, buy_rsi=?, buy_ma_gap=? WHERE id=1",
        (wallet["krw"], wallet["btc_qty"], wallet["buy_price"], wallet["buy_rsi"], wallet["buy_ma_gap"])
    )
    conn.commit()

# --- 시장 데이터 ---
def get_market_data(ticker="KRW-BTC"):
    df = pyupbit.get_ohlcv(ticker, interval="minute1", count=100)
    if df is None: return None, None
    df['ma5'] = df['close'].rolling(3).mean()
    df['ma20'] = df['close'].rolling(10).mean()
    df['ma_gap'] = (df['ma5'] - df['ma20']) / df['ma20'] * 100
    delta = df['close'].diff()
    up, down = delta.copy(), delta.copy()
    up[up<0], down[down>0] = 0, 0
    df['rsi'] = 100 - (100 / (1 + (up.rolling(14).mean() / abs(down.rolling(14).mean()))))
    curr_price = pyupbit.get_current_price(ticker)
    return df, curr_price

# --- 매매 로직 ---
def trade():
    wallet = load_wallet()
    df, current_price = get_market_data()
    if df is None: return wallet, "데이터 없음"
    
    ma5_c, ma20_c = df['ma5'].iloc[-1], df['ma20'].iloc[-1]
    ma5_p, ma20_p = df['ma5'].iloc[-2], df['ma20'].iloc[-2]
    rsi, ma_gap = df['rsi'].iloc[-1], df['ma_gap'].iloc[-1]
    
    decision, reason = "hold", "조건 분석 중"
    
    # 매수
    if ma5_c > ma20_c and ma5_p <= ma20_p:
        win_rate = c.execute("SELECT AVG(result) FROM trade_history WHERE rsi BETWEEN ? AND ?", (rsi-5,rsi+5)).fetchone()[0]
        if win_rate is not None and win_rate < 0.4:
            decision, reason = "hold", f"과거 유사 패턴 승률 저조({win_rate*100:.1f}%)"
        else:
            if wallet["krw"] >= 10000:
                buy_amt = wallet["krw"] * 0.5
                wallet["btc_qty"] += buy_amt / current_price
                wallet["krw"] -= buy_amt
                wallet["buy_price"], wallet["buy_rsi"], wallet["buy_ma_gap"] = current_price, rsi, ma_gap
                decision, reason = "buy", "골든크로스 매수"
    
    # 매도
    elif ma5_c < ma20_c and ma5_p >= ma20_p and wallet["btc_qty"] > 0:
        result = 1 if current_price > wallet["buy_price"] else 0
        c.execute("INSERT INTO trade_history (timestamp,rsi,ma_gap,result) VALUES (?,?,?,?)",
                  (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), wallet["buy_rsi"], wallet["buy_ma_gap"], result))
        wallet["krw"] += wallet["btc_qty"] * current_price
        wallet["btc_qty"] = 0
        wallet["buy_price"], wallet["buy_rsi"], wallet["buy_ma_gap"] = 0, 0, 0
        decision, reason = "sell", f"데드크로스 매도 (결과:{result})"
    
    save_wallet(wallet)
    return wallet, reason

# --- Streamlit UI ---
st.title("📈 1분봉 자가 학습 매매 시스템")
wallet, reason = trade()
df, current_price = get_market_data()
if df is not None:
    total_asset = wallet["krw"] + wallet["btc_qty"] * current_price
    profit_loss = total_asset - 10000000
    profit_rate = (profit_loss / 10000000) * 100

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 자산", f"{total_asset:,.0f} 원")
    col2.metric("보유 현금", f"{wallet['krw']:,.0f} 원")
    col3.metric("수익률", f"{profit_rate:.2f} %", delta=f"{profit_loss:,.0f} 원")
    col4.metric("현재가", f"{current_price:,.0f} 원")

    st.subheader("BTC 1분봉 차트 (3/10 이동평균)")
    st.line_chart(df[['close','ma5','ma20']].tail(30))
    st.info(f"알고리즘 상태: {reason}")

st.subheader("최근 거래 기록")
history_db = pd.read_sql_query("SELECT * FROM trade_history ORDER BY id DESC LIMIT 5", conn)
st.table(history_db)

st.subheader("지갑 상태")
st.json(wallet)

# --- 1분마다 자동 갱신 ---
time.sleep(60)
st.experimental_rerun()
