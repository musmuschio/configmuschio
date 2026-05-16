import ccxt
import time
import pandas as pd
import yfinance as yf
import warnings
from datetime import datetime

# Matikan pesan peringatan yang tidak penting dari library
warnings.filterwarnings('ignore')

# ==========================================
# [1] KONFIGURASI UTAMA (THE SYNDICATE HQ)
# ==========================================
API_KEY = 'YOUR_API_KEY'
SECRET_KEY = 'YOUR_SECRET_KEY'

SYMBOL_INDODAX = 'BTC/IDR'     # Eksekusi Rupiah
SYMBOL_YAHOO = 'BTC-USD'       # Radar Harga (Dolar)
BUY_AMOUNT_IDR = 25000         # Amunisi tembakan

RSI_PERIOD = 14
RSI_OVERSOLD = 30
SCAN_INTERVAL = 15       
COOLDOWN = 600           

# ==========================================
# [2] INISIALISASI MESIN EKSEKUSI INDODAX
# ==========================================
indodax = ccxt.indodax({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
})

def log(msg, level="INFO"):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARN": "⚠️", "ERROR": "❌", "EXEC": "🚀", "BRAIN": "🧠", "MONEY": "💰"}
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {icons.get(level, '🔹')} {msg}")

# ==========================================
# [3] RADAR YAHOO FINANCE (ANTI-BLOKIR)
# ==========================================
def analisa_market_via_yahoo():
    try:
        # Mengambil data 1 menit dari Yahoo Finance
        df = yf.download(tickers=SYMBOL_YAHOO, period='5d', interval='1m', progress=False)
        
        if df.empty:
            return None
            
        # Menyesuaikan nama kolom Yahoo untuk rumus kita
        df['close'] = df['Close']
        df['low'] = df['Low']
        
        # Hitung RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # Hitung MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # Hitung Bollinger Bands
        df['bb_mid'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_lower'] = df['bb_mid'] - (2 * df['bb_std'])
        
        return df
    except Exception as e:
        log(f"Gangguan sinyal Yahoo: {e}", "ERROR")
        return None

# ==========================================
# [4] AUDIT SALDO & EKSEKUSI INDODAX
# ==========================================
def eksekusi_beli_pasti():
    try:
        balance = indodax.fetch_balance()
        idr_tersedia = balance.get('IDR', {}).get('free', 0)
        
        log(f"Audit Saldo IDR: Rp {int(idr_tersedia):,}", "MONEY")
        
        if idr_tersedia < BUY_AMOUNT_IDR:
            log(f"Amunisi kurang! Bot butuh Rp {BUY_AMOUNT_IDR}, saldo cuma Rp {int(idr_tersedia)}.", "WARN")
            return False
            
        log(f"Mengeksekusi BELI {SYMBOL_INDODAX} senilai Rp {BUY_AMOUNT_IDR}...", "EXEC")
        
        order = indodax.private_post_trade({
            'pair': SYMBOL_INDODAX.replace('/', '_').lower(),
            'type': 'buy',
            'idr': int(BUY_AMOUNT_IDR)
        })
        
        if order.get('success') == 1 or order.get('success') == '1':
            terima = order.get('return', {}).get('receive_btc', 'koin')
            log(f"TRANSAKSI SUKSES! Saldo Rp{BUY_AMOUNT_IDR} telah menjadi {terima} {SYMBOL_INDODAX}.", "SUCCESS")
            return True
        else:
            log(f"Ditolak Indodax: {order.get('error', 'Unknown Error')}", "ERROR")
            return False

    except Exception as e:
        log(f"Koneksi Eksekusi Terputus: {e}", "ERROR")
        return False

# ==========================================
# [5] MAIN LOOP (KANTOR PUSAT)
# ==========================================
log(f"--- AsTraDax Ultimate (Yahoo Finance Radar) Aktif ---", "SUCCESS")

# CEK SALDO AWAL AGAR KAMU TENANG
try:
    awal_balance = indodax.fetch_balance()
    idr_awal = awal_balance.get('IDR', {}).get('free', 0)
    log(f"Koneksi Indodax Sukses! Saldo awal kamu: Rp {int(idr_awal):,}", "MONEY")
except Exception as e:
    log(f"Gagal mengecek saldo awal. Cek API Key kamu! Error: {e}", "ERROR")

while True:
    df = analisa_market_via_yahoo()
    
    if df is not None and not df.empty:
        curr = df.iloc[-1]
        
        rsi_ok = curr['rsi'] <= RSI_OVERSOLD
        macd_ok = curr['macd_hist'] > 0  
        bb_ok = curr['close'] <= curr['bb_lower'] 
        
        # Harga tampil dalam USD (karena dari Yahoo), tapi eksekusi tetap Rupiah di Indodax
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧐 Harga(USD): ${float(curr['close']):,.2f} | RSI:{curr['rsi']:.1f} | BB_Low:${float(curr['bb_lower']):,.0f} | MACD:{curr['macd_hist']:.1f}      ", end='\r')
        
        if rsi_ok and macd_ok and bb_ok:
            print("") 
            log(f"Sinyal Valid Ditemukan! Menginisiasi pembelian...", "BRAIN")
            
            if eksekusi_beli_pasti():
                log(f"Bot istirahat sejenak selama {COOLDOWN/60} menit...", "INFO")
                time.sleep(COOLDOWN)
    
    time.sleep(SCAN_INTERVAL)
        
