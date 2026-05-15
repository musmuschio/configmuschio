import ccxt
import pandas as pd
import time
from datetime import datetime
import os
from dotenv import load_dotenv

# 1. Load Kredensial dari .env
load_dotenv()

# 2. Konfigurasi Exchange (Indodax)
EXCHANGE = ccxt.indodax({
    'apiKey': os.getenv('INDODAX_API_KEY'),
    'secret': os.getenv('INDODAX_SECRET_KEY'),
    'enableRateLimit': True,
})

SYMBOL = 'BTC/IDR'
TIMEFRAME = '1m'
BUY_AMOUNT_IDR = 10000  # Amunisi Eksekusi: Rp 10.000

def calculate_rsi(series, period=14):
    """Kalkulasi RSI Murni"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_bollinger_bands(series, window=20, std_dev=2):
    """Kalkulasi BB Murni"""
    sma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    return upper, lower

def get_balance():
    """Mengambil saldo dengan aman"""
    balance = EXCHANGE.fetch_balance()
    # Menggunakan .get() agar tidak error jika koin benar-benar kosong
    idr_balance = balance['free'].get('IDR', 0.0)
    btc_balance = balance['free'].get('BTC', 0.0)
    return idr_balance, btc_balance

def trade_engine():
    print("==================================================")
    print(f"🚀 MESIN TRADING REAL V2.0 (LIVE ON INDODAX) 🚀")
    print(f"Target: {SYMBOL} | Amunisi per Trade: Rp{BUY_AMOUNT_IDR}")
    print("==================================================\n")
    
    # Cek status awal
    _, btc_start = get_balance()
    in_pos = True if btc_start > 0.00001 else False
    
    while True:
        try:
            # Ambil data saldo terkini
            idr_now, btc_now = get_balance()
            
            # Tarik data pasar
            bars = EXCHANGE.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=50)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            close_prices = df['c']
            
            # Hitung Indikator
            rsi = calculate_rsi(close_prices).iloc[-1]
            upper_bb, lower_bb = calculate_bollinger_bands(close_prices)
            
            current_price = close_prices.iloc[-1]
            low_bb = lower_bb.iloc[-1]
            up_bb = upper_bb.iloc[-1]
            
            waktu = datetime.now().strftime('%H:%M:%S')
            
            # --- LOGIKA EKSEKUSI ---
            
            # 🟢 KONDISI BELI (Oversold & Sentuh Bawah)
            if rsi < 30 and current_price <= low_bb and not in_pos:
                if idr_now >= BUY_AMOUNT_IDR:
                    print(f"[{waktu}] 🟢 MENGEKSEKUSI BELI Rp10.000...")
                    order = EXCHANGE.create_market_buy_order(SYMBOL, BUY_AMOUNT_IDR)
                    print(f"[{waktu}] ✅ BERHASIL BELI | Order ID: {order['id']}")
                    in_pos = True
                else:
                    print(f"[{waktu}] ⚠️ Sinyal BUY muncul, tapi saldo IDR tidak cukup!")

            # 🔴 KONDISI JUAL (Overbought & Sentuh Atas)
            elif rsi > 70 and current_price >= up_bb and in_pos:
                if btc_now > 0.00001:
                    print(f"[{waktu}] 🔴 MENGEKSEKUSI JUAL SEMUA BTC...")
                    order = EXCHANGE.create_market_sell_order(SYMBOL, btc_now)
                    print(f"[{waktu}] ✅ BERHASIL JUAL | Order ID: {order['id']}")
                    in_pos = False
                else:
                    print(f"[{waktu}] ⚠️ Sinyal SELL muncul, tapi saldo BTC kosong!")

            # 🔍 SCANNING (Menunggu)
            else:
                status = "HOLDING BTC" if in_pos else "WAITING SIGNAL"
                print(f"[{waktu}] 🔍 {status} | Harga: Rp{current_price:,.0f} | RSI: {rsi:.2f}")
                
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Terjadi kendala: {e}")
            
        # Jeda 15 detik (Aman dari limit server Indodax)
        time.sleep(15)

if __name__ == "__main__":
    try:
        trade_engine()
    except KeyboardInterrupt:
        print("\nMesin dinonaktifkan.")
            
