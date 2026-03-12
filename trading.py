import streamlit as st
import pyupbit
import pandas as pd
import sqlite3
import time
from datetime import datetime

# --- 1. 설정 및 초기화 ---
st.set_page_config(page_title="1분봉 자가 학습 시스템 (공격형)", layout="wide")

# 데이터베이스 연결 (자가 학습용 오답 노트)
def init_db():
    conn = sqlite3.connect('pattern_learning.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trade_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  timestamp TEXT, rsi REAL, ma_gap REAL, result INTEGER)''')
    conn.commit()
    return conn

conn = init_db()

# 가상 지갑 및 상태 초기화 (초기 자금 1,000만 원)
if 'wallet' not in st.session_state:
    st.session_state.wallet = {
        "krw": 10000000.0, 
        "btc_qty": 0.0, 
        "buy_price": 0.0,
        "buy_rsi": 0.0, 
        "buy_ma_gap": 0.0, 
        "history": []
    }

# --- 2. 데이터 가져오기 및 지표 계산 (공격적 이평선 적용) ---
def get_market_data(ticker="KRW-BTC"):
    # 1분봉(minute1) 기준으로 실시간 분석
    df = pyupbit.get_ohlcv(ticker, interval="minute1", count=100)
    if df is None: return None, None
    
    # 이평선 수치 조정: 5->3, 20->10 (더 빠른 골든/데드크로스 발생)
    df['ma5'] = df['close'].rolling(3).mean()   # 3분 이동평균선
    df['ma20'] = df['close'].rolling(10).mean() # 10분 이동평균선
    df['ma_gap'] = (df['ma5'] - df['ma20']) / df['ma20'] * 100
    
    # RSI 계산 (최근 14분 기준)
    delta = df['close'].diff()
    up, down = delta.copy(), delta.copy()
    up[up < 0], down[down > 0] = 0, 0
    df['rsi'] = 100 - (100 / (1 + (up.rolling(14).mean() / abs(down.rolling(14).mean()))))
    
    curr_price = pyupbit.get_current_price(ticker)
    return df, curr_price

# --- 3. 메인 화면 구성 및 로직 ---
st.title("📈 1분봉 기반 자가 학습 눈매매 (공격형 세팅)")
st.caption(f"최근 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (3분/10분 이평선 적용)")

df, current_price = get_market_data()

if df is not None:
    # 현재 지표 추출 (3분/10분 선 비교)
    ma5_c, ma20_c = df['ma5'].iloc[-1], df['ma20'].iloc[-1]
    ma5_p, ma20_p = df['ma5'].iloc[-2], df['ma20'].iloc[-2]
    rsi, ma_gap = df['rsi'].iloc[-1], df['ma_gap'].iloc[-1]
    
    decision, reason = "hold", "조건 분석 중 (관망)"
    
    # [매수 판단] 3/10 골든크로스 + 자가 학습 필터
    if ma5_c > ma20_c and ma5_p <= ma20_p:
        cursor = conn.cursor()
        cursor.execute("SELECT AVG(result) FROM trade_history WHERE rsi BETWEEN ? AND ?", (rsi-5, rsi+5))
        win_rate = cursor.fetchone()[0]
        
        if win_rate is not None and win_rate < 0.4:
            decision, reason = "hold", f"과거 유사 패턴 승률 저조({win_rate*100:.1f}%)로 매수 필터링"
        else:
            decision, reason = "buy", "3/10 골든크로스 발생 (매수)"
            if st.session_state.wallet["krw"] >= 10000:
                buy_amt = st.session_state.wallet["krw"] * 0.5
                st.session_state.wallet["btc_qty"] += buy_amt / current_price
                st.session_state.wallet["krw"] -= buy_amt
                st.session_state.wallet["buy_price"], st.session_state.wallet["buy_rsi"], st.session_state.wallet["buy_ma_gap"] = current_price, rsi, ma_gap
                st.session_state.wallet["history"].append(f"[{datetime.now().strftime('%H:%M')}] 매수 완료 (3/10선)")

    # [매도 판단] 3/10 데드크로스 + 학습 기록
    elif ma5_c < ma20_c and ma5_p >= ma20_p and st.session_state.wallet["btc_qty"] > 0:
        decision, reason = "sell", "3/10 데드크로스 발생 (매도 및 학습)"
        result = 1 if current_price > st.session_state.wallet["buy_price"] else 0
        
        conn.cursor().execute("INSERT INTO trade_history (timestamp, rsi, ma_gap, result) VALUES (?,?,?,?)",
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                        st.session_state.wallet["buy_rsi"], 
                        st.session_state.wallet["buy_ma_gap"], result))
        conn.commit()
        
        st.session_state.wallet["krw"] += st.session_state.wallet["btc_qty"] * current_price
        st.session_state.wallet["btc_qty"] = 0.0
        st.session_state.wallet["history"].append(f"[{datetime.now().strftime('%H:%M')}] 매도 완료 (결과:{result})")

    # --- 대시보드 레이아웃 ---
    total_asset = st.session_state.wallet["krw"] + (st.session_state.wallet["btc_qty"] * current_price)
    profit_loss = total_asset - 10000000.0
    profit_rate = (profit_loss / 10000000.0) * 100

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 자산", f"{total_asset:,.0f} 원")
    col2.metric("보유 현금", f"{st.session_state.wallet['krw']:,.0f} 원")
    col3.metric("수익률", f"{profit_rate:.2f} %", delta=f"{profit_loss:,.0f} 원")
    col4.metric("현재가", f"{current_price:,.0f} 원")

    st.subheader("BTC/KRW 1분봉 차트 (3분/10분 이평선)")
    st.line_chart(df[['close', 'ma5', 'ma20']].tail(30))
    st.info(f"**알고리즘 상태:** {reason}")

st.divider()
st.subheader("📄 매매 로그 및 1분봉 학습 데이터")
col_log, col_db = st.columns(2)

with col_log:
    st.write("**최근 거래 내역**")
    for log in reversed(st.session_state.wallet["history"][-5:]):
        st.text(log)

with col_db:
    st.write("**1분봉 기반 학습 데이터 (최근 5건)**")
    try:
        history_db = pd.read_sql_query("SELECT * FROM trade_history ORDER BY id DESC LIMIT 5", conn)
        st.table(history_db)
    except:
        st.write("아직 쌓인 학습 데이터가 없습니다.")

st.subheader("💰 현재 지갑 세부 상태")
st.json(st.session_state.wallet)

# --- 자동 갱신 로직 ---
time.sleep(60)
st.rerun()
