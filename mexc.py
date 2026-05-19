import os
import sys
import time
import hmac
import hashlib
import requests
import json
import urllib3
import ccxt  # <--- SENJATA BARU KITA
from datetime import datetime
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# ==========================================
# [1] KONFIGURASI TEMPUR
# ==========================================
API_KEY = os.getenv("MEXC_API_KEY", "").strip()
SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "").strip()

if not API_KEY or not SECRET_KEY:
    print("❌ ERROR: Kunci MEXC tidak ditemukan di .env!")
    sys.exit(1)

SYMBOL_TRADE = "BTC_USDT"     # Untuk dieksekusi di MEXC
SYMBOL_RADAR = "BTC/USDT"     # Untuk dipantau dari Binance CCXT
LEVERAGE = 20           
TRADE_VOL = 1           

RSI_PERIOD = 14         
RSI_OVERSOLD = 30       
RSI_OVERBOUGHT = 70     

TAKE_PROFIT_PERCENT = 1.5  
STOP_LOSS_PERCENT = 1.0    
COOLDOWN_TIME = 60         

# ==========================================
# [2] ENGINE EKSEKUSI RAW MEXC (TANGAN KANAN)
# ==========================================
class MexcEngine:
    def __init__(self):
        self.base_url = "https://contract.mexc.com"

    def _generate_signature(self, timestamp, payload=""):
        sign_str = f"{API_KEY}{timestamp}{payload}"
        return hmac.new(SECRET_KEY.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest()

    def _request(self, method, endpoint, params=None):
        url = self.base_url + endpoint
        timestamp = str(int(time.time() * 1000))
        headers = {"ApiKey": API_KEY, "Request-Time": timestamp, "Content-Type": "application/json"}
        payload = json.dumps(params) if params else ""

        try:
            if method == "GET":
                headers["Signature"] = self._generate_signature(timestamp)
                res = requests.get(url, headers=headers, timeout=10, verify=False)
            else:
                headers["Signature"] = self._generate_signature(timestamp, payload)
                res = requests.post(url, headers=headers, data=payload, timeout=10, verify=False)
            return res.json()
        except Exception:
            return {"success": False}

    def get_balance(self):
        res = self._request("GET", "/api/v1/private/account/assets")
        if res and res.get("success") and res.get("data"):
            for asset in res["data"]:
                if asset["currency"] == "USDT":
                    return float(asset["availableBalance"])
        return 0.0

    def get_real_position(self, symbol):
        res = self._request("GET", "/api/v1/private/position/open_positions")
        if res and res.get("success") and res.get("data"):
            for pos in res["data"]:
                if pos["symbol"] == symbol and pos["vol"] > 0:
                    return {
                        "positionType": pos["positionType"], 
                        "holdAvgPrice": float(pos["holdAvgPrice"]),
                        "vol": pos["vol"]
                    }
        return None

    def execute_order(self, symbol, side, vol, leverage):
        data = {"symbol": symbol, "vol": vol, "leverage": leverage, "side": side, "type": 5, "openType": 1}
        return self._request("POST", "/api/v1/private/order/submit", params=data)

# ==========================================
# [3] OTAK ALGORITMA PURE PYTHON (ANTI CRASH)
# ==========================================
def calculate_rsi(prices, period=14):
    if not isinstance(prices, list) or len(prices) < period + 1: return 50.0
    try: prices = [float(p) for p in prices]
    except Exception: return 50.0

    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0: gains.append(change); losses.append(0.0)
        else: gains.append(0.0); losses.append(abs(change))
            
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0: return 100.0
    return float(100 - (100 / (1 + (avg_gain / avg_loss))))

# ==========================================
# [4] TERMINAL TTY LOOP (CCXT HYBRID)
# ==========================================
def run_autonomous_bot():
    engine = MexcEngine()
    # MATA PENGINTAI CCXT: Menggunakan server Binance yang 1000% stabil
    radar = ccxt.binance({'enableRateLimit': True}) 
    
    print(f"\n[*] PROTOKOL VANGUARD AKTIF | MODE: HYBRID CCXT (BINANCE RADAR)")
    
    saldo = engine.get_balance()
    if saldo == 0.0:
        print("[!] Memeriksa koneksi API MEXC...")
        time.sleep(2)
        saldo = engine.get_balance()
        
    print(f"[✅] Engine Tembus. Amunisi: ${saldo:.4f} USDT | Target: {SYMBOL_TRADE}\n")
    print("="*85)

    waktu_mulai_cooldown = 0

    while True:
        waktu_sekarang = datetime.now().strftime("%H:%M:%S")
        timestamp_sekarang = time.time()
        
        # 1. PENGAMBILAN DATA (MENGGUNAKAN CCXT BINANCE - ANTI NYANGKUT)
        try:
            candles = radar.fetch_ohlcv(SYMBOL_RADAR, timeframe='1m', limit=RSI_PERIOD + 5)
            prices = [c[4] for c in candles] # Ambil harga Close saja
        except Exception as e:
            sys.stdout.write(f"\r[{waktu_sekarang}] Menunggu sinyal satelit CCXT...".ljust(85))
            sys.stdout.flush()
            time.sleep(2)
            continue
            
        harga_sekarang = prices[-1]
        rsi_sekarang = calculate_rsi(prices, RSI_PERIOD)

        # 2. SINKRONISASI POSISI MEXC
        posisi_aktif = engine.get_real_position(SYMBOL_TRADE)

        # 3. TAMPILAN RADAR
        if posisi_aktif:
            tipe = "LONG" if posisi_aktif["positionType"] == 1 else "SHORT"
            entry = posisi_aktif["holdAvgPrice"]
            pnl_pct = (((harga_sekarang - entry) / entry) * 100 * LEVERAGE) if tipe == "LONG" else (((entry - harga_sekarang) / entry) * 100 * LEVERAGE)
            teks_status = f"POSISI {tipe} | Entry: ${entry:,.2f} | PNL: {pnl_pct:+.2f}%"
        else:
            sisa_cooldown = int(COOLDOWN_TIME - (timestamp_sekarang - waktu_mulai_cooldown))
            if sisa_cooldown > 0: teks_status = f"PENDINGINAN ❄️ ({sisa_cooldown}d)"
            else: teks_status = "MENGINTAI MOMEN 🎯"

        sys.stdout.write(f"\r[{waktu_sekarang}] {SYMBOL_TRADE} | Harga: ${harga_sekarang:,.2f} | RSI: {rsi_sekarang:05.1f} | {teks_status}".ljust(90))
        sys.stdout.flush()

        # 4. LOGIKA EKSEKUSI
        if posisi_aktif:
            tipe = "LONG" if posisi_aktif["positionType"] == 1 else "SHORT"
            
            if pnl_pct >= TAKE_PROFIT_PERCENT:
                print(f"\n[🎯] TAKE PROFIT ({pnl_pct:+.2f}%)! MENUTUP POSISI...")
                engine.execute_order(SYMBOL_TRADE, 2 if tipe == "LONG" else 4, posisi_aktif["vol"], LEVERAGE)
                waktu_mulai_cooldown = time.time()
                
            elif pnl_pct <= -STOP_LOSS_PERCENT:
                print(f"\n[🩸] STOP LOSS ({pnl_pct:+.2f}%)! MEMOTONG KERUGIAN...")
                engine.execute_order(SYMBOL_TRADE, 2 if tipe == "LONG" else 4, posisi_aktif["vol"], LEVERAGE)
                waktu_mulai_cooldown = time.time()

        else:
            if sisa_cooldown <= 0:
                if rsi_sekarang <= RSI_OVERSOLD:
                    print(f"\n[🔥] RSI {rsi_sekarang:.1f} (OVERSOLD)! MEMBUKA POSISI LONG...")
                    engine.execute_order(SYMBOL_TRADE, 1, TRADE_VOL, LEVERAGE)
                    time.sleep(2)
                elif rsi_sekarang >= RSI_OVERBOUGHT:
                    print(f"\n[🧊] RSI {rsi_sekarang:.1f} (OVERBOUGHT)! MEMBUKA POSISI SHORT...")
                    engine.execute_order(SYMBOL_TRADE, 3, TRADE_VOL, LEVERAGE)
                    time.sleep(2)

        time.sleep(2) 

if __name__ == "__main__":
    while True:
        try: run_autonomous_bot()
        except KeyboardInterrupt: sys.exit()
        except Exception: time.sleep(5)
        
