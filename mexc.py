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

# Membungkam peringatan SSL agar terminal tetap bersih
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# ==========================================
# [1] KONFIGURASI TEMPUR (PRO-GRADE)
# ==========================================
API_KEY = os.getenv("MEXC_API_KEY", "").strip()
SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "").strip()

SYMBOL = "BTC_USDT"
LEVERAGE = 20
TRADE_VOL = 1           # Jumlah kontrak minimum
RSI_PERIOD = 14
RSI_OVERSOLD = 30       # Pemicu Open Long (Beli Naik)
RSI_OVERBOUGHT = 70     # Pemicu Open Short (Beli Turun)

HOLD_TIME_LIMIT = 180   # Tahan posisi maksimal 3 menit (180 detik)
COOLDOWN_TIME = 180     # Istirahat 3 menit setelah transaksi

# ==========================================
# [2] ENGINE RAW API MEXC
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

    def get_balance(self):
        res = self._request("GET", "/api/v1/private/account/assets")
        if res and res.get("success") and res.get("data"):
            for asset in res["data"]:
                if asset["currency"] == "USDT":
                    return float(asset["availableBalance"])
        return 0.0

    def get_klines(self, symbol):
        url = f"{self.base_url}/api/v1/contract/kline/{symbol}?interval=Min1&limit=50"
        try:
            res = requests.get(url, timeout=10, verify=False).json()
            if res.get("success") and "data" in res:
                return [float(p) for p in res["data"]["close"]]
            return []
        except:
            return []

    def execute_order(self, symbol, side, vol, leverage):
        # SIDE CODE MEXC: 1 (Open Long), 2 (Close Long), 3 (Open Short), 4 (Close Short)
        data = {
            "symbol": symbol,
            "price": "",
            "vol": vol,
            "leverage": leverage,
            "side": side,
            "type": 5, # Market Order (Instan)
            "openType": 1 # Isolated Margin
        }
        action = {1: "OPEN LONG", 2: "CLOSE LONG", 3: "OPEN SHORT", 4: "CLOSE SHORT"}
        print(f"\n[!] TRANSMISI API: Mengeksekusi {action[side]} | Vol: {vol} | Lev: {leverage}x")
        return self._request("POST", "/api/v1/private/order/submit", params=data)

# ==========================================
# [3] OTAK ALGORITMA (INDIKATOR)
# ==========================================
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    df = pd.DataFrame(prices, columns=['close'])
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

# ==========================================
# [4] STATE MACHINE (SISTEM AUTOPILOT)
# ==========================================
def run_autonomous_bot():
    engine = MexcEngine()
    print("\n" + "="*80)
    print(f"[*] PROTOKOL 'NIGHT WATCHMAN' AKTIF | MODE: HIATUS AUTOPILOT")
    print("="*80)
    
    saldo = engine.get_balance()
    print(f"[✅] Verifikasi Sistem Berhasil. Amunisi: ${saldo:.4f} USDT | Target: {SYMBOL}\n")

    # State Variables
    status_mesin = "MENGINTAI" 
    waktu_buka_posisi = 0
    waktu_mulai_cooldown = 0
    
    while True:
        waktu_sekarang = datetime.now().strftime("%H:%M:%S")
        timestamp_sekarang = time.time()
        
        prices = engine.get_klines(SYMBOL)
        if not prices:
            time.sleep(2) # Jika gagal ambil harga, tunggu sebentar
            continue
            
        harga_sekarang = prices[-1]
        rsi_sekarang = calculate_rsi(prices, RSI_PERIOD)
        
        # ---------------------------------------
        # LOGIKA TAMPILAN RADAR TTY
        # ---------------------------------------
        if status_mesin == "LONG" or status_mesin == "SHORT":
            durasi = int(timestamp_sekarang - waktu_buka_posisi)
            teks_status = f"DALAM POSISI {status_mesin} ⏳ ({durasi}d / {HOLD_TIME_LIMIT}d)"
        elif status_mesin == "COOLDOWN":
            sisa_cooldown = int(COOLDOWN_TIME - (timestamp_sekarang - waktu_mulai_cooldown))
            teks_status = f"PENDINGINAN MESIN ❄️ ({sisa_cooldown}d)"
        else:
            teks_status = "MENGINTAI MOMEN 🎯"

        sys.stdout.write(f"\r[{waktu_sekarang}] {SYMBOL} | Harga: ${harga_sekarang:,.2f} | Saldo: ${saldo:.4f} | RSI: {rsi_sekarang:05.1f} | {teks_status}".ljust(90))
        sys.stdout.flush()

        # ---------------------------------------
        # LOGIKA EKSEKUSI (STATE MACHINE)
        # ---------------------------------------
        if status_mesin == "MENGINTAI":
            if rsi_sekarang <= RSI_OVERSOLD:
                print(f"\n[🔥] RSI {rsi_sekarang:.1f} (OVERSOLD) TERDETEKSI! MEMBUKA POSISI LONG...")
                res = engine.execute_order(SYMBOL, 1, TRADE_VOL, LEVERAGE)
                if res and res.get('success'):
                    print("[✅] Order LONG Berhasil! Masuk mode tempur.")
                    status_mesin = "LONG"
                    waktu_buka_posisi = time.time()
                else:
                    print(f"[❌] Gagal Open Long: {res.get('error', 'Unknown Error')}")
                    time.sleep(5)

            elif rsi_sekarang >= RSI_OVERBOUGHT:
                print(f"\n[🧊] RSI {rsi_sekarang:.1f} (OVERBOUGHT) TERDETEKSI! MEMBUKA POSISI SHORT...")
                res = engine.execute_order(SYMBOL, 3, TRADE_VOL, LEVERAGE)
                if res and res.get('success'):
                    print("[✅] Order SHORT Berhasil! Masuk mode tempur.")
                    status_mesin = "SHORT"
                    waktu_buka_posisi = time.time()
                else:
                    print(f"[❌] Gagal Open Short: {res.get('error', 'Unknown Error')}")
                    time.sleep(5)

        elif status_mesin == "LONG":
            if (timestamp_sekarang - waktu_buka_posisi) >= HOLD_TIME_LIMIT:
                print(f"\n[⏰] Waktu Tahan ({HOLD_TIME_LIMIT}s) Habis! MENUTUP POSISI LONG (TAKE PROFIT/CUT LOSS)...")
                res = engine.execute_order(SYMBOL, 2, TRADE_VOL, LEVERAGE) # 2 = Close Long
                if res and res.get('success'):
                    print("[✅] Posisi LONG Tertutup Aman. Masuk mode pendinginan.")
                    saldo = engine.get_balance() # Refresh saldo
                    status_mesin = "COOLDOWN"
                    waktu_mulai_cooldown = time.time()

        elif status_mesin == "SHORT":
            if (timestamp_sekarang - waktu_buka_posisi) >= HOLD_TIME_LIMIT:
                print(f"\n[⏰] Waktu Tahan ({HOLD_TIME_LIMIT}s) Habis! MENUTUP POSISI SHORT (TAKE PROFIT/CUT LOSS)...")
                res = engine.execute_order(SYMBOL, 4, TRADE_VOL, LEVERAGE) # 4 = Close Short
                if res and res.get('success'):
                    print("[✅] Posisi SHORT Tertutup Aman. Masuk mode pendinginan.")
                    saldo = engine.get_balance() # Refresh saldo
                    status_mesin = "COOLDOWN"
                    waktu_mulai_cooldown = time.time()

        elif status_mesin == "COOLDOWN":
            if (timestamp_sekarang - waktu_mulai_cooldown) >= COOLDOWN_TIME:
                print(f"\n[🔄] Pendinginan selesai. Radar kembali aktif mencari mangsa.")
                status_mesin = "MENGINTAI"

        time.sleep(2) # Ritme detak jantung server: 2 detik

# ==========================================
# [5] PELINDUNG UTAMA (CRASH IMMUNITY)
# ==========================================
if __name__ == "__main__":
    while True:
        try:
            run_autonomous_bot()
        except KeyboardInterrupt:
            print("\n\n[!] Mesin dimatikan secara manual oleh Direktur. Selamat berhiatus!")
            sys.exit()
        except Exception as e:
            print(f"\n\n[☠️] TERJADI CRASH SISTEM / KONEKSI: {e}")
            print("[⚙️] Protokol Auto-Revive aktif. Mem-booting ulang mesin dalam 15 detik...")
            time.sleep(15)
