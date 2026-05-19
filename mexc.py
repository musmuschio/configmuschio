import os
import sys
import time
import hmac
import hashlib
import requests
import json
import urllib3
import ccxt
from datetime import datetime
from dotenv import load_dotenv

# [!] PROTOKOL SILUMAN: Bypass SSL & Matikan Warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# ==========================================
# [1] KONFIGURASI OPERASIONAL (HIATUS READY)
# ==========================================
API_KEY = os.getenv("MEXC_API_KEY", "").strip()
SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "").strip()

SYMBOL_TRADE = "BTC_USDT"     # Eksekusi di MEXC
SYMBOL_RADAR = "BTC/USDT"     # Pantau di Binance (Lebih Stabil)
LEVERAGE = 20           
TRADE_VOL = 1           

RSI_PERIOD = 14         
RSI_OVERSOLD = 30       
RSI_OVERBOUGHT = 70     

TAKE_PROFIT_PERCENT = 1.5  # Profit 1.5% langsung bungkus
STOP_LOSS_PERCENT = 1.0    # Rugi 1.0% langsung cut
COOLDOWN_TIME = 60         # Istirahat 1 menit setelah trade

# ==========================================
# [2] ENGINE EKSEKUSI (FONDASI TERUJI)
# ==========================================
class MexcEngine:
    def __init__(self):
        self.base_url = "https://contract.mexc.com"
        # Gunakan session agar koneksi lebih stabil
        self.session = requests.Session()

    def _generate_signature(self, timestamp, payload=""):
        sign_str = f"{API_KEY}{timestamp}{payload}"
        return hmac.new(SECRET_KEY.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest()

    def _request(self, method, endpoint, params=None):
        url = self.base_url + endpoint
        timestamp = str(int(time.time() * 1000))
        
        # Samarkan sebagai Browser Chrome agar tidak diblokir Cloudflare (Error 403)
        headers = {
            "ApiKey": API_KEY,
            "Request-Time": timestamp,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        payload = json.dumps(params) if params else ""
        
        try:
            if method == "GET":
                # Signature GET tanpa payload (Sesuai temuan Direktur)
                headers["Signature"] = self._generate_signature(timestamp)
                res = self.session.get(url, headers=headers, timeout=15, verify=False)
            else:
                # Signature POST dengan payload
                headers["Signature"] = self._generate_signature(timestamp, payload)
                res = self.session.post(url, headers=headers, data=payload, timeout=15, verify=False)
            
            if res.status_code == 403:
                return {"success": False, "error": "403: DIBLOKIR GATEWAY"}
            
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

    def get_real_position(self, symbol):
        # Cek posisi asli di bursa untuk sinkronisasi state
        res = self._request("GET", "/api/v1/private/position/open_positions")
        if res and res.get("success") and res.get("data"):
            for pos in res["data"]:
                if pos["symbol"] == symbol and pos["vol"] > 0:
                    return {
                        "positionType": pos["positionType"], # 1:Long, 2:Short
                        "holdAvgPrice": float(pos["holdAvgPrice"]),
                        "vol": pos["vol"]
                    }
        return None

    def execute_order(self, symbol, side, vol, leverage):
        # side: 1 (OpenLong), 2 (CloseLong), 3 (OpenShort), 4 (CloseShort)
        data = {"symbol": symbol, "vol": vol, "leverage": leverage, "side": side, "type": 5, "openType": 1}
        return self._request("POST", "/api/v1/private/order/submit", params=data)

# ==========================================
# [3] OTAK RSI (PURE PYTHON)
# ==========================================
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1: return 50.0
    try:
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [abs(d) if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
        if avg_loss == 0: return 100.0
        return 100 - (100 / (1 + (avg_gain / avg_loss)))
    except: return 50.0

# ==========================================
# [4] LOOP OTONOM (HYBRID CCXT)
# ==========================================
def run_autonomous_bot():
    engine = MexcEngine()
    # Gunakan Binance sebagai "Mata" karena API-nya paling kuat di dunia
    radar = ccxt.binance({'enableRateLimit': True})
    
    print(f"\n[*] VANGUARD PROTOCOL START | MODE: HIATUS SAFE")
    
    saldo = engine.get_balance()
    if saldo == 0.0:
        print("[!] Saldo 0 atau API Terblokir. Pastikan Dana ada di Akun FUTURES.")
    else:
        print(f"[✅] Koneksi Berhasil. Amunisi: ${saldo:.4f} USDT")
        
    print("="*85)
    
    waktu_mulai_cooldown = 0

    while True:
        waktu_sekarang = datetime.now().strftime("%H:%M:%S")
        timestamp_sekarang = time.time()
        
        try:
            # Ambil Candle 1 Menit dari Binance
            candles = radar.fetch_ohlcv(SYMBOL_RADAR, timeframe='1m', limit=RSI_PERIOD + 5)
            prices = [c[4] for c in candles]
            harga_sekarang = prices[-1]
            rsi_sekarang = calculate_rsi(prices, RSI_PERIOD)
        except:
            sys.stdout.write(f"\r[{waktu_sekarang}] Menunggu sinyal satelit...".ljust(85))
            sys.stdout.flush()
            time.sleep(2)
            continue

        # Sinkronisasi posisi MEXC
        posisi_aktif = engine.get_real_position(SYMBOL_TRADE)

        # UI Radar
        if posisi_aktif:
            tipe = "LONG" if posisi_aktif["positionType"] == 1 else "SHORT"
            entry = posisi_aktif["holdAvgPrice"]
            # Hitung PNL Aktual
            if tipe == "LONG":
                pnl = ((harga_sekarang - entry) / entry) * 100 * LEVERAGE
            else:
                pnl = ((entry - harga_sekarang) / entry) * 100 * LEVERAGE
            teks = f"POSISI {tipe} | Entry: ${entry:,.2f} | PNL: {pnl:+.2f}%"
        else:
            sisa_cd = int(COOLDOWN_TIME - (timestamp_sekarang - waktu_mulai_cooldown))
            teks = f"PENDINGINAN ({sisa_cd}d)" if sisa_cd > 0 else "MENGINTAI MOMEN 🎯"

        sys.stdout.write(f"\r[{waktu_sekarang}] {SYMBOL_TRADE} | Harga: ${harga_sekarang:,.2f} | RSI: {rsi_sekarang:.1f} | {teks}".ljust(90))
        sys.stdout.flush()

        # Eksekusi
        if posisi_aktif:
            tipe = "LONG" if posisi_aktif["positionType"] == 1 else "SHORT"
            if pnl >= TAKE_PROFIT_PERCENT or pnl <= -STOP_LOSS_PERCENT:
                print(f"\n[!] EXIT MARKET | PNL: {pnl:+.2f}%")
                res = engine.execute_order(SYMBOL_TRADE, 2 if tipe == "LONG" else 4, posisi_aktif["vol"], LEVERAGE)
                if res.get('success'): 
                    waktu_mulai_cooldown = time.time()
                    saldo = engine.get_balance()
        else:
            if (timestamp_sekarang - waktu_mulai_cooldown) > COOLDOWN_TIME:
                if rsi_sekarang <= RSI_OVERSOLD:
                    print(f"\n[🔥] RSI OVERSOLD! Beli LONG.")
                    engine.execute_order(SYMBOL_TRADE, 1, TRADE_VOL, LEVERAGE)
                    time.sleep(2)
                elif rsi_sekarang >= RSI_OVERBOUGHT:
                    print(f"\n[🧊] RSI OVERBOUGHT! Beli SHORT.")
                    engine.execute_order(SYMBOL_TRADE, 3, TRADE_VOL, LEVERAGE)
                    time.sleep(2)

        time.sleep(2)

if __name__ == "__main__":
    while True:
        try: run_autonomous_bot()
        except KeyboardInterrupt: sys.exit()
        except Exception as e:
            print(f"\n[!] System Restarting: {e}")
            time.sleep(5)
