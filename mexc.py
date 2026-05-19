import os
import sys
import time
import hmac
import hashlib
import requests
import json
import urllib3
import pandas as pd
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

HOLD_TIME_LIMIT = 180   # Waktu tahan posisi (3 menit)
COOLDOWN_TIME = 60      # Istirahat setelah untung (1 menit)

# ==========================================
# [2] ENGINE RAW API (BERDASARKAN KODEMU YG JALAN)
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
        headers["Signature"] = self._generate_signature(timestamp, payload)

        try:
            if method == "GET":
                headers["Signature"] = self._generate_signature(timestamp) 
                res = requests.get(url, headers=headers, timeout=10, verify=False)
            else:
                res = requests.post(url, headers=headers, data=payload, timeout=10, verify=False)
            return res.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_ticker(self, symbol):
        # Menggunakan jalur yang sudah terbukti sukses di mesinmu
        try:
            res = requests.get(f"{self.base_url}/api/v1/contract/ticker?symbol={symbol}", verify=False).json()
            if res and res.get("success"):
                return float(res["data"]["lastPrice"])
        except:
            pass
        return 0.0

    def get_balance(self):
        res = self._request("GET", "/api/v1/private/account/assets")
        if res and res.get("success") and res.get("data"):
            for asset in res["data"]:
                if asset["currency"] == "USDT":
                    return float(asset["availableBalance"])
        return 0.0

    def execute_order(self, symbol, side, vol, leverage):
        data = {
            "symbol": symbol, "price": "", "vol": vol, "leverage": leverage,
            "side": side, "type": 5, "openType": 1
        }
        action = {1: "OPEN LONG", 2: "CLOSE LONG", 3: "OPEN SHORT", 4: "CLOSE SHORT"}
        print(f"\n[!] TRANSMISI API: Mengeksekusi {action[side]} | Vol: {vol} | Lev: {leverage}x")
        return self._request("POST", "/api/v1/private/order/submit", params=data)

# ==========================================
# [3] OTAK ALGORITMA (TICK-BASED RSI)
# ==========================================
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    df = pd.DataFrame(prices, columns=['close'])
    delta = df['close'].diff()
    
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0.0).rolling(window=period).mean()
    
    g = gain.iloc[-1]
    l = loss.iloc[-1]
    
    if l == 0:
        return 100.0 if g > 0 else 50.0
        
    rs = g / l
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)

# ==========================================
# [4] TERMINAL TTY LOOP (AUTOPILOT)
# ==========================================
def run_autonomous_bot():
    engine = MexcEngine()
    print(f"\n[*] PROTOKOL 'NIGHT WATCHMAN' AKTIF | MODE: TICK-SCALPING")
    
    saldo = engine.get_balance()
    print(f"[✅] Amunisi: ${saldo:.4f} USDT | Target: {SYMBOL}\n")
    print("="*80)

    status_mesin = "MENGINTAI" 
    waktu_buka_posisi = 0
    waktu_mulai_cooldown = 0
    price_history = []
    
    print("[*] Mengumpulkan data harga secara live... (Butuh ~30 detik pemanasan)")
    
    while True:
        waktu_sekarang = datetime.now().strftime("%H:%M:%S")
        timestamp_sekarang = time.time()
        
        # Ekstraksi harga (Aman & Terbukti)
        harga_sekarang = engine.get_ticker(SYMBOL)
        if harga_sekarang == 0.0:
            time.sleep(2)
            continue
            
        # Simpan jejak harga ke memori lokal
        price_history.append(harga_sekarang)
        if len(price_history) > 60:
            price_history.pop(0)
            
        rsi_sekarang = calculate_rsi(price_history, RSI_PERIOD)
        
        # LOGIKA VISUAL RADAR
        if status_mesin == "LONG" or status_mesin == "SHORT":
            durasi = int(timestamp_sekarang - waktu_buka_posisi)
            teks_status = f"DALAM POSISI {status_mesin} ⏳ ({durasi}d / {HOLD_TIME_LIMIT}d)"
        elif status_mesin == "COOLDOWN":
            sisa_cooldown = int(COOLDOWN_TIME - (timestamp_sekarang - waktu_mulai_cooldown))
            teks_status = f"PENDINGINAN MESIN ❄️ ({sisa_cooldown}d)"
        else:
            if len(price_history) <= RSI_PERIOD:
                teks_status = f"MENGUMPULKAN DATA 🔄 ({len(price_history)}/{RSI_PERIOD})"
            else:
                teks_status = "MENGINTAI MOMEN 🎯"

        sys.stdout.write(f"\r[{waktu_sekarang}] {SYMBOL} | Harga: ${harga_sekarang:,.2f} | Saldo: ${saldo:.4f} | RSI: {rsi_sekarang:05.1f} | {teks_status}".ljust(90))
        sys.stdout.flush()

        # LOGIKA EKSEKUSI TRADING
        if len(price_history) > RSI_PERIOD:
            if status_mesin == "MENGINTAI":
                if rsi_sekarang <= RSI_OVERSOLD:
                    print(f"\n[🔥] RSI {rsi_sekarang:.1f} (OVERSOLD)! MEMBUKA POSISI LONG...")
                    res = engine.execute_order(SYMBOL, 1, TRADE_VOL, LEVERAGE)
                    if res and res.get('success'):
                        print("[✅] LONG Berhasil! Menahan posisi selama 3 menit.")
                        status_mesin = "LONG"
                        waktu_buka_posisi = time.time()
                    else:
                        print(f"\n[❌] Gagal Open: {res}")
                        time.sleep(2)

                elif rsi_sekarang >= RSI_OVERBOUGHT:
                    print(f"\n[🧊] RSI {rsi_sekarang:.1f} (OVERBOUGHT)! MEMBUKA POSISI SHORT...")
                    res = engine.execute_order(SYMBOL, 3, TRADE_VOL, LEVERAGE)
                    if res and res.get('success'):
                        print("[✅] SHORT Berhasil! Menahan posisi selama 3 menit.")
                        status_mesin = "SHORT"
                        waktu_buka_posisi = time.time()
                    else:
                        print(f"\n[❌] Gagal Open: {res}")
                        time.sleep(2)

            elif status_mesin == "LONG":
                if (timestamp_sekarang - waktu_buka_posisi) >= HOLD_TIME_LIMIT:
                    print(f"\n[⏰] Waktu Habis! MENUTUP POSISI LONG (Take Profit/Cut Loss)...")
                    res = engine.execute_order(SYMBOL, 2, TRADE_VOL, LEVERAGE) 
                    if res and res.get('success'):
                        saldo = engine.get_balance() 
                        status_mesin = "COOLDOWN"
                        waktu_mulai_cooldown = time.time()

            elif status_mesin == "SHORT":
                if (timestamp_sekarang - waktu_buka_posisi) >= HOLD_TIME_LIMIT:
                    print(f"\n[⏰] Waktu Habis! MENUTUP POSISI SHORT (Take Profit/Cut Loss)...")
                    res = engine.execute_order(SYMBOL, 4, TRADE_VOL, LEVERAGE) 
                    if res and res.get('success'):
                        saldo = engine.get_balance() 
                        status_mesin = "COOLDOWN"
                        waktu_mulai_cooldown = time.time()

            elif status_mesin == "COOLDOWN":
                if (timestamp_sekarang - waktu_mulai_cooldown) >= COOLDOWN_TIME:
                    print(f"\n[🔄] Pendinginan selesai. Radar siap mencari mangsa.")
                    status_mesin = "MENGINTAI"

        time.sleep(2) 

if __name__ == "__main__":
    while True:
        try:
            run_autonomous_bot()
        except KeyboardInterrupt:
            print("\n\n[!] Mesin dimatikan secara manual. Selamat tidur, Direktur!")
            sys.exit()
        except Exception as e:
            print(f"\n\n[☠️] SYSTEM CRASH / KONEKSI PUTUS: {e}")
            print("[⚙️] Auto-Revive aktif. Memulai ulang dalam 5 detik...")
            time.sleep(5)
                             
