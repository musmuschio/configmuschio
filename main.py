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
BUY_AMOUNT_IDR = 10000  # Amunisi 50rb kamu

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_bollinger_bands(series, window=20, std_dev=2):
    sma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    return upper, lower

def get_balance():
    """Mengambil saldo IDR dan BTC saat ini"""
    balance = EXCHANGE.fetch_balance()
    idr_balance = balance['free']['IDR']
    btc_balance = balance['free']['BTC']
    return idr_balance, btc_balance

def trade_engine():
    print("==================================================")
    print(f"🚀 MESIN TRADING REAL V2.0 (LIVE ON INDODAX) 🚀")
    print(f"Target: {SYMBOL} | Amunisi per Trade: Rp{BUY_AMOUNT_IDR}")
    print("==================================================\n")
    
    # Cek apakah mesin punya posisi BTC saat startup
    _, btc_start = get_balance()
    in_pos = True if btc_start > 0.00001 else False
    
    while True:
        try:
            # Ambil data saldo dan harga
            idr_now, btc_now = get_balance()
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
            
            # --- LOGIKA EKSEKUSI NYATA ---
            
            # 🟢 KONDISI BELI (BUY)
            if rsi < 30 and current_price <= low_bb and not in_pos:
                if idr_now >= BUY_AMOUNT_IDR:
                    print(f"[{waktu}] 🟢 MENGEKSEKUSI BELI...")
                    # Indodax Market Buy: Mengirim total IDR yang ingin dibelanjakan
                    order = EXCHANGE.create_market_buy_order(SYMBOL, BUY_AMOUNT_IDR)
                    print(f"[{waktu}] ✅ BERHASIL BELI | Info: {order['id']}")
                    in_pos = True
                else:
                    print(f"[{waktu}] ⚠️ Sinyal BUY muncul, tapi saldo IDR tidak cukup!")

            # 🔴 KONDISI JUAL (SELL)
            elif rsi > 70 and current_price >= up_bb and in_pos:
                if btc_now > 0.00001:
                    print(f"[{waktu}] 🔴 MENGEKSEKUSI JUAL...")
                    # Indodax Market Sell: Mengirim jumlah BTC yang ingin dijual
                    order = EXCHANGE.create_market_sell_order(SYMBOL, btc_now)
                    print(f"[{waktu}] ✅ BERHASIL JUAL | Info: {order['id']}")
                    in_pos = False
                else:
                    print(f"[{waktu}] ⚠️ Sinyal SELL muncul, tapi saldo BTC kosong!")

            else:
                status = "HOLDING BTC" if in_pos else "WAITING SIGNAL"
                print(f"[{waktu}] 🔍 {status} | Harga: Rp{current_price:,.0f} | RSI: {rsi:.2f}")
                
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Terjadi kendala: {e}")
            
        time.sleep(15) # Jeda agar tidak terkena limit API Indodax

if __name__ == "__main__":
    try:
        trade_engine()
    except KeyboardInterrupt:
        print("\nMesin dinonaktifkan.")
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
