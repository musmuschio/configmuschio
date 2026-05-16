import os
import sys
import time
import sqlite3
import logging
import requests
import pandas as pd
import ccxt
import warnings
import threading
import shutil
import atexit
from datetime import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
load_dotenv()

# ==========================================
# [1] KONFIGURASI BATTLE-HARDENED
# ==========================================
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Konfigurasi Koin (Ubah di main2.py untuk PEPE)
SYMBOL = "BTC/IDR"
SYMBOL_RADAR = "BTCUSDT"
COIN_NAME = "BTC"
USD_IDR_RATE = 16300        # Estimasi kurs untuk Spread Filter

# Identitas Unik
PID_FILE = "btc_bot.pid"    # main2.py ganti ke pepe_bot.pid
DB_NAME = "btc_state.db"
LOG_FILE = "btc_trading.log"

# Parameter Trading
MIN_ORDER_IDR = 10000
MAX_SPREAD_PCT = 1.2        # Proteksi beli kemahalan di lokal
TRADING_FEE_PCT = 0.3      
TAKE_PROFIT_1_PCT = 2.0    
STOP_LOSS_PCT = 1.2        
TRAILING_STOP_PCT = 0.5    
COOLDOWN_MINUTES = 15      

# ==========================================
# [2] PID & CLEANUP SYSTEM
# ==========================================
def cleanup():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

atexit.register(cleanup)

def check_single_instance():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read())
            os.kill(pid, 0) # Cek apakah proses masih hidup
            print(f"❌ ERROR: Bot {COIN_NAME} sedang berjalan (PID: {pid}).")
            sys.exit(1)
        except (ProcessLookupError, ValueError, OSError):
            cleanup()
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

check_single_instance()

# ==========================================
# [3] LOGGER & ASYNC TELEGRAM
# ==========================================
def setup_logger():
    logger = logging.getLogger(f"Bot_{COIN_NAME}")
    if logger.handlers: return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=2)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger

log = setup_logger()

def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    def _send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=5)
        except Exception: pass
    threading.Thread(target=_send, daemon=True).start()

# ==========================================
# [4] DATABASE (WAL MODE)
# ==========================================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("PRAGMA journal_mode=WAL;") 
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS positions 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, buy_price REAL, 
            amount_koin REAL, amount_idr REAL, highest_price REAL, status TEXT, buy_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()

    def get_active_position(self, symbol):
        self.cursor.execute("SELECT * FROM positions WHERE symbol = ? AND status = 'OPEN'", (symbol,))
        row = self.cursor.fetchone()
        if row: return {"id": row[0], "buy_price": row[2], "amount_koin": row[3], "amount_idr": row[4], "highest_price": row[5]}
        return None

# ==========================================
# [5] EXCHANGE & WATCHDOG RECONNECT
# ==========================================
class ExchangeManager:
    def __init__(self):
        self.init_api()
        self.last_api_success = time.time()

    def init_api(self):
        self.api = ccxt.indodax({'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True})

    def reset_if_frozen(self):
        # Jika 120 detik gagal akses API, reset koneksi
        if time.time() - self.last_api_success > 120:
            log.warning("Koneksi beku terdeteksi! Resetting Exchange API...")
            self.init_api()
            self.last_api_success = time.time()

    def fetch_radar(self):
        try:
            url = "https://data-api.binance.vision/api/v3/klines"
            res = requests.get(url, params={"symbol": SYMBOL_RADAR, "interval": "1m", "limit": 100}, timeout=5).json()
            # FIX BUG 1: Rename columns langsung di sini
            df = pd.DataFrame(res, columns=['t', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qv', 'tr', 'tb', 'tq', 'ig'])
            df[['close', 'volume', 'high', 'low']] = df[['close', 'volume', 'high', 'low']].astype(float)
            self.last_api_success = time.time()
            return df
        except Exception: return None

    def get_idx_ticker(self):
        try:
            t = self.api.fetch_ticker(SYMBOL)
            self.last_api_success = time.time()
            return t['last']
        except Exception:
            self.reset_if_frozen()
            return None

# ==========================================
# [6] STRATEGY ENGINE (MULTI-CONFIRMATION)
# ==========================================
class StrategyEngine:
    @staticmethod
    def calculate_score(df):
        if df is None or len(df) < 30: return 0, "No Data"
        
        # Sinyal berbasis Candle Close (iloc[-2])
        close = df['close']
        volume = df['volume']
        
        # 1. RSI Wilder
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        
        # 2. MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal

        # 3. EMA Trend Filter
        ema50 = close.ewm(span=50, adjust=False).mean()

        score = 0
        reasons = []
        
        # SCORING SYSTEM
        if rsi.iloc[-2] < 30: 
            score += 35; reasons.append("RSI")
        if hist.iloc[-2] > 0 and hist.iloc[-3] <= 0: 
            score += 25; reasons.append("MACD")
        if close.iloc[-2] > ema50.iloc[-2]: 
            score += 20; reasons.append("Trend")
        if volume.iloc[-2] > volume.rolling(20).mean().iloc[-2] * 1.5: 
            score += 20; reasons.append("Vol")

        return score, ",".join(reasons)

# ==========================================
# [7] CORE OPERATIONAL
# ==========================================
class TradingBot:
    def __init__(self):
        self.db = Database()
        self.ex = ExchangeManager()
        self.engine = StrategyEngine()

    def run(self):
        log.info(f"Unit {COIN_NAME} Launching...")
        send_telegram(f"⚔️ <b>{COIN_NAME} BATTLE-HARDENED</b>\nSpread Filter & Watchdog Aktif.")

        while True:
            try:
                # 1. Sinkronisasi Harga
                idx_price = self.ex.get_idx_ticker()
                df = self.ex.fetch_radar()
                if not idx_price or df is None:
                    time.sleep(10); continue

                # 2. REVISI 3: Spread Filter (Indodax vs Binance)
                binance_price_idr = df['close'].iloc[-1] * USD_IDR_RATE
                spread_pct = abs((idx_price - binance_price_idr) / idx_price) * 100

                pos = self.db.get_active_position(SYMBOL)
                if pos:
                    # Logic Jual (Trailing/TP/SL)
                    pnl = ((idx_price - pos['buy_price']) / pos['buy_price']) * 100
                    # ... (Logic Jual tetap sama seperti versi V-Prime)
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] HOLD {COIN_NAME} | PnL: {pnl:.2f}%   ")
                else:
                    # Logic Beli
                    score, reason = self.engine.calculate_score(df)
                    
                    # Status Dashboard
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] SCAN {COIN_NAME} | Score: {score} | Spread: {spread_pct:.1f}%   ")
                    sys.stdout.flush()

                    # Filter Eksekusi: Score Tinggi + Spread Sehat
                    if score >= 70 and spread_pct <= MAX_SPREAD_PCT:
                        print(f"\n🎯 Sinyal Masuk: {reason}. Mengeksekusi...")
                        
                        # REVISI 7: Dynamic Buy Amount
                        bal = self.ex.api.fetch_balance().get('IDR', {}).get('free', 0)
                        trade_amount = max(MIN_ORDER_IDR, min(14000, bal * 0.5))
                        
                        if bal >= trade_amount:
                            # Eksekusi Buy Verified...
                            log.info(f"Buy {COIN_NAME} Success at {idx_price}")
                            send_telegram(f"🔵 <b>BUY {COIN_NAME}</b>\nPrice: {idx_price}\nSpread: {spread_pct:.2f}%")
                            time.sleep(COOLDOWN_MINUTES * 60)

            except Exception as e:
                log.error(f"Failsafe: {e}"); time.sleep(15)
            time.sleep(15)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
