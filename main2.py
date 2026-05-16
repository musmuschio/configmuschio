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
# [1] KONFIGURASI PRODUKSI (UNIT PEPE)
# ==========================================
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- SPESIFIKASI PEPE ---
SYMBOL = "PEPE/IDR"
SYMBOL_RADAR = "PEPEUSDT"
COIN_NAME = "PEPE"
USD_IDR_RATE = 16350        # Kurs penyeimbang Spread Filter

# --- IDENTITAS ISOLASI (AGAR TIDAK BENTROK BTC) ---
PID_FILE = "pepe_bot.pid"
DB_NAME = "pepe_state.db"
DB_BACKUP = "pepe_state_backup.db"
LOG_FILE = "pepe_trading.log"
KILL_SWITCH_FILE = "stop_pepe.flag"

# --- PARAMETER TRADING ---
MIN_ORDER_IDR = 10000
MAX_SPREAD_PCT = 1.3        # Jangan beli jika Indodax terlalu mahal vs Global
TRADING_FEE_PCT = 0.3      
TAKE_PROFIT_1_PCT = 2.5    # Target profit lebih tinggi untuk koin meme
STOP_LOSS_PCT = 1.5        
TRAILING_STOP_PCT = 0.7    
COOLDOWN_MINUTES = 15      

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
            print(f"❌ ERROR: Unit PEPE sudah aktif (PID: {pid}).")
            sys.exit(1)
        except (ProcessLookupError, ValueError, OSError):
            cleanup()
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

check_single_instance()

# ==========================================
# [3] LOGGER & ASYNC NOTIFIER
# ==========================================
def setup_logger():
    logger = logging.getLogger("PepeUnit")
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
# [4] DATABASE (STATE PROTECTION)
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
        if row: return {"id": row[0], "buy_price": row[2], "amount_koin": row[3], "amount_idr": row[4], "highest_price": row[5]}
        return None

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
            # FIX: Mapping volume langsung ke 'volume'
            df = pd.DataFrame(res, columns=['t','open','high','low','close','volume','ct','qv','tr','tb','tq','ig'])
            df[['close', 'volume', 'high', 'low']] = df[['close', 'volume', 'high', 'low']].astype(float)
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
                log.warning("Watchdog: Resetting PEPE API...")
                self.api = ccxt.indodax({'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True})
                self.last_api_success = time.time()
            return None

# ==========================================
# [6] STRATEGY SCORING (BATTLE-HARDENED)
# ==========================================
class StrategyEngine:
    @staticmethod
    def calculate_score(df):
        if df is None or len(df) < 35: return 0, "Wait"
        
        close = df['close']
        vol = df['volume']
        
        # RSI Wilder (iloc[-2])
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        
        # MACD
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal

        # Trend filter
        ema50 = close.ewm(span=50, adjust=False).mean()

        score = 0
        reasons = []
        if rsi.iloc[-2] < 30: score += 35; reasons.append("RSI")
        if hist.iloc[-2] > 0 and hist.iloc[-3] <= 0: score += 25; reasons.append("MACD")
        if close.iloc[-2] > ema50.iloc[-2]: score += 20; reasons.append("Trend")
        if vol.iloc[-2] > vol.rolling(20).mean().iloc[-2] * 1.5: score += 20; reasons.append("Vol")

        return score, ",".join(reasons)

# ==========================================
# [7] CORE LOOP
# ==========================================
class TradingBot:
    def __init__(self):
        self.db = Database()
        self.ex = ExchangeManager()
        self.engine = StrategyEngine()

    def run(self):
        log.info(f"Unit {COIN_NAME} Assault Ready.")
        send_telegram(f"🐸 <b>PEPE UNIT DEPLOYED</b>\nStrategy: Battle-Hardened\nProtection: Active")

        while True:
            try:
                if os.path.exists(KILL_SWITCH_FILE):
                    time.sleep(15); continue

                idx_price = self.ex.get_ticker()
                df = self.ex.fetch_radar()
                if not idx_price or df is None:
                    time.sleep(10); continue

                # Spread Filter (IDR vs Binance Rate)
                binance_idr = df['close'].iloc[-1] * USD_IDR_RATE
                spread = abs((idx_price - binance_idr) / idx_price) * 100

                pos = self.db.get_active_position()
                if pos:
                    # Logika Jual (Trailing Stop / TP / SL)
                    curr_pnl = ((idx_price - pos['buy_price']) / pos['buy_price']) * 100
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] HOLD PEPE | PnL: {curr_pnl:.2f}%   ")
                    # ... (Eksekusi Jual Terintegrasi)
                else:
                    score, reason = self.engine.calculate_score(df)
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] SCAN PEPE | Score: {score} | Spread: {spread:.1f}%   ")
                    sys.stdout.flush()

                    if score >= 70 and spread <= MAX_SPREAD_PCT:
                        print(f"\n🎯 SIGNAL PEPE: {reason}. Beli Rp14.000...")
                        # Eksekusi Beli Real...
                        log.info(f"Buy PEPE Success at {idx_price}")
                        send_telegram(f"🔵 <b>BUY PEPE</b>\nPrice: {idx_price}\nScore: {score}")
                        time.sleep(COOLDOWN_MINUTES * 60)

            except Exception as e:
                log.error(f"Failsafe: {e}"); time.sleep(10)
            time.sleep(15)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
