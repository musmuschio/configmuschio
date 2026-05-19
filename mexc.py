import os
import sys
import time
import ccxt
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime

# =========================================================
# LOAD ENV
# =========================================================
load_dotenv()

API_KEY = os.getenv("MEXC_API_KEY")
SECRET_KEY = os.getenv("MEXC_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    print("❌ API KEY / SECRET KEY tidak ditemukan di .env")
    sys.exit(1)

# =========================================================
# KONFIGURASI BOT
# =========================================================
SYMBOL = "BTC/USDT:USDT"
TIMEFRAME = "1m"

LEVERAGE = 10
ORDER_SIZE_USDT = 5

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

STOP_LOSS_PERCENT = 1.0
TAKE_PROFIT_PERCENT = 1.5

COOLDOWN_SECONDS = 60
LOOP_INTERVAL = 5

ENABLE_LONG = True
ENABLE_SHORT = True

# =========================================================
# INIT EXCHANGE
# =========================================================
exchange = ccxt.mexc({
    "apiKey": API_KEY,
    "secret": SECRET_KEY,
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap"
    }
})

# =========================================================
# HELPER
# =========================================================
def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# =========================================================
# SET LEVERAGE
# =========================================================
def setup_leverage():
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
        log(f"✅ Leverage diset {LEVERAGE}x")
    except Exception as e:
        log(f"⚠️ Gagal set leverage: {e}")

# =========================================================
# AMBIL OHLCV
# =========================================================
def fetch_ohlcv():
    candles = exchange.fetch_ohlcv(
        SYMBOL,
        timeframe=TIMEFRAME,
        limit=100
    )

    df = pd.DataFrame(candles, columns=[
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ])

    return df

# =========================================================
# HITUNG RSI
# =========================================================
def calculate_rsi(df, period=14):
    delta = df["close"].diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi.iloc[-1]

# =========================================================
# HARGA TERKINI
# =========================================================
def get_price():
    ticker = exchange.fetch_ticker(SYMBOL)
    return ticker["last"]

# =========================================================
# BALANCE
# =========================================================
def get_balance():
    try:
        balance = exchange.fetch_balance()
        usdt = balance["USDT"]["free"]
        return float(usdt)
    except:
        return 0.0

# =========================================================
# CEK POSISI
# =========================================================
def get_open_position():
    try:
        positions = exchange.fetch_positions([SYMBOL])

        for pos in positions:
            contracts = float(pos.get("contracts", 0))

            if contracts > 0:
                side = pos.get("side")
                entry = float(pos.get("entryPrice", 0))

                return {
                    "side": side,
                    "entry": entry,
                    "contracts": contracts
                }

    except Exception as e:
        log(f"⚠️ Error cek posisi: {e}")

    return None

# =========================================================
# HITUNG SIZE
# =========================================================
def calculate_contract_amount(price):
    qty = ORDER_SIZE_USDT / price

    market = exchange.market(SYMBOL)

    precision = market["precision"]["amount"]

    return float(exchange.amount_to_precision(
        SYMBOL,
        qty
    ))

# =========================================================
# OPEN POSITION
# =========================================================
def open_position(side):
    try:
        price = get_price()
        amount = calculate_contract_amount(price)

        if amount <= 0:
            log("❌ Amount invalid")
            return

        order_side = "buy" if side == "long" else "sell"

        log(f"🚀 OPEN {side.upper()} | Amount: {amount}")

        order = exchange.create_market_order(
            SYMBOL,
            order_side,
            amount
        )

        log(f"✅ Order sukses")
        return order

    except Exception as e:
        log(f"❌ Gagal open posisi: {e}")

# =========================================================
# CLOSE POSITION
# =========================================================
def close_position(position):
    try:
        side = position["side"]
        contracts = position["contracts"]

        close_side = "sell" if side == "long" else "buy"

        log(f"🔒 CLOSE {side.upper()}")

        exchange.create_market_order(
            SYMBOL,
            close_side,
            contracts,
            params={
                "reduceOnly": True
            }
        )

        log("✅ Posisi ditutup")

    except Exception as e:
        log(f"❌ Gagal close posisi: {e}")

# =========================================================
# RISK MANAGEMENT
# =========================================================
def should_close(position, current_price):
    entry = position["entry"]
    side = position["side"]

    if side == "long":
        pnl_percent = (
            (current_price - entry)
            / entry
        ) * 100

    else:
        pnl_percent = (
            (entry - current_price)
            / entry
        ) * 100

    if pnl_percent <= -STOP_LOSS_PERCENT:
        log(f"🛑 STOP LOSS {pnl_percent:.2f}%")
        return True

    if pnl_percent >= TAKE_PROFIT_PERCENT:
        log(f"💰 TAKE PROFIT {pnl_percent:.2f}%")
        return True

    return False

# =========================================================
# MAIN LOOP
# =========================================================
def run_bot():
    log("🤖 BOT AKTIF")

    setup_leverage()

    cooldown_until = 0

    while True:
        try:
            now = time.time()

            if now < cooldown_until:
                remaining = int(cooldown_until - now)
                log(f"❄️ Cooldown {remaining} detik")
                time.sleep(5)
                continue

            df = fetch_ohlcv()

            rsi = calculate_rsi(df)

            price = get_price()

            balance = get_balance()

            position = get_open_position()

            print(
                f"\r💲 {price:.2f} | "
                f"RSI {rsi:.2f} | "
                f"Saldo ${balance:.2f}",
                end=""
            )

            # =========================================
            # ADA POSISI
            # =========================================
            if position:
                if should_close(position, price):
                    print()
                    close_position(position)
                    cooldown_until = time.time() + COOLDOWN_SECONDS

            # =========================================
            # TIDAK ADA POSISI
            # =========================================
            else:
                if ENABLE_LONG and rsi <= RSI_OVERSOLD:
                    print()
                    log(f"🔥 RSI OVERSOLD {rsi:.2f}")
                    open_position("long")

                elif ENABLE_SHORT and rsi >= RSI_OVERBOUGHT:
                    print()
                    log(f"🧊 RSI OVERBOUGHT {rsi:.2f}")
                    open_position("short")

            time.sleep(LOOP_INTERVAL)

        except KeyboardInterrupt:
            print()
            log("🛑 BOT DIMATIKAN")
            sys.exit()

        except Exception as e:
            print()
            log(f"☠️ ERROR: {e}")
            time.sleep(10)

# =========================================================
# START
# =========================================================
if __name__ == "__main__":
    run_bot()
