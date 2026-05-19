import os
import sys
import time
import hmac
import hashlib
import requests
import json
import urllib3
from datetime import datetime
from dotenv import load_dotenv

# [!] MEMBUNGKAM PERINGATAN SSL
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

SYMBOL = "BTC_USDT"     
LEVERAGE = 20           
TRADE_VOL = 1           

RSI_PERIOD = 14         
RSI_OVERSOLD = 30       
RSI_OVERBOUGHT = 70     

TAKE_PROFIT_PERCENT = 1.5  
STOP_LOSS_PERCENT = 1.0    
COOLDOWN_TIME = 60         

# ==========================================
# [2] ENGINE RAW API (FONDASI YANG TERBUKTI JALAN)
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
            
            if res.status_code != 200:
                return {"success": False, "error": f"HTTP {res.status_code}"}
            return res.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_balance(self):
        res = self._request("GET", "/api/v1/private/account/assets")
        if res and res.get("success") and res.get("data"):
            for asset in res["data"]:
                if asset["currency"] == "USDT":
                    return float(asset["availableBalance"])
        return 0.0

    def get_klines(self, symbol):
        url = f"{self.base_url}/api/v1/contract/kline/{symbol}?interval=Min1&limit={RSI_PERIOD + 10}"
        try:
            res = requests.get(url, timeout=10, verify=False).json()
            if res and res.get("success") and "data" in res and "close" in res["data"]:
                return [float(p) for p in res["data"]["close"]]
        except:
            pass
        return []

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
        data = {
            "symbol": symbol,
            "vol": vol,
            "leverage": leverage,
            "side": side,
            "type": 5, 
            "openType": 1 
        }
        action = {1: "OPEN LONG", 2: "CLOSE LONG", 3: "OPEN SHORT", 4: "CLOSE SHORT"}
        print(f"\n[!] TRANSMISI API: {action.get(side, 'UNKNOWN')} | Vol: {vol} | Lev: {leverage}x")
        return self._request("POST", "/api/v1/private/order/submit", params=data)

# ==========================================
# [3] OTAK ALGORITMA (PURE PYTHON - ANTI CRASH)
# ==========================================
def calculate_rsi(prices, period=14):
    # Pelindung mutlak: Jika data rusak, kembalikan 50 (Netral)
    if not isinstance(prices, list) or len(prices) < period + 1:
        return 50.0
    
    try:
        prices = [float(p) for p in prices]
    except Exception:
        return 50.0

    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
            
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100.0
        
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)

# ==========================================
# [4] TERMINAL TTY LOOP (INDESTRUCTIBLE EDITION)
# ==========================================
def run_autonomous_bot():
    engine = MexcEngine()
    print(f"\n[*] PROTOKOL VANGUARD AKTIF | MODE: INDESTRUCTIBLE")
    
    saldo = engine.get_balance()
    if saldo == 0.0:
        print("[!] Memeriksa koneksi API...")
        time.sleep(2)
        saldo = engine.get_balance()
        
    print(f"[✅] Engine Validated. Amunisi: ${saldo:.4f} USDT | Target: {SYMBOL}\n")
    print("="*85)

    waktu_mulai_cooldown = 0

    while True:
        waktu_sekarang = datetime.now().strftime("%H:%M:%S")
        timestamp_sekarang = time.time()
        
        # 1. PENGAMBILAN DATA
        prices = engine.get_klines(SYMBOL)
        if not prices or len(prices) < 2:
            sys.stdout.write(f"\r[{waktu_sekarang}] Menunggu sinkronisasi data harga (WARP/API)...".ljust(85))
            sys.stdout.flush()
            time.sleep(2)
            continue
            
        harga_sekarang = prices[-1]
        rsi_sekarang = calculate_rsi(prices, RSI_PERIOD)

        # 2. SINKRONISASI POSISI REAL-TIME
        posisi_aktif = engine.get_real_position(SYMBOL)

        # 3. TAMPILAN RADAR
        if posisi_aktif:
            tipe = "LONG" if posisi_aktif["positionType"] == 1 else "SHORT"
            entry = posisi_aktif["holdAvgPrice"]
            
            if tipe == "LONG":
                pnl_pct = ((harga_sekarang - entry) / entry) * 100 * LEVERAGE
            else:
                pnl_pct = ((entry - harga_sekarang) / entry) * 100 * LEVERAGE
                
            teks_status = f"POSISI {tipe} | Entry: ${entry:,.2f} | PNL: {pnl_pct:+.2f}%"
        else:
            sisa_cooldown = int(COOLDOWN_TIME - (timestamp_sekarang - waktu_mulai_cooldown))
            if sisa_cooldown > 0:
                teks_status = f"PENDINGINAN MESIN ❄️ ({sisa_cooldown}d)"
            else:
                teks_status = "MENGINTAI MOMEN 🎯"

        sys.stdout.write(f"\r[{waktu_sekarang}] {SYMBOL} | Harga: ${harga_sekarang:,.2f} | RSI: {rsi_sekarang:05.1f} | {teks_status}".ljust(85))
        sys.stdout.flush()

        # 4. LOGIKA EKSEKUSI TRADING
        if posisi_aktif:
            tipe = "LONG" if posisi_aktif["positionType"] == 1 else "SHORT"
            
            if pnl_pct >= TAKE_PROFIT_PERCENT:
                print(f"\n[🎯] TAKE PROFIT ({pnl_pct:+.2f}%)! MENUTUP POSISI...")
                res = engine.execute_order(SYMBOL, 2 if tipe == "LONG" else 4, posisi_aktif["vol"], LEVERAGE)
                if res and res.get('success'):
                    print("[✅] Sukses. Mengamankan Profit.")
                    waktu_mulai_cooldown = time.time()
                
            elif pnl_pct <= -STOP_LOSS_PERCENT:
                print(f"\n[🩸] STOP LOSS ({pnl_pct:+.2f}%)! MEMOTONG KERUGIAN...")
                res = engine.execute_order(SYMBOL, 2 if tipe == "LONG" else 4, posisi_aktif["vol"], LEVERAGE)
                if res and res.get('success'):
                    print("[✅] Sukses. Mencegah likuidasi.")
                    waktu_mulai_cooldown = time.time()

        else:
            sisa_cooldown = int(COOLDOWN_TIME - (timestamp_sekarang - waktu_mulai_cooldown))
            if sisa_cooldown <= 0:
                if rsi_sekarang <= RSI_OVERSOLD:
                    print(f"\n[🔥] RSI {rsi_sekarang:.1f} (OVERSOLD)! MEMBUKA POSISI LONG...")
                    res = engine.execute_order(SYMBOL, 1, TRADE_VOL, LEVERAGE)
                    if res and res.get("success"):
                        print("[✅] Order Masuk Bursa!")
                    time.sleep(2)

                elif rsi_sekarang >= RSI_OVERBOUGHT:
                    print(f"\n[🧊] RSI {rsi_sekarang:.1f} (OVERBOUGHT)! MEMBUKA POSISI SHORT...")
                    res = engine.execute_order(SYMBOL, 3, TRADE_VOL, LEVERAGE)
                    if res and res.get("success"):
                        print("[✅] Order Masuk Bursa!")
                    time.sleep(2)

        time.sleep(2) 

if __name__ == "__main__":
    backoff = 5
    while True:
        try:
            run_autonomous_bot()
        except KeyboardInterrupt:
            print("\n\n[!] Mesin dimatikan secara manual. Selamat berhiatus, Direktur!")
            sys.exit()
        except Exception as e:
            print(f"\n\n[☠️] KONEKSI TERSENDAT: {e}")
            print(f"[⚙️] Auto-Revive aktif. Restart dalam {backoff} detik...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        
