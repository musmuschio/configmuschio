import ccxt
import time
import pandas as pd
from datetime import datetime

# ==========================================
# [1] KONFIGURASI UTAMA (THE SYNDICATE HQ)
# ==========================================
API_KEY = 'YOUR_API_KEY'
SECRET_KEY = 'YOUR_SECRET_KEY'

SYMBOL = 'BTC/IDR'
BUY_AMOUNT_IDR = 25000   # Amunisi tembakan (Rupiah Bulat)

# Parameter Indikator
RSI_PERIOD = 14
RSI_OVERSOLD = 30
SCAN_INTERVAL = 15       # Jeda antar cek pasar (detik)
COOLDOWN = 600           # Jeda istirahat setelah berhasil beli (detik)

# ==========================================
# [2] INISIALISASI & LOGGER
# ==========================================
exchange = ccxt.indodax({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
})

def log(msg, level="INFO"):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARN": "⚠️", "ERROR": "❌", "EXEC": "🚀", "BRAIN": "🧠", "MONEY": "💰"}
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {icons.get(level, '🔹')} {msg}")

# ==========================================
# [3] SISTEM KECERDASAN (TANPA PANDAS_TA)
# ==========================================
def analisa_market():
    try:
        # Ambil data lilin (candlestick) 1 menit terakhir
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe='1m', limit=100)
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
        log(f"Gagal mengambil data market: {e}", "ERROR")
        return None

# ==========================================
# [4] AUDIT SALDO & EKSEKUSI (ANTI-ERROR)
# ==========================================
def eksekusi_beli_pasti():
    try:
        # LANGKAH 1: Cek Saldo Real-time di Indodax
        log("Mengakses brankas Indodax untuk cek saldo...", "INFO")
        balance = exchange.fetch_balance()
        idr_tersedia = balance.get('IDR', {}).get('free', 0)
        
        log(f"Saldo IDR Anda saat ini: Rp {int(idr_tersedia):,}", "MONEY")
        
        # LANGKAH 2: Validasi Amunisi
        if idr_tersedia < BUY_AMOUNT_IDR:
            log(f"Amunisi kurang! Bot butuh Rp {BUY_AMOUNT_IDR}, tapi saldo cuma Rp {int(idr_tersedia)}.", "WARN")
            return False
            
        # LANGKAH 3: Tembak Langsung (Bypass Pembulatan Koin)
        log(f"Mengeksekusi BELI {SYMBOL} senilai Rp {BUY_AMOUNT_IDR}...", "EXEC")
        
        # Ini adalah jalur khusus API Indodax. Meminta beli berdasarkan RUPIAH, bukan Koin.
        order = exchange.private_post_trade({
            'pair': SYMBOL.replace('/', '_').lower(),
            'type': 'buy',
            'idr': int(BUY_AMOUNT_IDR)
        })
        
        # LANGKAH 4: Konfirmasi Sukses
        if order.get('success') == 1 or order.get('success') == '1':
            detail = order.get('return', {})
            terima = detail.get('receive_btc', 'koin')
            log(f"TRANSAKSI SUKSES! Saldo Rp{BUY_AMOUNT_IDR} telah ditukar menjadi {terima} {SYMBOL}.", "SUCCESS")
            return True
        else:
            pesan_error = order.get('error', 'Unknown Error')
            log(f"Transaksi Ditolak Server: {pesan_error}", "ERROR")
            return False

    except Exception as e:
        log(f"Koneksi Eksekusi Terputus: {e}", "ERROR")
        return False

# ==========================================
# [5] MAIN LOOP (KANTOR PUSAT)
# ==========================================
log(f"--- AsTraDax Ultimate Final (No-Simulasi) Aktif ---", "SUCCESS")
log(f"Target: {SYMBOL} | Amunisi: Rp {BUY_AMOUNT_IDR} | Indikator: RSI, MACD, BB", "INFO")

while True:
    df = analisa_market()
    
    if df is not None:
        curr = df.iloc[-1]
        
        # Evaluasi Kecerdasan
        rsi_ok = curr['rsi'] <= RSI_OVERSOLD
        macd_ok = curr['macd_hist'] > 0  # Momentum mulai positif
        bb_ok = curr['close'] <= curr['bb_lower'] # Menyentuh lantai bawah
        
        # Tampilkan status ke layar
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧐 P:{curr['close']} | RSI:{curr['rsi']:.1f} | BB_Low:{curr['bb_lower']:.0f} | MACD:{curr['macd_hist']:.1f}", end='\r')
        
        # Jika ketiga indikator setuju (Triple Confirmation)
        if rsi_ok and macd_ok and bb_ok:
            print("") # Pindah baris
            log(f"Triple Konfirmasi Valid! Harga termurah terdeteksi.", "BRAIN")
            
            sukses = eksekusi_beli_pasti()
            
            if sukses:
                log(f"Bot akan istirahat {COOLDOWN/60} menit agar tidak over-trading...", "INFO")
                time.sleep(COOLDOWN)
    
    time.sleep(SCAN_INTERVAL)
