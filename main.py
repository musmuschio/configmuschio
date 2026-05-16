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
from datetime import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
load_dotenv()

# ==========================================
# [1] KONFIGURASI PRODUKSI (UNIT BTC - SNIPER)
# ==========================================
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTC/IDR"
SYMBOL_RADAR = "BTCUSDT"
COIN_NAME = "BTC"

# --- IDENTITAS UNIK BTC (BEDAKAN DENGAN PEPE) ---
PID_FILE = "btc_bot.pid"
DB_NAME = "btc_state.db"
DB_BACKUP = "btc_state_backup.db"
LOG_FILE = "btc_trading.log"
KILL_SWITCH_FILE = "stop_btc.flag"

# --- PARAMETER EKSEKUSI ---
MIN_ORDER_IDR = 10000
TRADING_FEE_PCT = 0.3      
TAKE_PROFIT_1_PCT = 2.0    
TAKE_PROFIT_2_PCT = 5.0    
STOP_LOSS_PCT = 1.0        
TRAILING_STOP_PCT = 0.5    
MAX_DAILY_LOSS_IDR = 25000 
COOLDOWN_MINUTES = 15      

# ==========================================
# [2] SINGLE INSTANCE PROTECTION (PID LOCK)
# ==========================================
def check_single_instance():
    """Mencegah dua bot BTC berjalan bersamaan"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read())
            os.kill(pid, 0)
            print(f"❌ ERROR: Bot BTC sudah jalan (PID: {pid}). Matikan dulu!")
            sys.exit(1)
        except (ProcessLookupError, ValueError, OSError):
            os.remove(PID_FILE)
            
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

check_single_instance()

# ==========================================
# [3] LOGGING & ASYNC TELEGRAM
# ==========================================
def setup_logger():
    logger = logging.getLogger("BtcBot")
    if logger.handlers: return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
    
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    
    logger.addHandler(ch)
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
# [4] DATABASE SQLITE (WAL MODE)
# ==========================================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("PRAGMA journal_mode=WAL;") 
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS positions 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, buy_price REAL, 
            amount_koin REAL, amount_idr REAL, highest_price REAL, status TEXT, buy_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS trade_history 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT, price REAL, 
            amount_idr REAL, pnl_pct REAL, pnl_idr REAL, reason TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()

    def backup(self):
        try: shutil.copy(DB_NAME, DB_BACKUP)
        except Exception: pass

    def save_position(self, symbol, buy_price, amount_koin, amount_idr):
        self.cursor.execute("INSERT INTO positions (symbol, buy_price, amount_koin, amount_idr, highest_price, status) VALUES (?, ?, ?, ?, ?, 'OPEN')",
            (symbol, buy_price, amount_koin, amount_idr, buy_price))
        self.conn.commit()
        self.backup()

    def get_active_position(self, symbol):
        self.cursor.execute("SELECT * FROM positions WHERE symbol = ? AND status = 'OPEN'", (symbol,))
        row = self.cursor.fetchone()
        if row: return {"id": row[0], "symbol": row[1], "buy_price": row[2], "amount_koin": row[3], "amount_idr": row[4], "highest_price": row[5]}
        return None

    def update_highest_price(self, pos_id, new_high):
        self.cursor.execute("UPDATE positions SET highest_price = ? WHERE id = ?", (new_high, pos_id))
        self.conn.commit()

    def close_position(self, pos_id, symbol, sell_price, amount_idr, pnl_pct, pnl_idr, reason):
        self.cursor.execute("UPDATE positions SET status = 'CLOSED' WHERE id = ?", (pos_id,))
        self.cursor.execute("INSERT INTO trade_history (symbol, side, price, amount_idr, pnl_pct, pnl_idr, reason) VALUES (?, 'SELL', ?, ?, ?, ?, ?)",
            (symbol, sell_price, amount_idr, pnl_pct, pnl_idr, reason))
        self.conn.commit()
        self.backup()

    def get_daily_loss_idr(self):
        today = datetime.now().strftime('%Y-%m-%d')
        self.cursor.execute("SELECT SUM(pnl_idr) FROM trade_history WHERE side = 'SELL' AND pnl_idr < 0 AND date(timestamp) = ?", (today,))
        total = self.cursor.fetchone()[0]
        return abs(total) if total else 0.0

# ==========================================
# [5] EXCHANGE & RADAR
# ==========================================
class ExchangeManager:
    def __init__(self):
        self.api = ccxt.indodax({'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True})

    def fetch_market_data(self, symbol):
        try:
            url = "https://data-api.binance.vision/api/v3/klines"
            res = requests.get(url, params={"symbol": symbol, "interval": "1m", "limit": 100}, timeout=5).json()
            df = pd.DataFrame(res, columns=['t', 'open', 'high', 'low', 'close', 'v', 'ct', 'qv', 'tr', 'tb', 'tq', 'ig'])
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            return df
        except Exception: return None

    def get_indodax_ticker(self, symbol):
        try: return self.api.fetch_ticker(symbol)['last']
        except Exception: return None

    def get_balance(self, asset):
        try:
            bal = self.api.fetch_balance()
            return float(bal.get(asset, {}).get('free', 0))
        except Exception: return 0.0

    def execute_buy_verified(self, symbol, amount_idr):
        coin = symbol.split('/')[0]
        bal_before = self.get_balance(coin)
        order = self.api.private_post_trade({'pair': symbol.replace('/', '_').lower(), 'type': 'buy', 'idr': int(amount_idr)})
        if order and str(order.get('success')) == '1':
            time.sleep(3)
            real_received = self.get_balance(coin) - bal_before
            if real_received > 0:
                return {"success": True, "koin_diterima": real_received, "real_price": amount_idr / real_received}
        return {"success": False}

    def execute_sell_verified(self, symbol, amount_koin):
        actual_bal = self.get_balance(symbol.split('/')[0])
        sell_amount = min(amount_koin, actual_bal)
        if sell_amount <= 0: return False
        order = self.api.private_post_trade({'pair': symbol.replace('/', '_').lower(), 'type': 'sell', symbol.split('/')[0].lower(): sell_amount})
        return True if order and str(order.get('success')) == '1' else False

# ==========================================
# [6] STRATEGY & RISK ENGINE
# ==========================================
class StrategyEngine:
    @staticmethod
    def calculate_score(df):
        if df is None or len(df) < 20: return 0
        close = df['close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        
        curr_rsi = rsi.iloc[-2] # Gunakan candle tutup
        score = 0
        if curr_rsi < 30: score += 40
        if close.iloc[-2] <= close.rolling(20).mean().iloc[-2]: score += 30
        return score

# ==========================================
# [7] CORE LOOP
# ==========================================
class TradingBot:
    def __init__(self):
        self.db = Database()
        self.ex = ExchangeManager()
        self.engine = StrategyEngine()

    def run(self):
        log.info(f"Unit BTC Sniper Aktif. PID: {os.getpid()}")
        send_telegram(f"🎯 <b>BTC SNIPER DEPLOYED</b>\nPair: {SYMBOL}\nProtection: Fully Hardened")

        while True:
            try:
                if os.path.exists(KILL_SWITCH_FILE):
                    time.sleep(15); continue

                idx_price = self.ex.get_indodax_ticker(SYMBOL)
                pos = self.db.get_active_position(SYMBOL)
                
                if pos:
                    gross = ((idx_price - pos['buy_price']) / pos['buy_price']) * 100
                    net = gross - (TRADING_FEE_PCT * 2)
                    if idx_price > pos['highest_price']: self.db.update_highest_price(pos['id'], idx_price)
                    
                    reason = None
                    drop = ((pos['highest_price'] - idx_price) / pos['highest_price']) * 100
                    
                    if net >= TAKE_PROFIT_2_PCT: reason = "HARD EXIT"
                    elif net >= TAKE_PROFIT_1_PCT and drop >= TRAILING_STOP_PCT: reason = "TRAILING"
                    elif net <= -STOP_LOSS_PCT: reason = "STOP LOSS"

                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] BTC HOLD | PnL: {net:.2f}%   ")
                    sys.stdout.flush()

                    if reason:
                        if self.ex.execute_sell_verified(SYMBOL, pos['amount_koin']):
                            self.db.close_position(pos['id'], SYMBOL, idx_price, pos['amount_idr'], net, (pos['amount_idr']*net/100), reason)
                            send_telegram(f"🟢 <b>BTC SOLD ({reason})</b>\nPnL: {net:.2f}%")
                            time.sleep(COOLDOWN_MINUTES * 60)
                else:
                    df = self.ex.fetch_market_data(SYMBOL_RADAR)
                    score = self.engine.calculate_score(df)
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] BTC SCAN | Score: {score}/100   ")
                    sys.stdout.flush()

                    if score >= 70:
                        bal = self.ex.get_balance('IDR')
                        if bal >= MIN_ORDER_IDR:
                            res = self.ex.execute_buy_verified(SYMBOL, 14000)
                            if res['success']:
                                self.db.save_position(SYMBOL, res['real_price'], res['koin_diterima'], 14000)
                                send_telegram(f"🔵 <b>BTC BOUGHT</b>\nPrice: Rp{res['real_price']:,.0f}")
                                time.sleep(COOLDOWN_MINUTES * 60)

            except Exception as e:
                log.error(f"Error: {e}"); time.sleep(10)
            time.sleep(15)

if __name__ == "__main__":
    try:
        bot = TradingBot()
        bot.run()
    except KeyboardInterrupt:
        if os.path.exists(PID_FILE): os.remove(PID_FILE)
        sys.exit(0)
        
