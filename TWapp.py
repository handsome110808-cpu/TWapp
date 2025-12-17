import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime

# --- 1. 頁面設定 (台灣看盤風格) ---
st.set_page_config(
    page_title="台股智庫 - Pro Trader Terminal",
    page_icon="🇹🇼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定義 CSS (深色模式優化)
st.markdown("""
<style>
    .big-font { font-size: 24px !important; font-weight: bold; }
    .up-color { color: #ff3b30 !important; } /* 台灣漲是紅色 */
    .down-color { color: #30d158 !important; } /* 台灣跌是綠色 */
    div.stButton > button { width: 100%; }
</style>
""", unsafe_allow_html=True)


# --- 2. 核心數據與策略函數 ---
@st.cache_data(ttl=300)
def get_tw_stock_data(ticker):
    # 台股代號需加上 .TW
    stock_id = f"{ticker}.TW"

    # 抓取 1 年數據以計算長均線
    df = yf.download(stock_id, period="1y", interval="1d", progress=False)

    # 處理 MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # --- 計算台股關鍵指標 ---
    # 1. 均線系統 (MA)
    df['MA_5'] = ta.sma(df['Close'], length=5)  # 週線 (短線攻擊)
    df['MA_10'] = ta.sma(df['Close'], length=10)  # 雙週線
    df['MA_20'] = ta.sma(df['Close'], length=20)  # 月線 (生命線 - 法人防守點)
    df['MA_60'] = ta.sma(df['Close'], length=60)  # 季線 (景氣線 - 中長線趨勢)

    # 2. MACD (動能)
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)
    df.rename(columns={
        df.columns[-3]: 'MACD_Line',
        df.columns[-2]: 'MACD_Hist',
        df.columns[-1]: 'MACD_Signal'
    }, inplace=True)

    # 3. 籌碼/量能分析 (模擬法人動向)
    df['Vol_MA_5'] = ta.sma(df['Volume'], length=5)
    # 乖離率 (BIAS) - 判斷是否過熱
    df['BIAS_20'] = ((df['Close'] - df['MA_20']) / df['MA_20']) * 100

    return df


def analyze_strategy(df):
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    signals = []

    # --- 經理人邏輯判定 ---

    # 1. 趨勢判定 (權重 40%)
    if curr['Close'] > curr['MA_20'] and curr['MA_20'] > curr['MA_60']:
        score += 40
        signals.append("✅ 多頭排列 (站穩月季線)")
    elif curr['Close'] < curr['MA_20']:
        score -= 20
        signals.append("⚠️ 跌破月線 (短線轉弱)")

    # 2. 動能判定 (權重 30%)
    if curr['MACD_Hist'] > 0 and curr['MACD_Hist'] > prev['MACD_Hist']:
        score += 30
        signals.append("✅ MACD 動能增強 (紅柱放大)")
    elif curr['MACD_Hist'] < 0:
        score -= 20
        signals.append("🔴 MACD 空方控盤")

    # 3. 量能判定 (權重 30%) - 攻擊量
    if curr['Volume'] > curr['Vol_MA_5'] * 1.3:
        score += 30
        signals.append("🔥 爆量攻擊 (法人/主力進場)")
    elif curr['Volume'] < curr['Vol_MA_5'] * 0.7:
        signals.append("⚪ 量縮整理")

    # 綜合建議
    if score >= 70:
        action = "積極買進 (Strong Buy)"
        color = "red"
    elif score >= 30:
        action = "區間操作 / 持股續抱 (Hold)"
        color = "orange"
    else:
        action = "減碼 / 避險 (Sell/Avoid)"
        color = "green"  # 台股跌是綠色

    return action, color, signals, score


# --- 3. UI 介面設計 ---

# 側邊欄
with st.sidebar:
    st.title("🇹🇼 台股戰情室")
    st.markdown("---")
    target = st.radio("選擇標的", ["2330 台積電", "0050 元大台灣50"])
    ticker = target.split(" ")[0]

    st.info("""
    **經理人觀點：**
    * **短線：** 看 5日線 與 量能
    * **中線：** 看 20日線 (月線)
    * **操作：** 站上月線翻多，跌破月線停利
    """)

# 主畫面
st.header(f"📊 {target} 專業技術分析")

# 獲取數據
df = get_tw_stock_data(ticker)
last_row = df.iloc[-1]
prev_row = df.iloc[-2]

# 計算漲跌
change = last_row['Close'] - prev_row['Close']
pct_change = (change / prev_row['Close']) * 100
price_color = "red" if change >= 0 else "green"
arrow = "▲" if change >= 0 else "▼"

# 顯示價格看板
col1, col2, col3 = st.columns([1.5, 2, 1.5])

with col1:
    st.markdown(f"""
    <div style='text-align: center; border: 1px solid #ddd; padding: 10px; border-radius: 10px;'>
        <div style='font-size: 16px; color: gray;'>目前股價</div>
        <div style='font-size: 36px; font-weight: bold; color: {price_color};'>
            {last_row['Close']:.0f} <span style='font-size: 20px;'>{arrow} {abs(change):.1f} ({pct_change:.2f}%)</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

# 執行策略分析
action, action_color, reasons, total_score = analyze_strategy(df)

with col2:
    st.markdown(f"""
    <div style='text-align: center; background-color: #f0f2f6; padding: 10px; border-radius: 10px;'>
        <div style='font-size: 16px; color: gray;'>AI 經理人建議</div>
        <div style='font-size: 28px; font-weight: bold; color: {action_color};'>{action}</div>
        <div style='font-size: 14px;'>綜合評分: {total_score}/100</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    # 顯示關鍵均線位置
    st.metric("月線 (生命線)", f"{last_row['MA_20']:.1f}", delta=f"{last_row['Close'] - last_row['MA_20']:.1f}")
    st.metric("季線 (趨勢線)", f"{last_row['MA_60']:.1f}")

st.markdown("---")

# --- 4. 繪製專業 K 線圖 (Plotly) ---
# 設定分頁
tab1, tab2 = st.tabs(["📈 K線主圖 (Price)", "📊 籌碼與動能 (Indicators)"])

with tab1:
    # 建立雙軸圖表
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05, row_heights=[0.7, 0.3],
                        subplot_titles=('股價走勢 & 均線', '成交量'))

    # K棒 (台股紅漲綠跌)
    candlestick = go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name='K線',
        increasing_line_color='#ff3b30',  # 紅漲
        decreasing_line_color='#30d158'  # 綠跌
    )
    fig.add_trace(candlestick, row=1, col=1)

    # 均線
    fig.add_trace(go.Scatter(x=df.index, y=df['MA_5'], line=dict(color='orange', width=1), name='5日線'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA_20'], line=dict(color='purple', width=2), name='20日線(月)'), row=1,
                  col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA_60'], line=dict(color='blue', width=2), name='60日線(季)'), row=1,
                  col=1)

    # 成交量 (顏色隨漲跌變)
    colors = ['#ff3b30' if row['Open'] < row['Close'] else '#30d158' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)

    # 布局設定
    fig.update_layout(height=600, xaxis_rangeslider_visible=False,
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      font=dict(color='white' if st.get_option("theme.base") == "dark" else "black"))

    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("MACD 動能分析")
    # MACD 圖表
    fig_macd = make_subplots(rows=1, cols=1)

    # MACD 柱狀圖
    colors_macd = ['#ff3b30' if val >= 0 else '#30d158' for val in df['MACD_Hist']]
    fig_macd.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=colors_macd, name='MACD柱狀'), row=1, col=1)
    fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Line'], line=dict(color='orange'), name='DIF快線'), row=1,
                       col=1)
    fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='blue'), name='DEM慢線'), row=1,
                       col=1)

    fig_macd.update_layout(height=300, margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig_macd, use_container_width=True)

# --- 5. 策略診斷報告 ---
with st.expander("📋 查看詳細策略邏輯 (Strategy Report)", expanded=True):
    for signal in reasons:
        st.write(signal)

    st.markdown("---")
    st.caption("""
    **免責聲明：** 本工具僅供技術分析輔助，不包含即時法人籌碼（因需付費來源）。
    交易邏輯基於 20MA 月線戰法，適合作為中短線判斷依據。
    """)
