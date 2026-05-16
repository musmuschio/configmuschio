import ccxt
import time
import pandas as pd
import cloudscraper
from datetime import datetime

# ==========================================
# [1] KONFIGURASI UTAMA (THE SYNDICATE HQ)
# ==========================================
API_KEY = 'YOUR_API_KEY'
SECRET_KEY = 'YOUR_SECRET_KEY'

SYMBOL_API = 'BTC/IDR'       # Untuk eksekusi beli CCXT
SYMBOL_CHART = 'BTCIDR'      # Format khusus untuk Radar Indodax
BUY_AMOUNT_IDR = 25000       # Amunisi (Rupiah Bulat)

RSI_PERIOD = 14
RSI_OVERSOLD = 30
SCAN_INTERVAL = 15       
COOLDOWN = 600           

# ==========================================
# [2] INISIALISASI DUA MESIN (100% INDODAX)
# ==========================================
# Mesin Eksekusi (Tangan)
indodax = ccxt.indodax({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
})

# Mesin Radar Penyamar (Mata)
scraper = cloudscraper.create_scraper()

def log(msg, level="INFO"):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARN": "⚠️", "ERROR": "❌", "EXEC": "🚀", "BRAIN": "🧠", "MONEY": "💰"}
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {icons.get(level, '🔹')} {msg}")

# ==========================================
# [3] RADAR GRAFIK (MENEMBUS CLOUDFLARE)
# ==========================================
def get_indodax_chart():
    try:
        # Ambil waktu saat ini dan 100 menit ke belakang
        to_ts = int(time.time())
        from_ts = to_ts - (100 * 60)
        
        # Endpoint rahasia grafik Indodax
        url = f"https://indodax.com/tradingview/history_v2?symbol={SYMBOL_CHART}&resolution=1&from={from_ts}&to={to_ts}"
        
        # Menyamar sebagai manusia menggunakan Cloudscraper
        response = scraper.get(url).json()
        
        if response.get('s') == 'ok':
            # Susun data mentah menjadi tabel (DataFrame)
            df = pd.DataFrame({
                'timestamp': response['t'],
                'open': response['o'],
                'high': response['h'],
                'low': response['l'],
                'close': response['c'],
                'volume': response['v']
            })
            
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
        else:
            log(f"Format data Indodax berubah: {response}", "WARN")
            return None
            
    except Exception as e:
        log(f"Radar terhalang sistem keamanan: {e}", "ERROR")
        return None

# ==========================================
# [4] AUDIT SALDO & EKSEKUSI INDODAX
# ==========================================
def eksekusi_beli_pasti():
    try:
        log("Membuka brankas Indodax untuk verifikasi dana...", "INFO")
        balance = indodax.fetch_balance()
        idr_tersedia = balance.get('IDR', {}).get('free', 0)
        
        log(f"Dana Tersedia: Rp {int(idr_tersedia):,}", "MONEY")
        
        if idr_tersedia < BUY_AMOUNT_IDR:
            log(f"Operasi dibatalkan! Dana tidak cukup (Min: Rp {BUY_AMOUNT_IDR}).", "WARN")
            return False
            
        log(f"Mengeksekusi BELI {SYMBOL_API} senilai Rp {BUY_AMOUNT_IDR}...", "EXEC")
        
        order = indodax.private_post_trade({
            'pair': SYMBOL_API.replace('/', '_').lower(),
            'type': 'buy',
            'idr': int(BUY_AMOUNT_IDR)
        })
        
        if order.get('success') == 1 or order.get('success') == '1':
            terima = order.get('return', {}).get('receive_btc', 'koin')
            log(f"EKSEKUSI BERHASIL! Mendapatkan {terima} {SYMBOL_API}.", "SUCCESS")
            return True
        else:
            log(f"Eksekusi digagalkan server: {order.get('error', 'Error')}", "ERROR")
            return False

    except Exception as e:
        log(f"Jalur eksekusi terputus: {e}", "ERROR")
        return False

# ==========================================
# [5] KANTOR PUSAT OPERASIONAL
# ==========================================
log(f"--- AsTraDax V3 (Pure Indodax Engine) Aktif ---", "SUCCESS")
log(f"Sistem bekerja mandiri tanpa koneksi pihak ketiga.", "INFO")

while True:
    df = get_indodax_chart()
    
    if df is not None and not df.empty:
        curr = df.iloc[-1]
        
        rsi_ok = curr['rsi'] <= RSI_OVERSOLD
        macd_ok = curr['macd_hist'] > 0  
        bb_ok = curr['close'] <= curr['bb_lower'] 
        
        # Tampilan terminal yang rapi
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧐 Harga: Rp{curr['close']:,.0f} | RSI:{curr['rsi']:.1f} | BB_Low: Rp{curr['bb_lower']:,.0f} | MACD:{curr['macd_hist']:.0f}      ", end='\r')
        
        if rsi_ok and macd_ok and bb_ok:
            print("") 
            log("Sinyal Triple Konfirmasi Menyala! Memulai operasi pembelian...", "BRAIN")
            
            if eksekusi_beli_pasti():
                log(f"Sistem pendingin aktif selama {COOLDOWN/60} menit.", "INFO")
                time.sleep(COOLDOWN)
    
    time.sleep(SCAN_INTERVAL)
        
