```python
import ccxt
import time
import pandas as pd
from datetime import datetime

# ==========================================
# [1] KONFIGURASI UTAMA (THE SYNDICATE HQ)
# ==========================================
API_KEY = 'YOUR_API_KEY_INDODAX'
SECRET_KEY = 'YOUR_SECRET_KEY_INDODAX'

SYMBOL_INDODAX = 'BTC/IDR'     # Untuk eksekusi beli di Indodax
SYMBOL_BINANCE = 'BTC/USDT'    # Untuk membaca grafik tanpa error
BUY_AMOUNT_IDR = 25000         # Amunisi tembakan (Rupiah Bulat)

# Parameter Indikator
RSI_PERIOD = 14
RSI_OVERSOLD = 30
SCAN_INTERVAL = 15       # Jeda antar cek pasar (detik)
COOLDOWN = 600           # Jeda istirahat setelah berhasil beli (detik)

# ==========================================
# [2] INISIALISASI DUA MESIN & LOGGER
# ==========================================
# Mesin 1: Indodax (Hanya untuk Eksekusi & Cek Uang)
indodax = ccxt.indodax({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
})

# Mesin 2: Binance (Hanya untuk Radar Harga, GRATIS TANPA API KEY)
binance = ccxt.binance({
    'enableRateLimit': True,
})

def log(msg, level="INFO"):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARN": "⚠️", "ERROR": "❌", "EXEC": "🚀", "BRAIN": "🧠", "MONEY": "💰", "RADAR": "📡"}
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {icons.get(level, '🔹')} {msg}")

# ==========================================
# [3] SISTEM KECERDASAN (RADAR BINANCE)
# ==========================================
def analisa_market_via_binance():
    try:
        # PENTING: Kita ambil data lilin dari Binance agar TIDAK ERROR.
        bars = binance.fetch_ohlcv(SYMBOL_BINANCE, timeframe='1m', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 1. Hitung RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # 2. Hitung MACD (12, 26, 9)
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # 3. Hitung Bollinger Bands (SMA 20)
        df['bb_mid'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_lower'] = df['bb_mid'] - (2 * df['bb_std'])
        
        return df
    except Exception as e:
        log(f"Radar Binance terganggu: {e}", "ERROR")
        return None

# ==========================================
# [4] AUDIT SALDO & EKSEKUSI INDODAX
# ==========================================
def eksekusi_beli_pasti():
    try:
        # LANGKAH 1: Cek Saldo Real-time di Indodax
        log("Mengakses brankas Indodax untuk cek saldo...", "INFO")
        balance = indodax.fetch_balance()
        idr_tersedia = balance.get('IDR', {}).get('free', 0)
        
        log(f"Saldo IDR Anda saat ini: Rp {int(idr_tersedia):,}", "MONEY")
        
        # LANGKAH 2: Validasi Amunisi
        if idr_tersedia < BUY_AMOUNT_IDR:
            log(f"Amunisi kurang! Bot butuh Rp {BUY_AMOUNT_IDR}, tapi saldo cuma Rp {int(idr_tersedia)}.", "WARN")
            return False
            
        # LANGKAH 3: Tembak Langsung di Indodax
        log(f"Mengeksekusi BELI {SYMBOL_INDODAX} senilai Rp {BUY_AMOUNT_IDR}...", "EXEC")
        
        order = indodax.private_post_trade({
            'pair': SYMBOL_INDODAX.replace('/', '_').lower(),
            'type': 'buy',
            'idr': int(BUY_AMOUNT_IDR)
        })
        
        # LANGKAH 4: Konfirmasi Sukses
        if order.get('success') == 1 or order.get('success') == '1':
            detail = order.get('return', {})
            terima = detail.get('receive_btc', 'koin')
            log(f"TRANSAKSI SUKSES! Saldo Rp{BUY_AMOUNT_IDR} telah ditukar menjadi {terima} {SYMBOL_INDODAX}.", "SUCCESS")
            return True
        else:
            pesan_error = order.get('error', 'Unknown Error')
            log(f"Transaksi Ditolak Server Indodax: {pesan_error}", "ERROR")
            return False

    except Exception as e:
        log(f"Koneksi Eksekusi Terputus: {e}", "ERROR")
        return False

# ==========================================
# [5] MAIN LOOP (KANTOR PUSAT)
# ==========================================
log(f"--- AsTraDax Absolute Final Aktif ---", "SUCCESS")
log(f"Radar: {SYMBOL_BINANCE} (Binance) | Eksekusi: {SYMBOL_INDODAX} (Indodax)", "RADAR")
log(f"Amunisi: Rp {BUY_AMOUNT_IDR} | Indikator: RSI, MACD, BB", "INFO")

while True:
    df = analisa_market_via_binance()
    
    if df is not None:
        curr = df.iloc[-1]
        
        # Evaluasi Kecerdasan
        rsi_ok = curr['rsi'] <= RSI_OVERSOLD
        macd_ok = curr['macd_hist'] > 0  
        bb_ok = curr['close'] <= curr['bb_lower'] 
        
        # Tampilkan status ke layar (Harga dalam USDT karena baca dari Binance)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧐 Harga Global(USDT): ${curr['close']:.2f} | RSI:{curr['rsi']:.1f} | BB_Low:${curr['bb_lower']:.0f} | MACD:{curr['macd_hist']:.1f}", end='\r')
        
        if rsi_ok and macd_ok and bb_ok:
            print("") 
            log(f"Triple Konfirmasi Valid! Pasar global sedang diskon besar.", "BRAIN")
            
            sukses = eksekusi_beli_pasti()
            
            if sukses:
                log(f"Bot istirahat {COOLDOWN/60} menit...", "INFO")
                time.sleep(COOLDOWN)
    
    time.sleep(SCAN_INTERVAL)


```
