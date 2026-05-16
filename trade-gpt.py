import ccxt
import time
import pandas as pd
from datetime import datetime

# =========================
# CONFIG
# =========================
API_KEY = "YOUR_API_KEY"
SECRET_KEY = "YOUR_SECRET_KEY"

SYMBOL = "BTC/IDR"

BUY_AMOUNT_IDR = 25000

RSI_PERIOD = 14
RSI_OVERSOLD = 30

TIMEFRAME = "1m"
CANDLE_LIMIT = 100

SCAN_INTERVAL = 15
COOLDOWN_AFTER_BUY = 600


# =========================
# LOGGER
# =========================
def log(msg, level="INFO"):
    icons = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARN": "⚠️",
        "ERROR": "❌",
        "TRADE": "🚀",
        "BRAIN": "🧠"
    }

    now = datetime.now().strftime("%H:%M:%S")

    print(
        f"[{now}] "
        f"{icons.get(level,'🔹')} "
        f"{msg}"
    )


# =========================
# EXCHANGE
# =========================
exchange = ccxt.indodax({
    "apiKey": API_KEY,
    "secret": SECRET_KEY,
    "enableRateLimit": True
})

markets = exchange.load_markets()

if SYMBOL not in markets:
    raise Exception(
        f"Pair {SYMBOL} tidak ditemukan."
    )

market_info = markets[SYMBOL]


# =========================
# INDICATORS
# =========================
def add_indicators(df):

    # RSI
    delta = df["close"].diff()

    gain = (
        delta.where(delta > 0, 0)
        .rolling(RSI_PERIOD)
        .mean()
    )

    loss = (
        (-delta.where(delta < 0, 0))
        .rolling(RSI_PERIOD)
        .mean()
    )

    rs = gain / loss

    df["rsi"] = 100 - (
        100 / (1 + rs)
    )

    # MACD
    ema12 = df["close"].ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = df["close"].ewm(
        span=26,
        adjust=False
    ).mean()

    df["macd"] = ema12 - ema26

    df["macd_signal"] = df["macd"].ewm(
        span=9,
        adjust=False
    ).mean()

    df["macd_hist"] = (
        df["macd"] - df["macd_signal"]
    )

    # Bollinger
    df["bb_mid"] = (
        df["close"]
        .rolling(20)
        .mean()
    )

    df["bb_std"] = (
        df["close"]
        .rolling(20)
        .std()
    )

    df["bb_upper"] = (
        df["bb_mid"] +
        (2 * df["bb_std"])
    )

    df["bb_lower"] = (
        df["bb_mid"] -
        (2 * df["bb_std"])
    )

    return df


# =========================
# FETCH DATA
# =========================
def get_market_dataframe():

    bars = exchange.fetch_ohlcv(
        SYMBOL,
        timeframe=TIMEFRAME,
        limit=CANDLE_LIMIT
    )

    df = pd.DataFrame(
        bars,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]
    )

    return add_indicators(df)


# =========================
# SIGNAL CHECK
# =========================
def check_signal(df):

    if len(df) < 30:
        return False

    current = df.iloc[-1]
    prev = df.iloc[-2]

    # Hindari NaN
    required = [
        current["rsi"],
        current["macd_hist"],
        current["bb_lower"]
    ]

    if pd.isna(required).any():
        return False

    # RSI oversold
    rsi_ok = (
        current["rsi"] <= RSI_OVERSOLD
    )

    # MACD crossing
    macd_ok = (
        prev["macd_hist"] <= 0 and
        current["macd_hist"] > 0
    )

    # Harga murah
    bb_ok = (
        current["close"] <=
        current["bb_lower"]
    )

    log(
        f"RSI={current['rsi']:.2f} | "
        f"MACD={current['macd_hist']:.4f} | "
        f"PRICE={current['close']}",
        "BRAIN"
    )

    return (
        rsi_ok and
        macd_ok and
        bb_ok
    )


# =========================
# BALANCE CHECK
# =========================
def has_enough_balance():

    balance = exchange.fetch_balance()

    idr_free = balance["IDR"]["free"]

    log(
        f"Saldo IDR tersedia: {idr_free}",
        "INFO"
    )

    return idr_free >= BUY_AMOUNT_IDR


# =========================
# BUY EXECUTION
# =========================
def execute_buy():

    if not has_enough_balance():

        log(
            "Saldo tidak cukup.",
            "WARN"
        )

        return False

    ticker = exchange.fetch_ticker(
        SYMBOL
    )

    last_price = ticker["last"]

    btc_amount = (
        BUY_AMOUNT_IDR /
        last_price
    )

    # Precision fix
    btc_amount = exchange.amount_to_precision(
        SYMBOL,
        btc_amount
    )

    # Check minimum lot
    min_amount = (
        market_info["limits"]
        .get("amount", {})
        .get("min")
    )

    if min_amount:

        if float(btc_amount) < min_amount:

            log(
                f"Amount terlalu kecil "
                f"({btc_amount} < {min_amount})",
                "WARN"
            )

            return False

    log(
        f"BUY {btc_amount} BTC "
        f"@ {last_price}",
        "TRADE"
    )

    order = exchange.create_market_buy_order(
        SYMBOL,
        float(btc_amount)
    )

    log(
        f"BUY SUCCESS: {order['id']}",
        "SUCCESS"
    )

    return True


# =========================
# MAIN LOOP
# =========================
log(
    f"Bot aktif: {SYMBOL}",
    "SUCCESS"
)

while True:

    try:

        df = get_market_dataframe()

        if check_signal(df):

            log(
                "Triple confirmation valid.",
                "SUCCESS"
            )

            success = execute_buy()

            if success:

                log(
                    "Cooldown aktif...",
                    "INFO"
                )

                time.sleep(
                    COOLDOWN_AFTER_BUY
                )

        else:

            price = df.iloc[-1]["close"]

            print(
                f"Monitoring... "
                f"{SYMBOL} "
                f"{price}",
                end="\r"
            )

    except Exception as e:

        log(
            f"System Error: {e}",
            "ERROR"
        )

    time.sleep(
        SCAN_INTERVAL
    )