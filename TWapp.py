import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests

# --- 1. 頁面設定 (開啟深色護眼模式) ---
st.set_page_config(
    page_title="台股智庫 - Pro Trader Terminal",
    page_icon="🇹🇼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 自定義 CSS (深色護眼配色) ---
st.markdown("""
<style>
    /* 全局背景色 - 深炭灰 */
    .stApp {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    
    /* 側邊欄背景 */
    [data-testid="stSidebar"] {
        background-color: #262730;
    }

    /* 數據卡片樣式 - 深灰底柔和邊框 */
    .metric-card {
        background-color: #1E1E1E;
        border: 1px solid #333;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        text-align: center;
    }
    
    /* 漲跌顏色 (台灣紅漲綠跌，但在深色模式下稍微調亮一點以免刺眼) */
    .up-color { color: #FF4B4B !important; }
    .down-color { color: #00CC96 !important; }
    
    /* 文字優化 */
    .big-font { font-size: 24px !important; font-weight: bold; }
    .label-text { color: #A0A0A0; font-size: 14px; margin-bottom: 5px; }
    
    /* 按鈕全寬 */
    div.stButton > button { width: 100%; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# --- 2. 核心數據與策略函數 ---
@st.cache_data(ttl=300)
def get_tw_stock_data(ticker):
    stock_id = f"{ticker}.TW"
    try:
        df = yf.download(stock_id, period="1y", interval="1d", progress=False)
    except Exception:
        return None
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    if df.empty:
        return None
    
    # 計算指標
    df['MA_5'] = ta.sma(df['Close'], length=5)
    df['MA_20'] = ta.sma(df['Close'], length=20)
    df['MA_60'] = ta.sma(df['Close'], length=60)

    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df = pd.concat([df, macd], axis=1)
        df.rename(columns={
            df.columns[-3]: 'MACD_Line',
            df.columns[-2]: 'MACD_Hist',
            df.columns[-1]: 'MACD_Signal'
        }, inplace=True)
    else:
        df['MACD_Line'] = 0
        df['MACD_Hist'] = 0
        df['MACD_Signal'] = 0

    df['Vol_MA_5'] = ta.sma(df['Volume'], length=5)
    return df

def analyze_strategy(df):
    if df is None or len(df) < 60:
        return "數據不足", "gray", ["數據過少，無法計算技術指標"], 0

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    signals = []
    
    # 策略邏輯
    # 1. 趨勢
    if curr['Close'] > curr['MA_20'] and curr['MA_20'] > curr['MA_60']:
        score += 40
        signals.append("✅ 多頭排列 (站穩月季線)")
    elif curr['Close'] < curr['MA_20']:
        score -= 20
        signals.append("⚠️ 跌破月線 (短線轉弱)")
    else:
        signals.append("⚪ 均線糾結或盤整")
        
    # 2. 動能
    if curr['MACD_Hist'] > 0 and curr['MACD_Hist'] > prev['MACD_Hist']:
        score += 30
        signals.append("✅ MACD 動能增強 (紅柱放大)")
    elif curr['MACD_Hist'] < 0:
        score -= 20
        signals.append("🔴 MACD 空方控盤")
        
    # 3. 量能
    if curr['Vol_MA_5'] > 0 and curr['Volume'] > curr['Vol_MA_5'] * 1.3:
        score += 30
        signals.append("🔥 爆量攻擊 (資金進場)")
    elif curr['Vol_MA_5'] > 0 and curr['Volume'] < curr['Vol_MA_5'] * 0.7:
        signals.append("⚪ 量縮整理")

    # 綜合建議
    if score >= 70:
        action = "積極買進 (Strong Buy)"
        color = "#FF4B4B" # 亮紅
    elif score >= 30:
        action = "區間操作 / 續抱 (Hold)"
        color = "#FFA500" # 橘色
    else:
        action = "減碼 / 觀望 (Sell/Avoid)"
        color = "#00CC96" # 亮綠
        
    return action, color, signals, score

def send_line_notify(token, message):
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": "Bearer " + token}
    data = {"message": message}
    try:
        r = requests.post(url, headers=headers, data=data)
        return r.status_code == 200
    except Exception:
        return False

# --- 3. UI 介面設計 ---

with st.sidebar:
    st.title("🇹🇼 台股戰情室")
    st.caption("Dark Mode Enabled 🌙")
    st.markdown("---")
    
    stock_options = [
        "0050 元大台灣50", 
        "0056 元大高股息", 
        "00737 國泰AI+Robo", 
        "2330 台積電"
    ]
    
    target = st.radio("選擇標的", stock_options)
    ticker = target.split(" ")[0]
    
    st.markdown("---")
    st.header("🔔 LINE 通知設定")
    line_token = st.text_input("輸入 LINE Token", type="password")
    
    st.info("💡 **護眼模式小撇步：**\n如果覺得螢幕還是太亮，可嘗試調低螢幕亮度。本介面已優化對比度，低亮度下依然清晰。")

# 主畫面
st.header(f"📊 {target} 專業技術分析")

df = get_tw_stock_data(ticker)

if df is None:
    st.error(f"❌ 無法取得 {ticker} 數據，請確認代號是否正確。")
else:
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # 計算漲跌
    change = last_row['Close'] - prev_row['Close']
    pct_change = (change / prev_row['Close']) * 100
    # 深色模式專用配色
    price_color = "#FF4B4B" if change >= 0 else "#00CC96" 
    arrow = "▲" if change >= 0 else "▼"

    # 執行策略
    action, action_color, reasons, total_score = analyze_strategy(df)

    # 版面佈局
    col1, col2, col3 = st.columns([1.5, 2, 1.5])

    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="label-text">目前股價</div>
            <div style='font-size: 32px; font-weight: bold; color: {price_color};'>
                {last_row['Close']:.2f}
            </div>
            <div style='font-size: 18px; color: {price_color};'>
                {arrow} {abs(change):.2f} ({pct_change:.2f}%)
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="label-text">AI 經理人建議</div>
            <div style='font-size: 26px; font-weight: bold; color: {action_color}; margin: 5px 0;'>
                {action}
            </div>
            <div style='font-size: 14px; color: #CCC;'>綜合評分: {total_score}/100</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        # 使用 Streamlit 原生 metric，它會自動適應深色模式
        st.metric("月線 (生命線)", f"{last_row['MA_20']:.2f}", delta=f"{last_row['Close'] - last_row['MA_20']:.2f}")
        st.metric("季線 (趨勢線)", f"{last_row['MA_60']:.2f}")

    # LINE 按鈕
    st.markdown("---")
    if st.button("📲 發送 LINE 戰報", type="primary", disabled=not line_token):
        if not line_token:
            st.error("請先輸入 Token")
        else:
            msg = f"\n【台股戰情室】\n標的：{target}\n現價：{last_row['Close']:.2f}\n建議：{action}\n評分：{total_score}\n關鍵理由：\n"
            for r in reasons:
                msg += f"• {r}\n"
            if send_line_notify(line_token, msg):
                st.toast("✅ 戰報已發送！", icon="🚀")
            else:
                st.error("發送失敗")

    st.markdown("---")

    # --- 4. 繪製 K 線圖 (深色模式優化) ---
    tab1, tab2 = st.tabs(["📈 K線主圖", "📊 MACD 動能"])

    with tab1:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, row_heights=[0.7, 0.3],
                            subplot_titles=('股價 & 均線', '成交量'))

        # K棒
        candlestick = go.Candlestick(
            x=df.index,
            open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            name='K線',
            increasing_line_color='#FF4B4B', decreasing_line_color='#00CC96'
        )
        fig.add_trace(candlestick, row=1, col=1)

        # 均線 (顏色調整為高對比)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_5'], line=dict(color='#FFA500', width=1), name='5日線'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_20'], line=dict(color='#DDA0DD', width=2), name='20日線'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_60'], line=dict(color='#00BFFF', width=2), name='60日線'), row=1, col=1)

        # 成交量
        colors = ['#FF4B4B' if row['Open'] < row['Close'] else '#00CC96' for index, row in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)
        
        # ⚠️ 關鍵：套用 Plotly Dark 模板
        fig.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_dark")
        # 移除背景色，讓它透出網頁的深色背景
        fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("MACD 動能分析")
        fig_macd = make_subplots(rows=1, cols=1)
        colors_macd = ['#FF4B4B' if val >= 0 else '#00CC96' for val in df['MACD_Hist']]
        
        fig_macd.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=colors_macd, name='柱狀體'), row=1, col=1)
        fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Line'], line=dict(color='#FFA500'), name='DIF'), row=1, col=1)
        fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='#00BFFF'), name='DEM'), row=1, col=1)
        
        # ⚠️ 套用深色模板
        fig_macd.update_layout(height=300, template="plotly_dark",
                               paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_macd, use_container_width=True)
