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
    page_title="AlphaTrader - TW 量化交易終端",
    page_icon="📈",
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
    
    /* 總表樣式優化 */
    .summary-header { font-size: 20px; font-weight: bold; margin-bottom: 10px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# --- 3. 全域設定與快照功能 ---
SNAPSHOT_FILE = 'options_history.json'

# 指定的目標股票清單 (台股代碼需加上 .TW)
TARGET_TICKERS = sorted([
    "0050.TW",  # 元大台灣50
    "0056.TW",  # 元大高股息
    "00737.TW", # 國泰AI+Robo
    "2317.TW",  # 鴻海
    "2330.TW"   # 台積電
])

def load_snapshot(ticker):
    if not os.path.exists(SNAPSHOT_FILE): return None
    try:
        with open(SNAPSHOT_FILE, 'r') as f:
            data = json.load(f)
        return data.get(ticker)
    except: return None

def save_snapshot(ticker, price, pc_data):
    record = {
        "date": datetime.datetime.now().strftime('%Y-%m-%d'),
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "close_price": price,
        "pc_data": pc_data
    }
    all_data = {}
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f: all_data = json.load(f)
        except: pass
    all_data[ticker] = record
    with open(SNAPSHOT_FILE, 'w') as f: json.dump(all_data, f, indent=4)
    return True

# --- 4. 核心運算邏輯 (提取共用) ---
def calculate_technical_indicators(df, atr_mult):
    """共用的技術指標與訊號計算邏輯"""
    # 確保數據足夠
    if len(df) < 50: return df, "數據不足"
    
    # 填補空值
    df = df.ffill()

    # 計算指標
    df['EMA_8'] = ta.ema(df['Close'], length=8)
    df['EMA_21'] = ta.ema(df['Close'], length=21)
    
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df = pd.concat([df, macd], axis=1)
        # 重新命名欄位，避免後續抓不到
        cols_map = {
            df.columns[-3]: 'MACD_Line', 
            df.columns[-2]: 'MACD_Hist', 
            df.columns[-1]: 'MACD_Signal'
        }
        df.rename(columns=cols_map, inplace=True)

    df['Vol_SMA_10'] = ta.sma(df['Volume'], length=10)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    df['Stop_Loss'] = df['Close'] - (df['ATR'] * atr_mult)

    # 訊號判定邏輯
    # 1. 買進條件
    conditions = [
        (df['Close'] > df['EMA_8']) & 
        (df['EMA_8'] > df['EMA_21']) & 
        (df['MACD_Hist'] > 0) & 
        (df['MACD_Hist'] > df['MACD_Hist'].shift(1)) & 
        (df['Volume'] > df['Vol_SMA_10'] * 1.2)
    ]
    df['Signal'] = np.select(conditions, ['BUY'], default='HOLD')
    
    # 2. 賣出條件 (優先權高於 HOLD)
    sell_cond = (df['Close'] < df['EMA_21']) | (df['MACD_Hist'] < 0)
    df.loc[sell_cond, 'Signal'] = 'SELL'
    
    return df, None

@st.cache_data(ttl=60)
def get_signal(ticker, atr_mult):
    """單一股票詳細分析"""
    try:
        # 下載數據，台股建議使用 auto_adjust=True 處理除權息
        df = yf.download(ticker, period="6mo", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        # 處理非交易時段的空數據
        if len(df) > 0:
            last_row = df.iloc[-1]
            if pd.isna(last_row['Close']) or pd.isna(last_row['Open']): df = df.iloc[:-1]

        # 呼叫共用邏輯
        df, err = calculate_technical_indicators(df, atr_mult)
        if err: return None, err
        
        return df, None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=60)
def scan_market_summary(tickers, atr_mult):
    """批次掃描全市場訊號 (總表用)"""
    summary = {"BUY": [], "HOLD": [], "SELL": []}
    
    try:
        # 批次下載，使用 group_by='ticker' 方便後續處理
        data = yf.download(tickers, period="3mo", group_by='ticker', progress=False, threads=True, auto_adjust=True)
        
        for ticker in tickers:
            try:
                # 處理 MultiIndex 資料結構
                df_t = data[ticker].copy()
                
                # 簡單清洗
                if len(df_t) > 0:
                    last_row = df_t.iloc[-1]
                    if pd.isna(last_row['Close']): df_t = df_t.iloc[:-1]
                
                if df_t.empty: continue

                # 計算訊號 (使用相同的邏輯)
                df_t, err = calculate_technical_indicators(df_t, atr_mult)
                
                if err: continue
                
                last_sig = df_t.iloc[-1]['Signal']
                
                # 分類
                if last_sig == "BUY": summary["BUY"].append(ticker)
                elif last_sig == "SELL": summary["SELL"].append(ticker)
                else: summary["HOLD"].append(ticker)
            except:
                continue
                
    except Exception as e:
        return None
        
    return summary

@st.cache_data(ttl=300)
def get_advanced_pc_ratio(ticker, current_price):
    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations: return None, "無期權數據"
