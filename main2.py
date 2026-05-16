import os
import ccxt
import time
import pandas as pd
import warnings
from datetime import datetime
from dotenv import load_dotenv

# Matikan peringatan
warnings.filterwarnings('ignore')
load_dotenv()

# ==========================================
# [1] KONFIGURASI UTAMA (THE SYNDICATE HQ)
# ==========================================
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')

SYMBOL_INDODAX = 'PEPE/IDR'     
SYMBOL_RADAR = 'PEPE/USDT'      # Radar menggunakan KuCoin
BUY_AMOUNT_IDR = 14000          # Amunisi Rp 14.000

RSI_PERIOD = 14
RSI_OVERSOLD = 30
SCAN_INTERVAL = 15       
COOLDOWN = 600           

def log(msg, level="INFO"):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARN": "⚠️", "ERROR": "❌", "EXEC": "🚀", "BRAIN": "🧠", "MONEY": "💰", "RADAR": "📡"}
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {icons.get(level, '🔹')} {msg}")

if not API_KEY or not SECRET_KEY:
    log("KUNCI RAHASIA TIDAK DITEMUKAN! Pastikan file .env sudah dibuat dan diisi.", "ERROR")
    exit()

# ==========================================
# [2] INISIALISASI DUA MESIN 
# ==========================================
# Tangan (Eksekusi Indodax)
indodax = ccxt.indodax({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
})

# Mata (Radar KuCoin - Anti Blokir)
kucoin = ccxt.kucoin({
    'enableRateLimit': True,
})

# ==========================================
# [3] RADAR KUCOIN (KHUSUS MEMECOIN)
# ==========================================
def analisa_market_via_kucoin():
    try:
        # Ambil 100 lilin terakhir (1 Menit)
        bars = kucoin.fetch_ohlcv(SYMBOL_RADAR, timeframe='1m', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Hitung Indikator
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        df['bb_mid'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_lower'] = df['bb_mid'] - (2 * df['bb_std'])
        
        return df
    except Exception as e:
        log(f"Radar KuCoin terhalang: {e}", "ERROR")
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
            log(f"Amunisi kurang! Butuh Rp {BUY_AMOUNT_IDR}, saldo cuma Rp {int(idr_tersedia)}.", "WARN")
            return False
            
        log(f"Mengeksekusi BELI {SYMBOL_INDODAX} senilai Rp {BUY_AMOUNT_IDR}...", "EXEC")
        
        order = indodax.private_post_trade({
            'pair': SYMBOL_INDODAX.replace('/', '_').lower(),
            'type': 'buy',
            'idr': int(BUY_AMOUNT_IDR)
        })
        
        if order.get('success') == 1 or order.get('success') == '1':
            log(f"TRANSAKSI SUKSES! Pasukan PEPE berhasil diamankan senilai Rp{BUY_AMOUNT_IDR}.", "SUCCESS")
            return True
        else:
            log(f"Ditolak Indodax: {order.get('error', 'Unknown Error')}", "ERROR")
            return False

    except Exception as e:
        log(f"Koneksi Eksekusi Terputus: {e}", "ERROR")
        return False

# ==========================================
# [5] MAIN LOOP (KANTOR PUSAT PEPE)
# ==========================================
log(f"--- AsTraDax Assault Unit (Radar KuCoin) Aktif ---", "SUCCESS")

try:
    awal_balance = indodax.fetch_balance()
    idr_awal = awal_balance.get('IDR', {}).get('free', 0)
    log(f"Koneksi API Aman! Saldo awal kamu: Rp {int(idr_awal):,}", "MONEY")
except Exception as e:
    log(f"Gagal verifikasi kunci API. Error: {e}", "ERROR")
    exit()

while True:
    try:
        df = analisa_market_via_kucoin()
        
        if df is not None and not df.empty:
            curr = df.iloc[-1]
            
            rsi_ok = curr['rsi'] <= RSI_OVERSOLD
            macd_ok = curr['macd_hist'] > 0  
            bb_ok = curr['close'] <= curr['bb_lower'] 
            
            # Format desimal diperpanjang agar harga PEPE terlihat jelas
            harga_usd = float(curr['close'])
            rsi_val = float(curr['rsi'])
            bb_low_val = float(curr['bb_lower'])
            macd_val = float(curr['macd_hist'])
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧐 Harga(USDT): ${harga_usd:.8f} | RSI:{rsi_val:.1f} | BB_Low:${bb_low_val:.8f} | MACD:{macd_val:.8f}      ", end='\r')
            
            if rsi_ok and macd_ok and bb_ok:
                print("") 
                log(f"Sinyal Valid Ditemukan! Katak Hijau Diskon, Menginisiasi pembelian...", "BRAIN")
                
                if eksekusi_beli_pasti():
                    log(f"Bot istirahat sejenak selama {COOLDOWN/60} menit...", "INFO")
                    time.sleep(COOLDOWN)
        
    except Exception as e:
        log(f"Main Loop Error: {e}", "ERROR")
        
    time.sleep(SCAN_INTERVAL)
            
