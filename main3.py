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
# [1] KONFIGURASI "SADIS" MODE (UNIT GIGA)
# ==========================================
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "GIGA/IDR"
SYMBOL_RADAR = "GIGAUSDT"
COIN_NAME = "GIGA"
USD_IDR_RATE = 16350        

# Identitas Isolasi (Ganti agar tidak bentrok dengan BTC)
PID_FILE = "alt_bot.pid"
DB_NAME = "alt_state.db"
DB_BACKUP = "alt_state_backup.db"
LOG_FILE = "alt_trading.log"
KILL_SWITCH_FILE = "stop_alt.flag"

# Parameter Trading Agresif
MIN_ORDER_IDR = 10000
MAX_SPREAD_PCT = 2.5        # Longgarkan spread karena koin liar
TRADING_FEE_PCT = 0.3      
TAKE_PROFIT_1_PCT = 5.0     # Target awal 5%
TAKE_PROFIT_2_PCT = 15.0    # Hard Exit 15%
STOP_LOSS_PCT = 3.0         # Stop Loss lebih lebar (koin meme sering gocek)
TRAILING_STOP_PCT = 1.0    
COOLDOWN_MINUTES = 5        # Istirahat singkat saja

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
            print(f"❌ ERROR: Unit GIGA sudah aktif (PID: {pid}).")
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
    logger = logging.getLogger("GigaAssault")
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

    def get_balance(self, asset):
        try:
            bal = self.api.fetch_balance()
            return float(bal.get(asset, {}).get('free', 0))
        except Exception: return 0.0

# ==========================================
# [6] AGGRESSIVE SCORING ENGINE
# ==========================================
class StrategyEngine:
    @staticmethod
    def calculate_score(df):
        if df is None or len(df) < 20: return 0, "Wait"
        close = df['close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        
        curr_rsi = rsi.iloc[-2]
        score = 0
        if curr_rsi < 45: score += 40 # Threshold RSI dinaikkan (lebih gampang buy)
        if close.iloc[-2] <= close.rolling(20).mean().iloc[-2]: score += 30
        
        return score, f"RSI:{curr_rsi:.1f}"

# ==========================================
# [7] CORE OPERATIONAL (SADIS MODE)
# ==========================================
class TradingBot:
    def __init__(self):
        self.db = Database()
        self.ex = ExchangeManager()
        self.engine = StrategyEngine()

    def run(self):
        log.info(f"Unit {COIN_NAME} Assault: HI-AGGRESSIVE MODE.")
        send_telegram(f"⚔️ <b>{COIN_NAME} ASSAULT UNIT ACTIVE</b>\nMode: Sadis (Aggressive)")

        while True:
            try:
                if os.path.exists(KILL_SWITCH_FILE):
                    time.sleep(15); continue

                idx_price = self.ex.get_ticker()
                df = self.ex.fetch_radar()
                if not idx_price or df is None:
                    time.sleep(10); continue

                binance_idr = df['close'].iloc[-1] * USD_ID_RATE
                spread = abs((idx_price - binance_idr) / idx_price) * 100

                pos = self.db.get_active_position()
                if pos:
                    pnl = ((idx_price - pos['buy_price']) / pos['buy_price']) * 100
                    if idx_price > pos['highest_price']:
                        self.db.update_highest_price(pos['id'], idx_price)
                    
                    reason = None
                    drop = ((pos['highest_price'] - idx_price) / pos['highest_price']) * 100
                    
                    if pnl >= TAKE_PROFIT_2_PCT: reason = "HARD EXIT"
                    elif pnl >= TAKE_PROFIT_1_PCT and drop >= TRAILING_STOP_PCT: reason = "TRAILING"
                    elif pnl <= -STOP_LOSS_PCT: reason = "STOP LOSS"

                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] HOLD {COIN_NAME} | PnL: {pnl:.2f}%   ")
                    sys.stdout.flush()

                    if reason:
                        # Logic Jual (Real)...
                        print(f"\n🟢 JUAL {COIN_NAME}: {reason}")
                        time.sleep(COOLDOWN_MINUTES * 60)
                else:
                    score, detail = self.engine.calculate_score(df)
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] SCAN {COIN_NAME} | Score: {score}/100 | {detail}   ")
                    sys.stdout.flush()

                    # --- MODE AGRESIF: THRESHOLD 55 ---
                    if score >= 55 and spread <= MAX_SPREAD_PCT:
                        print(f"\n🔥 {COIN_NAME} MENEMBAK! Score: {score}")
                        bal = self.ex.get_balance('IDR')
                        # SIKAT SEMUA SALDO (Sisakan sedikit fee)
                        trade_amount = max(MIN_ORDER_IDR, bal - 500)
                        
                        if bal >= MIN_ORDER_IDR:
                            # Eksekusi Beli Real Disini...
                            self.db.save_position(idx_price, (trade_amount/idx_price), trade_amount)
                            send_telegram(f"🔵 <b>{COIN_NAME} BOUGHT</b>\nPrice: {idx_price}")
                            time.sleep(COOLDOWN_MINUTES * 60)

            except Exception as e:
                log.error(f"Failsafe: {e}"); time.sleep(10)
            time.sleep(15)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
