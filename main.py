import ccxt
import pandas as pd
import time
from datetime import datetime

# Konfigurasi Mesin
EXCHANGE = ccxt.binance()
SYMBOL = 'BTC/USDT'
TIMEFRAME = '1m'

def calculate_rsi(series, period=14):
    """Kalkulasi RSI Murni tanpa library eksternal"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_bollinger_bands(series, window=20, std_dev=2):
    """Kalkulasi BB Murni tanpa library eksternal"""
    sma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    return upper, lower

def trade_engine():
    print("==================================================")
    print(f"🚀 MESIN TRADING MANUAL (TANPA PANDAS-TA) AKTIF 🚀")
    print(f"Target: {SYMBOL} | Mode: SIMULASI PENGINTAIAN")
    print("==================================================\n")
    
    in_pos = False
    
    while True:
        try:
            # Tarik Data Harga Terkini
            bars = EXCHANGE.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=50)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            close_prices = df['c']
            
            # Eksekusi Rumus Matematika
            rsi = calculate_rsi(close_prices).iloc[-1]
            upper_bb, lower_bb = calculate_bollinger_bands(close_prices)
            
            current_price = close_prices.iloc[-1]
            low_bb = lower_bb.iloc[-1]
            up_bb = upper_bb.iloc[-1]
            
            waktu = datetime.now().strftime('%H:%M:%S')
            
            # Logika Pemicu (Trigger)
            if rsi < 30 and current_price <= low_bb and not in_pos:
                print(f"[{waktu}] 🟢 [BUY EKSEKUSI] Harga: ${current_price} | RSI: {rsi:.2f}")
                in_pos = True
            elif rsi > 70 and current_price >= up_bb and in_pos:
                print(f"[{waktu}] 🔴 [SELL EKSEKUSI] Harga: ${current_price} | RSI: {rsi:.2f}")
                in_pos = False
            else:
                # Log pemantauan datar
                status = "HOLDING" if in_pos else "SCANNING"
                print(f"[{waktu}] 🔍 {status} | Harga: ${current_price} | RSI: {rsi:.2f} | BB_Low: ${low_bb:.1f}")
                
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Koneksi terputus/Error: {e}")
            
        # Jeda 10 detik agar tidak diblokir Binance
        time.sleep(10)

if __name__ == "__main__":
    try:
        trade_engine()
    except KeyboardInterrupt:
        print("\nMesin dimatikan secara manual.")
