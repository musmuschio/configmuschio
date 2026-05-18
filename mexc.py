import os
import sys
import time
import hmac
import hashlib
import requests
import json
import urllib3
from datetime import datetime
from urllib.parse import urlencode
from dotenv import load_dotenv

# [!] MEMBUNGKAM PERINGATAN SSL (AGAR TTY TETAP BERSIH)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

# ==========================================
# [1] KONFIGURASI BARE-METAL
# ==========================================
API_KEY = os.getenv("MEXC_API_KEY", "").strip()
SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "").strip()

if not API_KEY or not SECRET_KEY:
    print("❌ ERROR: Kunci MEXC tidak ditemukan di .env!")
    sys.exit(1)

# Parameter Trading Futures
SYMBOL = "BTC_USDT"     
LEVERAGE = 20           

# ==========================================
# [2] ENGINE RAW API MEXC FUTURES (BYPASS MODE)
# ==========================================
class MexcEngine:
    def __init__(self):
        self.base_url = "https://contract.mexc.com"

    def _generate_signature(self, timestamp, payload=""):
        sign_str = f"{API_KEY}{timestamp}{payload}"
        return hmac.new(
            SECRET_KEY.encode('utf-8'),
            sign_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _request(self, method, endpoint, params=None):
        url = self.base_url + endpoint
        timestamp = str(int(time.time() * 1000))
        
        headers = {
            "ApiKey": API_KEY,
            "Request-Time": timestamp,
            "Content-Type": "application/json"
        }

        payload = json.dumps(params) if params else ""
        headers["Signature"] = self._generate_signature(timestamp, payload)

        try:
            # Menggunakan verify=False untuk menembus blokir ISP lokal
            if method == "GET":
                headers["Signature"] = self._generate_signature(timestamp) 
                res = requests.get(url, headers=headers, timeout=10, verify=False)
            else:
                res = requests.post(url, headers=headers, data=payload, timeout=10, verify=False)
            
            # Memastikan response adalah JSON, bukan halaman blokir HTML
            return res.json()
            
        except json.JSONDecodeError:
            return {"success": False, "error": "Koneksi dialihkan ke halaman blokir (Internet Positif)."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==========================================
    # [3] OPERASI INTI
    # ==========================================
    def get_ticker(self, symbol):
        res = requests.get(f"{self.base_url}/api/v1/contract/ticker?symbol={symbol}", verify=False).json()
        if res.get("success"):
            return float(res["data"]["lastPrice"])
        return 0.0

    def get_balance(self):
        res = self._request("GET", "/api/v1/private/account/assets")
        if res.get("success") and res.get("data"):
            for asset in res["data"]:
                if asset["currency"] == "USDT":
                    return float(asset["availableBalance"])
        return 0.0

# ==========================================
# [4] TERMINAL TTY LOOP (ALACRITTY READY)
# ==========================================
def run_tty_monitor():
    engine = MexcEngine()
    print(f"\n[*] Mesin Futures MEXC Diinisialisasi | Mode: TTY Silent (Bypass SSL)")
    print(f"[*] Menembus dinding API dan memeriksa saldo...\n")
    
    saldo = engine.get_balance()
    
    if saldo == 0.0:
        print("[!] Peringatan: Saldo tidak terbaca atau 0. Pastikan kunci API benar dan ada saldo di Futures.")
    else:
        print(f"[✅] Akses Tembus! Saldo Margin (USDT): ${saldo:.4f}")
        
    print("="*60)

    try:
        while True:
            harga_sekarang = engine.get_ticker(SYMBOL)
            waktu = datetime.now().strftime("%H:%M:%S")
            
            # Animasi terminal per 1 detik
            sys.stdout.write(f"\r[{waktu}] RADAR {SYMBOL} | Harga: ${harga_sekarang:,.2f} | Saldo: ${saldo:.4f} | Status: MENGINTAI 🎯 ")
            sys.stdout.flush()
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n[!] Mesin dimatikan secara manual oleh Direktur.")
        sys.exit()

if __name__ == "__main__":
    run_tty_monitor()
    
