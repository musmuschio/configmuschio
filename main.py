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
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
load_dotenv()

# ==========================================
# [1] KONFIGURASI PRODUKSI (REAL TRADING)
# ==========================================
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTC/IDR"
SYMBOL_RADAR = "BTCUSDT"
COIN_NAME = SYMBOL.split('/')[0]

MIN_ORDER_IDR = 10000
TRADING_FEE_PCT = 0.3      
TAKE_PROFIT_1_PCT = 2.0    # Trailing aktif setelah ini
TAKE_PROFIT_2_PCT = 5.0    # Hard Exit
STOP_LOSS_PCT = 1.0        
TRAILING_STOP_PCT = 0.5    
MAX_DAILY_LOSS_IDR = 25000 # Stop trading jika loss harian > Rp 25.000
COOLDOWN_MINUTES = 15      

DB_NAME = "trading_state.db"
DB_BACKUP = "trading_state_backup.db"
LOG_FILE = "bot_trading.log"
KILL_SWITCH_FILE = "stop.flag"

# ==========================================
# [2] LOGGING & ASYNC TELEGRAM
# ==========================================
def setup_logger():
    logger = logging.getLogger("TradeBot")
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
    """Non-blocking Telegram sender (Fire and Forget)"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    
    def _send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=5)
        except Exception: pass
        
    threading.Thread(target=_send, daemon=True).start()

# ==========================================
# [3] DATABASE INTEGRITY & WAL MODE
# ==========================================
class Database:
    def __init__(self):
        self._check_integrity()
        self.conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("PRAGMA journal_mode=WAL;") 
        self._create_tables()

    def _check_integrity(self):
        if not os.path.exists(DB_NAME): return
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            res = cursor.fetchone()
            conn.close()
            if res[0] != "ok": raise Exception("Database Corrupt")
        except Exception as e:
            log.error(f"DB Integrity Error: {e}. Recreating...")
            if os.path.exists(DB_BACKUP):
                shutil.copy(DB_BACKUP, DB_NAME)
                log.info("Database dipulihkan dari backup.")

    def _create_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS positions 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, buy_price REAL, 
            amount_koin REAL, amount_idr REAL, highest_price REAL, status TEXT, buy_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS trade_history 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT, price REAL, 
            amount_idr REAL, pnl_pct REAL, pnl_idr REAL, reason TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()

    def backup(self):
        try:
            shutil.copy(DB_NAME, DB_BACKUP)
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
        
    def force_close_ghost(self, pos_id):
        self.cursor.execute("UPDATE positions SET status = 'GHOST_CLOSED' WHERE id = ?", (pos_id,))
        self.conn.commit()

    def get_daily_loss_idr(self):
        today = datetime.now().strftime('%Y-%m-%d')
        self.cursor.execute("SELECT SUM(pnl_idr) FROM trade_history WHERE side = 'SELL' AND pnl_idr < 0 AND date(timestamp) = ?", (today,))
        total = self.cursor.fetchone()[0]
        return abs(total) if total else 0.0

# ==========================================
# [4] EXCHANGE MANAGER & API CACHE
# ==========================================
class ExchangeManager:
    def __init__(self):
        if not API_KEY or not SECRET_KEY:
            log.error("API_KEY KOSONG! Sistem Real Trading dihentikan.")
            sys.exit(1)
        self.api = ccxt.indodax({'apiKey': API_KEY, 'secret': SECRET_KEY, 'enableRateLimit': True})
        self.cache = {}

    def safe_api_call(self, func, *args, retries=3, **kwargs):
        for attempt in range(retries):
            try: return func(*args, **kwargs)
            except Exception as e:
                time.sleep(2 ** attempt)
        return None

    def fetch_market_data(self, symbol, interval='1m', limit=100):
        cache_key = f"klines_{symbol}_{interval}"
        if cache_key in self.cache and time.time() - self.cache[cache_key]['time'] < 5:
            return self.cache[cache_key]['data']
            
        try:
            url = "https://data-api.binance.vision/api/v3/klines"
            res = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=5).json()
            df = pd.DataFrame(res, columns=['t', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qv', 'tr', 'tb', 'tq', 'ig'])
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['volume'] = df['volume'].astype(float)
            self.cache[cache_key] = {'time': time.time(), 'data': df}
            return df
        except Exception: return None

    def get_indodax_ticker(self, symbol):
        cache_key = f"ticker_{symbol}"
        if cache_key in self.cache and time.time() - self.cache[cache_key]['time'] < 3:
            return self.cache[cache_key]['data']
        ticker = self.safe_api_call(self.api.fetch_ticker, symbol)
        if ticker:
            self.cache[cache_key] = {'time': time.time(), 'data': ticker['last']}
            return ticker['last']
        return None

    def get_balance(self, asset):
        bal = self.safe_api_call(self.api.fetch_balance)
        return float(bal.get(asset, {}).get('free', 0)) if bal else 0.0

    def calculate_position_size(self, balance_idr):
        risk_amount = balance_idr * 0.02
        return max(risk_amount, MIN_ORDER_IDR) if balance_idr >= MIN_ORDER_IDR else 0

    def execute_buy_verified(self, symbol, amount_idr):
        """REAL ORDER VERIFICATION & REAL FILL PRICE"""
        coin = symbol.split('/')[0]
        bal_before = self.get_balance(coin)
        
        log.info(f"🚀 EKSEKUSI NYATA: Membeli {symbol} senilai Rp{amount_idr:,.0f}")
        order = self.safe_api_call(self.api.private_post_trade, {'pair': symbol.replace('/', '_').lower(), 'type': 'buy', 'idr': int(amount_idr)})
        
        if order and str(order.get('success')) == '1':
            time.sleep(3) # Tunggu settlement
            bal_after = self.get_balance(coin)
            real_received = bal_after - bal_before
            
            if real_received > 0:
                real_price = amount_idr / real_received # Harga fill nyata
                return {"success": True, "koin_diterima": real_received, "real_price": real_price}
        return {"success": False}

    def execute_sell_verified(self, symbol, amount_koin):
        # Sell Verification & Dust Prevention
        actual_bal = self.get_balance(symbol.split('/')[0])
        sell_amount = min(amount_koin, actual_bal) # Cegah error insufficient fund
        
        if sell_amount <= 0: return False
        
        order = self.safe_api_call(self.api.private_post_trade, {'pair': symbol.replace('/', '_').lower(), 'type': 'sell', symbol.split('/')[0].lower(): sell_amount})
        return True if order and str(order.get('success')) == '1' else False

# ==========================================
# [5] UNIFIED SCORING & VOLATILITY ENGINE
# ==========================================
class StrategyEngine:
    @staticmethod
    def calculate_score(df_1m, df_15m):
        """Unified Score Engine + ATR Volatility Filter"""
        if df_1m is None or df_15m is None or len(df_1m) < 20: return 0, "No Data"

        # Hitung Indikator 1m
        delta = df_1m['close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        macd = df_1m['close'].ewm(span=12, adjust=False).mean() - df_1m['close'].ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - signal
        
        bb_mid = df_1m['close'].rolling(20).mean()
        bb_std = df_1m['close'].rolling(20).std()
        bb_lower = bb_mid - (2 * bb_std)
        
        # Volatility (ATR) Filter
        high_low = df_1m['high'] - df_1m['low']
        atr = high_low.rolling(14).mean().iloc[-1]
        close = df_1m['close'].iloc[-1]
        if (atr / close) * 100 > 3.0: return 0, "Pasar Terlalu Liar (ATR > 3%)"

        # Hitung EMA 15m (Trend Filter)
        ema_50 = df_15m['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        ema_200 = df_15m['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        if ema_50 < ema_200: return 0, "Downtrend 15m Parah"

        # Scoring
        score = 0
        curr_rsi = rsi.iloc[-1]
        if curr_rsi < 30: score += 30
        if macd_hist.iloc[-1] > 0: score += 25
        if close <= bb_lower.iloc[-1]: score += 20
        if df_1m['volume'].iloc[-1] > df_1m['volume'].rolling(20).mean().iloc[-1]: score += 15
        if ema_50 >= ema_200: score += 10

        detail = f"RSI:{curr_rsi:.1f} | MACD:{macd_hist.iloc[-1]:.1f}"
        return score, detail

# ==========================================
# [6] KANTOR PUSAT OPERASIONAL (WATCHDOG & RECONCILIATION)
# ==========================================
class TradingBot:
    def __init__(self):
        self.db = Database()
        self.ex = ExchangeManager()
        self.engine = StrategyEngine()
        self.last_loop_time = time.time()
        self._startup_safety_check()

    def _startup_safety_check(self):
        """Startup Safety & Position Reconciliation"""
        log.info("Sistem Inisialisasi... Melakukan Safety Check & Rekonsiliasi.")
        time.sleep(2)
        
        pos = self.db.get_active_position(SYMBOL)
        if pos:
            actual_koin = self.ex.get_balance(COIN_NAME)
            # Jika selisih koin di exchange dan DB lebih dari 5% (toleransi fee), berarti user jual manual / ghost pos
            if actual_koin < (pos['amount_koin'] * 0.95):
                log.error("🚨 GHOST POSITION TERDETEKSI! Koin tidak ada di dompet Indodax.")
                send_telegram("⚠️ <b>GHOST POSITION CLOSED</b>\nBot mendeteksi posisi terbuka di DB tapi saldo kosong.")
                self.db.force_close_ghost(pos['id'])
            else:
                log.info("✅ Rekonsiliasi Sukses: Posisi lama dilanjutkan.")
                send_telegram("🔄 <b>RECOVERY MODE</b>\nMelanjutkan monitoring posisi aktif sebelumnya.")
        log.info("Sistem Siap Tempur.")

    def run(self):
        send_telegram(f"🚀 <b>BOT STARTUP</b>\nPair: {SYMBOL}\nMode: Production V-Prime")

        while True:
            try:
                # 1. KILL SWITCH CHECK
                if os.path.exists(KILL_SWITCH_FILE):
                    log.warning("KILL SWITCH AKTIF. Bot menahan semua eksekusi.")
                    time.sleep(15)
                    continue

                # 2. WATCHDOG SYSTEM
                if time.time() - self.last_loop_time > 120:
                    log.error("⚠️ Watchdog Timeout! Memulihkan koneksi internal...")
                    self.db.conn.close()
                    self.db = Database() # Reconnect
                self.last_loop_time = time.time()

                # 3. DAILY LOSS LIMIT (NOMINAL)
                daily_loss_idr = self.db.get_daily_loss_idr()
                if daily_loss_idr >= MAX_DAILY_LOSS_IDR:
                    log.error(f"🛑 MAX DAILY LOSS TERCAPAI (Rp{daily_loss_idr:,.0f}).")
                    send_telegram(f"🛑 <b>TRADING HALTED</b>\nLoss harian mencapai Rp{daily_loss_idr:,.0f}.")
                    time.sleep(3600) # Tidur 1 jam
                    continue

                # 4. MARKET DATA FETCH
                idx_price = self.ex.get_indodax_ticker(SYMBOL)
                if not idx_price:
                    time.sleep(3)
                    continue

                pos = self.db.get_active_position(SYMBOL)
                
                # 5. POSITION MANAGEMENT (ADVANCED TRAILING)
                if pos:
                    gross_pct = ((idx_price - pos['buy_price']) / pos['buy_price']) * 100
                    net_pct = gross_pct - (TRADING_FEE_PCT * 2)
                    net_idr = (pos['amount_idr'] * net_pct) / 100

                    if idx_price > pos['highest_price']:
                        self.db.update_highest_price(pos['id'], idx_price)
                    
                    reason = None
                    drop_from_high_pct = ((pos['highest_price'] - idx_price) / pos['highest_price']) * 100

                    if net_pct >= TAKE_PROFIT_2_PCT:
                        reason = "HARD EXIT (TP2)"
                    elif net_pct >= TAKE_PROFIT_1_PCT and drop_from_high_pct >= TRAILING_STOP_PCT:
                        reason = "TRAILING STOP"
                    elif net_pct <= -STOP_LOSS_PCT:
                        reason = "STOP LOSS"

                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] HOLDING | {SYMBOL}: Rp{idx_price:,.0f} | Net PnL: {net_pct:.2f}% (Rp{net_idr:,.0f})      ")
                    sys.stdout.flush()

                    if reason:
                        print("")
                        if self.ex.execute_sell_verified(SYMBOL, pos['amount_koin']):
                            self.db.close_position(pos['id'], SYMBOL, idx_price, pos['amount_idr'], net_pct, net_idr, reason)
                            msg = f"🟢 <b>SELL {reason}</b>\nPair: {SYMBOL}\nNet PnL: {net_pct:.2f}% (Rp{net_idr:,.0f})"
                            send_telegram(msg)
                            time.sleep(COOLDOWN_MINUTES * 60)

                # 6. SCANNING ENTRY MODE
                else:
                    df_1m = self.ex.fetch_market_data(SYMBOL_RADAR, '1m')
                    df_15m = self.ex.fetch_market_data(SYMBOL_RADAR, '15m')
                    
                    score, detail = self.engine.calculate_score(df_1m, df_15m)
                    
                    sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] SCAN | {SYMBOL}: Rp{idx_price:,.0f} | Score: {score}/100 | {detail}      ")
                    sys.stdout.flush()

                    if score >= 70:
                        print("") 
                        log.info(f"🎯 Sinyal Masuk! Score: {score}. Memeriksa Saldo...")
                        bal_idr = self.ex.get_balance('IDR')
                        trade_amount = self.ex.calculate_position_size(bal_idr)

                        if trade_amount >= MIN_ORDER_IDR:
                            res = self.ex.execute_buy_verified(SYMBOL, trade_amount)
                            if res['success']:
                                real_buy_price = res['real_price']
                                self.db.save_position(SYMBOL, real_buy_price, res['koin_diterima'], trade_amount)
                                msg = f"🔵 <b>BUY SUCCESS</b>\nPair: {SYMBOL}\nReal Price: Rp{real_buy_price:,.0f}\nAmount: Rp{trade_amount:,.0f}"
                                send_telegram(msg)
                                time.sleep(COOLDOWN_MINUTES * 60)
                        else:
                            log.warning("Saldo Rupiah (Rp{bal_idr:,.0f}) di bawah limit Indodax.")

            except Exception as e:
                log.error(f"Failsafe Triggered: {str(e)}")
                # traceback.print_exc() # Aktifkan ini jika ingin debugging mendalam
                time.sleep(10)

            time.sleep(10) # Base Loop Interval

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
                            
