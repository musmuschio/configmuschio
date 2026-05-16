import ccxt
import time
import pandas as pd
from datetime import datetime

# --- [ CONFIGURATION: THE SYNDICATE HQ ] ---
API_KEY = 'YOUR_API_KEY'
SECRET_KEY = 'YOUR_SECRET_KEY'
SYMBOL = 'BTC/IDR'
BUY_AMOUNT_IDR = 25000   # Amunisi per tembakan
RSI_PERIOD = 14
RSI_OVERSOLD = 30        # Target beli (RSI di bawah ini)
MIN_BALANCE_IDR = 10000  # Batas aman Indodax

# Inisialisasi Koneksi
exchange = ccxt.indodax({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
})

def log(msg, type="INFO"):
    now = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO": "ℹ️", "SUCCESS": "✅", "WARN": "⚠️", "ERROR": "🚨", "EXEC": "🚀"}
    print(f"[{now}] {icon.get(type, '🔹')} {msg}")

def hitung_rsi_manual(series, period=14):
    """Rumus RSI Standar (Tanpa Library Eksternal)"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def cek_saldo_idr():
    try:
        balance = exchange.fetch_balance()
        free_idr = balance.get('IDR', {}).get('free', 0)
        return int(free_idr)
    except Exception as e:
        log(f"Gagal akses saldo: {e}", "ERROR")
        return 0

def eksekusi_beli_final(amount):
    try:
        saldo_sekarang = cek_saldo_idr()
        log(f"Audit Saldo: Rp{saldo_sekarang} tersedia di dompet.", "INFO")

        if saldo_sekarang < amount:
            log(f"Amunisi kurang! Butuh Rp{amount}, cuma ada Rp{saldo_sekarang}.", "WARN")
            return False

        log(f"Mendobrak sistem Indodax dengan nominal Rp{int(amount)}...", "EXEC")
        
        # PARAMETER KRITIKAL: Menggunakan 'idr' untuk Market Buy V2
        params = {
            'pair': SYMBOL.replace('/', '_').lower(),
            'type': 'buy',
            'idr': int(amount) 
        }
        
        response = exchange.private_post_trade(params)
        
        if response.get('success') == '1' or response.get('success') == 1:
            log(f"TEMBAKAN BERHASIL! {SYMBOL} terbeli senilai Rp{amount}.", "SUCCESS")
            return True
        else:
            pesan_error = response.get('error', 'Unknown Rejected')
            log(f"Ditolak Indodax: {pesan_error}", "ERROR")
            return False
            
    except Exception as e:
        log(f"Kegagalan Komunikasi API: {e}", "ERROR")
        return False

# --- [ MAIN LOOP: OPERASIONAL SYNDICATE ] ---
log(f"AsTraDax V2.6 Aktif. Mengawasi {SYMBOL}...", "SUCCESS")

while True:
    try:
        # 1. Ambil Data Market
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe='1m', limit=50)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 2. Analisa Indikator
        df['rsi'] = hitung_rsi_manual(df['close'], RSI_PERIOD)
        current_rsi = df['rsi'].iloc[-1]
        current_price = df['close'].iloc[-1]
        
        # 3. Alert Detail ke Terminal
        status_msg = f"Price: {current_price} | RSI: {current_rsi:.2f}"
        if current_rsi <= RSI_OVERSOLD:
            log(f"{status_msg} -> [KONDISI TERPENUHI]", "SUCCESS")
            if eksekusi_beli_final(BUY_AMOUNT_IDR):
                log("Istirahat 10 menit untuk menghindari over-trading.", "INFO")
                time.sleep(600)
        else:
            # Alert tipis agar terminal tidak sepi tapi tidak spam
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧐 Memantau... {status_msg} (Target: <{RSI_OVERSOLD})", end='\r')
            
    except Exception as e:
        log(f"Loop Error: {e}", "ERROR")
    
    time.sleep(10) # Interval scan pasar
