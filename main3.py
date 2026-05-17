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
import atexit
from datetime import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
load_dotenv()

# ==========================================
# [1] KONFIGURASI "THE MAD DOG" (UNIT WIF)
# ==========================================
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- SPESIFIKASI WIF (SADIS & LIAR) ---
SYMBOL = "WIF/IDR"         # Indodax
SYMBOL_RADAR = "WIFUSDT"   # Binance Radar (Pasti Ada)
COIN_NAME = "WIF"
USD_IDR_RATE = 16350        

# --- IDENTITAS ISOLASI ---
PID_FILE = "wif_bot.pid"
DB_NAME = "wif_state.db"
LOG_FILE = "wif_trading.log"
KILL_SWITCH_FILE = "stop_wif.flag"

# --- PARAMETER HYPER-AGGRESSIVE ---
MIN_ORDER_IDR = 10000
MAX_SPREAD_PCT = 2.0        # Toleransi spread sedikit lebih lebar
TAKE_PROFIT_1_PCT = 4.0     # Mulai trailing di 4%
TAKE_PROFIT_2_PCT = 12.0    # Hard Exit di 12%
STOP_LOSS_PCT = 3.5         # SL lebih lebar agar tidak kena "noise"
TRAILING_STOP_PCT = 1.0    
COOLDOWN_MINUTES = 3        # Istirahat cuma 3 menit (Gass terus!)

# ==========================================
# [2] PID & AUTO-CLEANUP
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
            os.kill(pid, 0)
            print(f"❌ ERROR: Unit WIF sudah aktif (PID: {pid}).")
            sys.exit(1)
        except (ProcessLookupError, ValueError, OSError):
            cleanup()
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

check_single_instance()

# ==========================================
# [3] LOGGER & NOTIFIER
# ==========================================
def setup_logger():
    logger = logging.getLogger("WifUnit")
    if logger.handlers: return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=2)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger

log = setup_logger()

def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    def _send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
        except Exception: pass
    threading.Thread(target=_send, daemon=True).start()

# ==========================================
# [4] DATABASE
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

    def save_position(self, buy_price, amount_koin, amount_idr):
        self.cursor.execute("INSERT INTO positions (symbol, buy_price, amount_koin, amount_idr, highest_price, status) VALUES (?, ?, ?, ?, ?, 'OPEN')",
            (SYMBOL, buy_price, amount_koin, amount_idr, buy_price))
        self.conn.commit()

    def get_active_position(self):
        self.cursor.execute("SELECT * FROM positions WHERE symbol = ? AND status = 'OPEN'", (SYMBOL,))
        row = self.cursor.fetchone()
        return {"id": row[0], "buy_price": row[2], "amount_koin": row[3], "amount_idr": row[4], "highest_price": row[5]} if row else None

# ==========================================
# [5] EXCHANGE & WATCHDOG
# ==========================================
class ExchangeManager:
    def __init__(self):
        self.api = ccxt.indodax({'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True})
        self.last_api_success = time.time()

    def fetch_radar(self):
        try:
            url = "https://data-api.binance.vision/api/v3/klines"
            res = requests.get(url, params={"symbol": SYMBOL_RADAR, "interval": "1m", "limit": 100}, timeout=5).json()
            if not res or len(res) == 0: return None
            df = pd.DataFrame(res, columns=['t','open','high','low','close','volume','ct','qv','tr','tb','tq','ig'])
            df[['close', 'volume']] = df[['close', 'volume']].astype(float)
            self.last_api_success = time.time()
            return df
        except Exception: return None

    def get_ticker(self):
        try:
            t = self.api.fetch_ticker(SYMBOL)
            self.last_api_success = time.time()
            return t['last']
        except Exception:
            if time.time() - self.last_api_success > 120:
                self.api = ccxt.indodax({'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True})
            return None

# ==========================================
# [6] MAD DOG STRATEGY (SKOR AGRESIF)
# ==========================================
class StrategyEngine:
    @staticmethod
    def calculate_score(df):
        # --- ANTI CRASH FILTER ---
        if df is None or df.empty or len(df) < 20: return 0, "Wait"
        
        close = df['close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        
        # Agresif: RSI di bawah 45 sudah dianggap sinyal beli
        curr_rsi = rsi.iloc[-2]
        score = 0
        if curr_rsi < 45: score += 40
        if close.iloc[-2] <= close.rolling(20).mean().iloc[-2]: score += 30
        
        return score, f"RSI:{curr_rsi:.1f}"

# ==========================================
# [7] CORE OPERATIONAL
# ==========================================
class TradingBot:
    def __init__(self):
        self.db = Database()
        self.ex = ExchangeManager()
        self.engine = StrategyEngine()

    def run(self):
        log.info(f"Unit WIF 'Mad Dog' Launched. PID: {os.getpid()}")
        send_telegram(f"🐕 <b>WIF UNIT DEPLOYED</b>\nMode: Hyper-Aggressive")

        while True:
            try:
                if os.path.exists(KILL_SWITCH_FILE):
                    time.sleep(15); continue

                idx_price = self.ex.get_ticker()
                df = self.ex.fetch_radar()
                
                # Cek apakah data radar valid
                if not idx_price or df is None or df.empty:
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] Menunggu Data Radar {SYMBOL_RADAR}...   ")
                    sys.stdout.flush()
                    time.sleep(10); continue

                binance_idr = df['close'].iloc[-1] * USD_IDR_RATE
                spread = abs((idx_price - binance_idr) / idx_price) * 100

                pos = self.db.get_active_position()
                if pos:
                    pnl = ((idx_price - pos['buy_price']) / pos['buy_price']) * 100
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] HOLD WIF | PnL: {pnl:.2f}%   ")
                    # ... (Logic jual otomatis ada di sini)
                else:
                    score, detail = self.engine.calculate_score(df)
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] SCAN WIF | Score: {score}/100 | Spread: {spread:.1f}%   ")
                    sys.stdout.flush()

                    # --- THRESHOLD AGRESIF 55 ---
                    if score >= 55 and spread <= MAX_SPREAD_PCT:
                        print(f"\n🔥 WIF DISIKAT! Score: {score}")
                        # Simulasi simpan posisi (Lengkapi dengan fungsi buy asli jika saldo siap)
                        self.db.save_position(idx_price, (14000/idx_price), 14000)
                        send_telegram(f"🔵 <b>WIF BOUGHT</b>\nPrice: {idx_price}")
                        time.sleep(COOLDOWN_MINUTES * 60)

            except Exception as e:
                log.error(f"Failsafe: {e}"); time.sleep(10)
            time.sleep(15)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
            
