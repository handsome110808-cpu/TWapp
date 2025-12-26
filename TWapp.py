import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import datetime
import time
import pytz
import json
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 網頁設定 ---
st.set_page_config(
    page_title="AlphaTrader - AI 量化交易終端",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. 自定義 CSS ---
st.markdown("""
<style>
    .control-panel { background-color: #f8f9fa; padding: 20px; border-radius: 10px; border: 1px solid #ddd; margin-bottom: 20px; }
    .metric-card { background-color: #f0f2f6; border-radius: 10px; padding: 15px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }
    div.stButton > button { height: 3em; width: 100%; }
    .countdown-box { position: fixed; bottom: 10px; right: 10px; background-color: #ffffff; border: 1px solid #ddd; padding: 5px 10px; border-radius: 5px; font-size: 12px; color: #666; z-index: 999; }
    .snapshot-badge { background-color: #e3f2fd; color: #1565c0; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; border: 1px solid #bbdefb; }
    
    /* 資金流向樣式 */
    .flow-in { color: #00c853; font-weight: bold; }
    .flow-out { color: #d50000; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- 3. 全域設定與股票清單 ---
SNAPSHOT_FILE = 'market_flow_history.json'

# 您指定的美股+ADR清單
TARGET_TICKERS = sorted([
    "AAPL", "AMD", "APP", "ASML", "AVGO", "GOOG", "HIMS", "INTC",
    "LLY", "LRCX", "MSFT", "MU", "NBIS", "NVDA", "ORCL", "PLTR",
    "QQQ", "SPY", "XLV", "TEM", "TSLA", "TSM"
])

def load_snapshot(ticker):
    if not os.path.exists(SNAPSHOT_FILE): return None
    try:
        with open(SNAPSHOT_FILE, 'r') as f:
            data = json.load(f)
        return data.get(ticker)
    except: return None

def save_snapshot(ticker, price, flow_data):
    record = {
        "date": datetime.datetime.now().strftime('%Y-%m-%d'),
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "close_price": price,
        "flow_data": flow_data
    }
    all_data = {}
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f: all_data = json.load(f)
        except: pass
    all_data[ticker] = record
    with open(SNAPSHOT_FILE, 'w') as f: json.dump(all_data, f, indent=4)
    return True

# --- 4. 核心運算邏輯 (資金流向版) ---
def calculate_technical_indicators(df, atr_mult):
    """共用的技術指標與訊號計算邏輯"""
    if len(df) < 50: return df, "數據不足"
    df = df.ffill()

    # 1. 均線與趨勢
    df['EMA_8'] = ta.ema(df['Close'], length=8)
    df['EMA_21'] = ta.ema(df['Close'], length=21)
    
    # 2. MACD
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df = pd.concat([df, macd], axis=1)
        cols_map = {df.columns[-3]: 'MACD_Line', df.columns[-2]: 'MACD_Hist', df.columns[-1]: 'MACD_Signal'}
        df.rename(columns=cols_map, inplace=True)

    # 3. 資金流向指標 (Institutional Flow Proxies)
    # CMF (Chaikin Money Flow): 判斷主力吸籌(>0)或派發(<0)
    df['CMF'] = ta.cmf(df['High'], df['Low'], df['Close'], df['Volume'], length=20)
    # MFI (Money Flow Index): 資金動能 (類似RSI但含成交量)
    df['MFI'] = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)

    # 4. 波動率與止損
    df['Vol_SMA_10'] = ta.sma(df['Volume'], length=10)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    df['Stop_Loss'] = df['Close'] - (df['ATR'] * atr_mult)

    # --- 訊號判定邏輯 ---
    # 買進：趨勢向上 + 動能增強 + 資金流入 (CMF > -0.05, 允許輕微背離但不能大出貨)
    conditions = [
        (df['Close'] > df['EMA_8']) & 
        (df['EMA_8'] > df['EMA_21']) & 
        (df['MACD_Hist'] > 0) & 
        (df['MACD_Hist'] > df['MACD_Hist'].shift(1)) & 
        (df['CMF'] > -0.05) # 資金面確認：主力沒有明顯出貨
    ]
    df['Signal'] = np.select(conditions, ['BUY'], default='HOLD')
    
    # 賣出：跌破均線 或 資金大幅流出 (CMF < -0.15)
    sell_cond = (df['Close'] < df['EMA_21']) | (df['MACD_Hist'] < 0) | (df['CMF'] < -0.2)
    df.loc[sell_cond, 'Signal'] = 'SELL'
    
    return df, None

@st.cache_data(ttl=60)
def get_analysis_data(ticker, atr_mult):
    """單一股票詳細分析"""
    try:
        df = yf.download(ticker, period="6mo", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        if len(df) > 0:
            last_row = df.iloc[-1]
            if pd.isna(last_row['Close']): df = df.iloc[:-1]

        df, err = calculate_technical_indicators(df, atr_mult)
        if err: return None, err, None
        
        # 提取資金流向數據
        last = df.iloc[-1]
        flow_data = {
            "CMF": last['CMF'], # 資金流向
            "MFI": last['MFI'], # 資金動能
            "Vol_Ratio": last['Volume'] / last['Vol_SMA_10'] if last['Vol_SMA_10'] > 0 else 1.0
        }
        
        return df, None, flow_data
    except Exception as e:
        return None, str(e), None

@st.cache_data(ttl=60)
def scan_market_summary(tickers, atr_mult):
    """批次掃描全市場訊號 (含資金流向)"""
    summary = {"BUY": [], "HOLD": [], "SELL": []}
    
    try:
        data = yf.download(tickers, period="3mo", group_by='ticker', progress=False, threads=True)
        
        for ticker in tickers:
            try:
                df_t = data[ticker].copy()
                if len(df_t) > 0:
                    if pd.isna(df_t.iloc[-1]['Close']): df_t = df_t.iloc[:-1]
                if df_t.empty: continue

                df_t, err = calculate_technical_indicators(df_t, atr_mult)
                if err: continue
                
                last = df_t.iloc[-1]
                
                # 簡單標註資金狀態
                flow_status = " (資金入)" if last['CMF'] > 0.05 else " (資金出)" if last['CMF'] < -0.05 else ""
                ticker_display = f"{ticker}{flow_status}"
                
                if last['Signal'] == "BUY": summary["BUY"].append(ticker_display)
                elif last['Signal'] == "SELL": summary["SELL"].append(ticker_display)
                else: summary["HOLD"].append(ticker_display)
            except: continue
                
    except Exception as e: return None
    return summary

# --- 5. 介面佈局 ---
st.title("AlphaTrader 量化終端 (資金流向版)")

# 時間設定 (美股使用美東時間)
est = pytz.timezone('US/Eastern')
now_est = datetime.datetime.now(est)
is_market_open = (now_est.weekday() < 5) and (9 <= now_est.hour < 16) or (now_est.hour == 16 and now_est.minute == 0)
is_closing_window = (now_est.hour == 15 and now_est.minute >= 55)

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    with c1:
        # 預設選擇 NVDA
        default_idx = TARGET_TICKERS.index('NVDA') if 'NVDA' in TARGET_TICKERS else 0
        selected_ticker = st.selectbox("美股標的", TARGET_TICKERS, index=default_idx)
    with c2:
        atr_multiplier = st.slider("ATR 止損乘數", 1.5, 4.0, 2.5, 0.1)
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        auto_refresh = st.checkbox("每分刷新", value=True)
        if st.button("🔄 刷新"): st.rerun()
        
    time_str = now_est.strftime('%H:%M EST')
    status_text = "⚡ 收盤存檔中" if is_closing_window else "🟢 盤中交易" if is_market_open else "🌑 休市中"
    st.caption(f"{status_text} ({time_str})")
    st.markdown('</div>', unsafe_allow_html=True)

# === A. 單一股票詳細分析 ===
df, error, flow_data = get_analysis_data(selected_ticker, atr_multiplier)

if error:
    st.error(f"錯誤: {error}")
else:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    signal = last['Signal']
    
    # 自動存檔邏輯
    if is_closing_window and flow_data:
        saved = load_snapshot(selected_ticker)
        if not saved or saved.get('date') != now_est.strftime('%Y-%m-%d'):
            save_snapshot(selected_ticker, last['Close'], flow_data)
            st.toast(f"✅ {selected_ticker} 資金流向數據已存檔", icon="💾")

    # 頂部狀態
    if signal == 'BUY': st.success(f"🔥 {selected_ticker} 強力買進 (STRONG BUY)")
    elif signal == 'SELL': st.error(f"🛑 {selected_ticker} 離場/止損 (SELL/EXIT)")
    else: st.info(f"👀 {selected_ticker} 觀望/持有 (HOLD)")

    # 資金流向解讀
    cmf_val = flow_data['CMF']
    if cmf_val > 0.1: flow_status = "主力大舉買進"
    elif cmf_val > 0: flow_status = "資金溫和流入"
    elif cmf_val > -0.1: flow_status = "資金震盪/觀望"
    else: flow_status = "主力正在出貨"
    
    flow_color = "inverse" if cmf_val > 0 else "normal" # 綠色流入，紅色流出

    # KPI 卡片
    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric("最新價格", f"${last['Close']:.2f}", f"{(last['Close']-prev['Close']):.2f}")
    with k2: st.metric("建議止損", f"${last['Stop_Loss']:.2f}")
    with k3: st.metric("單股風險", f"${(last['Close']-last['Stop_Loss']):.2f}")
    with k4: st.metric("主力資金流 (CMF)", f"{cmf_val:.3f}", flow_status, delta_color="off" if cmf_val < 0 else "inverse")

    st.markdown("---")

    # 圖表區 (左圖右數據)
    main_col, side_col = st.columns([2, 1])
    with main_col:
        st.subheader("📈 價量與趨勢")
        # 繪製價格與均線
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_8'], line=dict(color='yellow', width=1), name='EMA 8'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_21'], line=dict(color='purple', width=1), name='EMA 21'), row=1, col=1)
        # CMF 資金指標
        colors = ['#00c853' if v >= 0 else '#d50000' for v in df['CMF']]
        fig.add_trace(go.Bar(x=df.index, y=df['CMF'], marker_color=colors, name='資金流 (CMF)'), row=2, col=1)
        fig.update_layout(height=500, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with side_col:
        st.subheader("📊 機構籌碼分析")
        
        # 1. CMF 資金流向 (核心判斷)
        st.write("**1. 資金淨流量 (CMF)**")
        cmf_pct = (cmf_val + 0.5) # 正規化顯示
        st.progress(min(max(cmf_pct, 0.0), 1.0), text=f"數值: {cmf_val:.3f} ({flow_status})")
        
        # 2. MFI 資金動能
        st.write("**2. 資金動能 (MFI)**")
        mfi_val = flow_data['MFI']
        st.progress(int(mfi_val), text=f"MFI: {mfi_val:.1f} ( >80 過熱, <20 超賣 )")
        
        # 3. 量能分析
        st.write("**3. 成交量能比**")
        vol_r = flow_data['Vol_Ratio']
        if vol_r > 1.5: st.warning(f"🔥 爆量攻擊 ({vol_r:.1f}x)")
        elif vol_r < 0.7: st.info(f"❄️ 量縮整理 ({vol_r:.1f}x)")
        else: st.write(f"⚖️ 量能溫和 ({vol_r:.1f}x)")
        
        st.markdown("---")
        st.info("💡 **解讀：** \nCMF > 0 代表機構吸籌(多頭)，CMF < 0 代表機構派發(空頭)。結合 MFI 判斷是否資金過熱。")

    # 歷史數據表格
    with st.expander("查看詳細數據"):
        cols = ['Close', 'Volume', 'EMA_8', 'CMF', 'MFI', 'Signal']
        fmt = {'Close':'{:.2f}', 'Volume':'{:.0f}', 'EMA_8':'{:.2f}', 'CMF':'{:.3f}', 'MFI':'{:.1f}'}
        st.dataframe(df[cols].tail(5).style.format(fmt))

# === B. 全市場訊號彙整總表 ===
st.markdown("---")
st.subheader("🌍 全市場資金流向總表 (Institutional Flow)")

with st.spinner("正在掃描市場訊號..."):
    market_signals = scan_market_summary(TARGET_TICKERS, atr_multiplier)

if market_signals:
    max_len = max(len(market_signals["BUY"]), len(market_signals["HOLD"]), len(market_signals["SELL"]))
    buy_list = market_signals["BUY"] + [""] * (max_len - len(market_signals["BUY"]))
    hold_list = market_signals["HOLD"] + [""] * (max_len - len(market_signals["HOLD"]))
    sell_list = market_signals["SELL"] + [""] * (max_len - len(market_signals["SELL"]))
    
    summary_df = pd.DataFrame({
        "BUY (資金流入)": buy_list,
        "HOLD (觀望/震盪)": hold_list,
        "SELL (資金流出)": sell_list
    })
    
    st.dataframe(
        summary_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "BUY (資金流入)": st.column_config.TextColumn(help="技術面強勢 + 資金淨流入"),
            "SELL (資金流出)": st.column_config.TextColumn(help="技術面轉弱 + 資金淨流出"),
            "HOLD (觀望/震盪)": st.column_config.TextColumn(help="多空不明或資金無明顯方向")
        }
    )
else:
    st.error("無法取得市場數據")

if auto_refresh:
    placeholder = st.empty()
    for s in range(60, 0, -1):
        now_str = datetime.datetime.now(est).strftime('%H:%M:%S')
        placeholder.markdown(f'<div class="countdown-box">🕒 {now_str} | ⏳ {s}s 刷新</div>', unsafe_allow_html=True)
        time.sleep(1)
    placeholder.empty()
    st.rerun()
