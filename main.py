import os
import sys
import time
import sqlite3
import logging
import requests
import pandas as pd
import ccxt
import warnings
from datetime import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
load_dotenv()

# ==========================================
# [1] CONFIGURATION & ENVIRONMENT
# ==========================================
PAPER_TRADING = True  # Set False untuk trading pakai uang beneran

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTC/IDR"
SYMBOL_RADAR = "BTCUSDT"   # Binance Vision Radar
BUY_AMOUNT_IDR = 25000     

# Strategi & Risk Management
TAKE_PROFIT_PCT = 2.0      # Take Profit 2%
STOP_LOSS_PCT = 1.0        # Stop Loss 1%
TRAILING_STOP_PCT = 0.5    # Jarak Trailing Stop 0.5%
COOLDOWN_MINUTES = 15      # Istirahat setelah beli/jual

# Sistem
DB_NAME = "trading_state.db"
LOG_FILE = "bot_trading.log"

# ==========================================
# [2] LOGGER SYSTEM
# ==========================================
def setup_logger():
    logger = logging.getLogger("TradeBot")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)

    fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger

log = setup_logger()

# ==========================================
# [3] TELEGRAM NOTIFIER
# ==========================================
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ==========================================
# [4] SQLITE DATABASE (STATE MANAGEMENT)
# ==========================================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                buy_price REAL,
                amount_koin REAL,
                amount_idr REAL,
                highest_price REAL,
                status TEXT, 
                buy_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()

    def save_position(self, symbol, buy_price, amount_koin, amount_idr):
        self.cursor.execute(
            "INSERT INTO positions (symbol, buy_price, amount_koin, amount_idr, highest_price, status) VALUES (?, ?, ?, ?, ?, 'OPEN')",
            (symbol, buy_price, amount_koin, amount_idr, buy_price)
        )
        self.conn.commit()

    def get_active_position(self, symbol):
        self.cursor.execute("SELECT * FROM positions WHERE symbol = ? AND status = 'OPEN'", (symbol,))
        row = self.cursor.fetchone()
        if row:
            return {"id": row[0], "symbol": row[1], "buy_price": row[2], "amount_koin": row[3], "amount_idr": row[4], "highest_price": row[5]}
        return None

    def update_highest_price(self, pos_id, new_high):
        self.cursor.execute("UPDATE positions SET highest_price = ? WHERE id = ?", (new_high, pos_id))
        self.conn.commit()

    def close_position(self, pos_id):
        self.cursor.execute("UPDATE positions SET status = 'CLOSED' WHERE id = ?", (pos_id,))
        self.conn.commit()

# ==========================================
# [5] EXCHANGE & RADAR MANAGER
# ==========================================
class ExchangeManager:
    def __init__(self):
        if not PAPER_TRADING and (not API_KEY or not SECRET_KEY):
            log.error("API_KEY Kosong di mode REAL TRADING!")
            sys.exit(1)
            
        self.api = ccxt.indodax({
            'apiKey': API_KEY,
            'secret': SECRET_KEY,
            'enableRateLimit': True,
        })

    def fetch_market_data(self, symbol, interval='1m', limit=100):
        try:
            url = "https://data-api.binance.vision/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            res = requests.get(url, params=params, timeout=10).json()
            df = pd.DataFrame(res, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_vol', 'trades', 'taker_base', 'taker_quote', 'ignore'])
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            return df
        except Exception as e:
            log.warning(f"Radar Vision Error: {e}")
            return None

    def get_balance_idr(self):
        if PAPER_TRADING: return 1000000.0 
        try:
            return self.api.fetch_balance().get('IDR', {}).get('free', 0)
        except Exception as e:
            log.error(f"Gagal fetch balance: {e}")
            return 0

    def execute_buy_idr(self, symbol, amount_idr):
        if PAPER_TRADING:
            log.info(f"[PAPER] Beli {symbol} senilai Rp{amount_idr}")
            return {"success": True, "koin_diterima": amount_idr / 1000000} 
            
        try:
            res = self.api.private_post_trade({
                'pair': symbol.replace('/', '_').lower(),
                'type': 'buy',
                'idr': int(amount_idr)
            })
            if str(res.get('success')) == '1':
                koin = float(res.get('return', {}).get(f"receive_{symbol.split('/')[0].lower()}", 0))
                return {"success": True, "koin_diterima": koin}
            log.error(f"Beli ditolak: {res.get('error')}")
            return {"success": False}
        except Exception as e:
            log.error(f"API Buy Error: {e}")
            return {"success": False}

    def execute_sell_koin(self, symbol, amount_koin):
        if PAPER_TRADING:
            log.info(f"[PAPER] Jual {amount_koin} {symbol}")
            return True
            
        try:
            res = self.api.private_post_trade({
                'pair': symbol.replace('/', '_').lower(),
                'type': 'sell',
                symbol.split('/')[0].lower(): amount_koin
            })
            if str(res.get('success')) == '1':
                return True
            log.error(f"Jual ditolak: {res.get('error')}")
            return False
        except Exception as e:
            log.error(f"API Sell Error: {e}")
            return False

# ==========================================
# [6] INDICATORS & STRATEGY
# ==========================================
class Strategy:
    @staticmethod
    def calc_indicators(df):
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        df['macd'] = df['close'].ewm(span=12, adjust=False).mean() - df['close'].ewm(span=26, adjust=False).mean()
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['signal']

        # Bollinger Bands
        df['bb_mid'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_lower'] = df['bb_mid'] - (2 * df['bb_std'])
        
        # EMA
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        return df

    def check_buy_signal(self, ex: ExchangeManager):
        # Multi-timeframe: Cek Trend di 15m
        df_15m = ex.fetch_market_data(SYMBOL_RADAR, '15m')
        if df_15m is None: return False
        df_15m = self.calc_indicators(df_15m)
        curr_15m = df_15m.iloc[-1]
        
        # Jika EMA 50 di bawah 200 (Downtrend Parah), jangan beli
        if curr_15m['ema_50'] < curr_15m['ema_200']: return False

        # Eksekusi di 1m
        df_1m = ex.fetch_market_data(SYMBOL_RADAR, '1m')
        if df_1m is None: return False
        df_1m = self.calc_indicators(df_1m)
        curr_1m = df_1m.iloc[-1]

        rsi_ok = curr_1m['rsi'] < 30
        macd_ok = curr_1m['macd_hist'] > 0
        bb_ok = curr_1m['close'] <= curr_1m['bb_lower']
        vol_ok = curr_1m['volume'] > df_1m['volume'].rolling(20).mean().iloc[-1]

        return rsi_ok and macd_ok and bb_ok and vol_ok

# ==========================================
# [7] RISK MANAGEMENT
# ==========================================
class RiskManager:
    def __init__(self, db: Database, ex: ExchangeManager):
        self.db = db
        self.ex = ex

    def check_auto_sell(self, pos: dict, current_price: float):
        buy_price = pos['buy_price']
        highest = pos['highest_price']
        profit_pct = ((current_price - buy_price) / buy_price) * 100

        # Trailing High Update
        if current_price > highest:
            self.db.update_highest_price(pos['id'], current_price)
            highest = current_price

        reason = None
        if profit_pct >= TAKE_PROFIT_PCT:
            reason = "TAKE PROFIT"
        elif profit_pct <= -STOP_LOSS_PCT:
            reason = "STOP LOSS"
        elif profit_pct > 1.0 and (((highest - current_price) / highest) * 100) >= TRAILING_STOP_PCT:
            reason = "TRAILING STOP"

        if reason:
            log.warning(f"Sinyal {reason} aktif di {pos['symbol']}! Mengeksekusi Jual...")
            if self.ex.execute_sell_koin(pos['symbol'], pos['amount_koin']):
                self.db.close_position(pos['id'])
                msg = f"🟢 <b>SELL SUCCESS ({reason})</b>\nPair: {pos['symbol']}\nPrice: {current_price:,.0f}\nPnL: {profit_pct:.2f}%"
                send_telegram(msg)
                log.info(f"Transaksi Jual Selesai. PnL: {profit_pct:.2f}%")
                time.sleep(COOLDOWN_MINUTES * 60)

# ==========================================
# [8] THE CORE LOOP
# ==========================================
class TradingBot:
    def __init__(self):
        self.db = Database()
        self.ex = ExchangeManager()
        self.strategy = Strategy()
        self.risk = RiskManager(self.db, self.ex)
        self.mode = "PAPER" if PAPER_TRADING else "REAL"

    def print_dashboard(self, price, rsi, pnl=0.0, status="SCANNING"):
        bal = self.ex.get_balance_idr()
        dash = f"[{datetime.now().strftime('%H:%M:%S')}] {self.mode} | IDR: Rp{int(bal):,} | {SYMBOL}: {price:,.0f} | RSI: {rsi:.1f} | PnL: {pnl:.2f}% | {status}      "
        sys.stdout.write('\r' + dash)
        sys.stdout.flush()

    def run(self):
        msg = f"🚀 Bot {self.mode} Started on {SYMBOL}"
        log.info(msg)
        send_telegram(msg)

        while True:
            try:
                pos = self.db.get_active_position(SYMBOL)
                
                df = self.ex.fetch_market_data(SYMBOL_RADAR, '1m')
                if df is None:
                    time.sleep(5)
                    continue
                    
                df = self.strategy.calc_indicators(df)
                curr_price = df.iloc[-1]['close']
                rsi = df.iloc[-1]['rsi']

                if pos:
                    pnl_pct = ((curr_price - pos['buy_price']) / pos['buy_price']) * 100
                    self.print_dashboard(curr_price, rsi, pnl_pct, "HOLDING")
                    self.risk.check_auto_sell(pos, curr_price)
                else:
                    self.print_dashboard(curr_price, rsi, 0.0, "SCANNING")
                    
                    if self.strategy.check_buy_signal(self.ex):
                        print("") 
                        log.info("🎯 Triple Confirmation + Trend + Volume Valid! EKSEKUSI BUY.")
                        
                        bal = self.ex.get_balance_idr()
                        if bal >= BUY_AMOUNT_IDR:
                            res = self.ex.execute_buy_idr(SYMBOL, BUY_AMOUNT_IDR)
                            if res['success']:
                                self.db.save_position(SYMBOL, curr_price, res['koin_diterima'], BUY_AMOUNT_IDR)
                                msg = f"🔵 <b>BUY SUCCESS</b>\nPair: {SYMBOL}\nPrice: {curr_price:,.0f}\nAmount: Rp{BUY_AMOUNT_IDR}"
                                send_telegram(msg)
                                log.info("Berhasil Beli! Masuk fase Cooldown.")
                                time.sleep(COOLDOWN_MINUTES * 60)
                        else:
                            log.warning("Saldo IDR tidak cukup untuk menembak.")

            except KeyboardInterrupt:
                print("\nMenutup sistem dengan aman...")
                sys.exit(0)
            except Exception as e:
                log.error(f"Failsafe Triggered: {e}")
                send_telegram(f"⚠️ <b>BOT ERROR</b>\nMessage: {e}")
                time.sleep(15)

            time.sleep(15)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
            
