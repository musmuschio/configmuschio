import ccxt
import time
import pandas as pd
import numpy as np
from datetime import datetime

# --- [ CONFIGURATION ] ---
API_KEY = 'YOUR_API_KEY'
SECRET_KEY = 'YOUR_SECRET_KEY'
SYMBOL = 'BTC/IDR'
BUY_AMOUNT_IDR = 25000   
RSI_PERIOD = 14
RSI_OVERSOLD = 30        

# --- [ INDICATOR CALCULATORS (NO DEPENDENCY) ] ---

def get_indicators(df):
    # 1. RSI (Manual)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # 2. MACD (Manual)
    # Fast EMA (12), Slow EMA (26), Signal (9)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # 3. Bollinger Bands (Manual)
    # Simple Moving Average (20) & Std Deviation
    df['bb_mid'] = df['close'].rolling(window=20).mean()
    df['bb_std'] = df['close'].rolling(window=20).std()
    df['bb_lower'] = df['bb_mid'] - (2 * df['bb_std'])
    df['bb_upper'] = df['bb_mid'] + (2 * df['bb_std'])
    
    return df

# --- [ OPERATIONAL FUNCTIONS ] ---

def log(msg, type="INFO"):
    now = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO": "ℹ️", "SUCCESS": "✅", "WARN": "⚠️", "EXEC": "🚀", "BRAIN": "🧠"}
    print(f"[{now}] {icon.get(type, '🔹')} {msg}")

def cek_evaluasi_kecerdasan(df):
    """Logika Konfirmasi Berlapis (Triple Check)"""
    current = df.iloc[-1]
    
    rsi_ok = current['rsi'] <= RSI_OVERSOLD
    # MACD Histogram > 0 artinya momentum mulai naik (Golden Cross/Bullish)
    macd_ok = current['macd_hist'] > 0 
    # Harga di bawah atau menyentuh Lower Band (Harga sudah sangat murah)
    bb_ok = current['close'] <= current['bb_lower']
    
    log(f"Analisa: RSI({current['rsi']:.1f}) | MACD_H({current['macd_hist']:.2f}) | BB_L({current['bb_lower']:.0f})", "BRAIN")
    
    # Syarat mutlak: Ketiganya harus memberikan sinyal positif
    if rsi_ok and macd_ok and bb_ok:
        return True
    return False

# ... (Fungsi eksekusi_beli_final tetap sama dengan V2.6) ...

# --- [ MAIN LOOP ] ---
log(f"AsTraDax V2.7 'Intelligence' Online. Monitoring {SYMBOL}...", "SUCCESS")

while True:
    try:
        exchange = ccxt.indodax({'apiKey': API_KEY, 'secret': SECRET_KEY})
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe='1m', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Hitung 3 Indikator sekaligus
        df = get_indicators(df)
        
        # Evaluasi Kecerdasan
        if cek_evaluasi_kecerdasan(df):
            log("🎯 KONFIRMASI TRIPLE: RSI, MACD, dan BB Setuju! EKSEKUSI!", "SUCCESS")
            # panggil fungsi eksekusi_beli_final(BUY_AMOUNT_IDR) di sini
            time.sleep(600)
        else:
            # Monitoring Mode
            curr = df.iloc[-1]
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧐 Menunggu Sinyal Kompak... (P:{curr['close']} RSI:{curr['rsi']:.1f})", end='\r')
            
    except Exception as e:
        log(f"System Error: {e}", "ERROR")
    
    time.sleep(15)

