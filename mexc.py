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
from urllib.parse import urlencode
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# ==========================================
# [1] KONFIGURASI TEMPUR (SESUAIKAN JIKA PERLU)
# ==========================================
API_KEY = os.getenv("MEXC_API_KEY", "").strip()
SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "").strip()

SYMBOL = "BTC_USDT"
LEVERAGE = 20
TRADE_VOL = 1           # Modal minimum (1 kontrak)
RSI_PERIOD = 14
RSI_OVERSOLD = 30       # Waktunya Long (Beli)
RSI_OVERBOUGHT = 70     # Waktunya Short (Jual)

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
        except Exception:
            return {"success": False}

    def get_balance(self):
        res = self._request("GET", "/api/v1/private/account/assets")
        if res and res.get("success") and res.get("data"):
            for asset in res["data"]:
                if asset["currency"] == "USDT":
                    return float(asset["availableBalance"])
        return 0.0

    def get_klines(self, symbol):
        # Ambil data lilin (candlestick) 1 Menit terakhir
        url = f"{self.base_url}/api/v1/contract/kline/{symbol}?interval=Min1&limit=50"
        try:
            res = requests.get(url, timeout=10, verify=False).json()
            if res.get("success"):
                return res["data"]["close"]
            return []
        except:
            return []

    def open_market_order(self, symbol, side, vol, leverage):
        # side: 1 (Open Long), 3 (Open Short)
        data = {
            "symbol": symbol,
            "price": "",
            "vol": vol,
            "leverage": leverage,
            "side": side,
            "type": 5,
            "openType": 1
        }
        print(f"\n[!] MENGEKSEKUSI ORDER: {'LONG' if side == 1 else 'SHORT'} | Vol: {vol} | Lev: {leverage}x")
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
    return rsi.iloc[-1]

# ==========================================
# [4] TERMINAL TTY LOOP (MODE TIDUR)
# ==========================================
def run_auto_bot():
    engine = MexcEngine()
    print(f"\n[*] MENGAKTIFKAN MESIN OTONOM | MODE: AUTO-TRADE TTY")
    saldo = engine.get_balance()
    print(f"[✅] Amunisi Siap: ${saldo:.4f} USDT | Target: {SYMBOL}\n")
    print("="*65)

    posisi_terbuka = False # Menjaga agar tidak dobel beli

    try:
        while True:
            waktu = datetime.now().strftime("%H:%M:%S")
            prices = engine.get_klines(SYMBOL)
            
            if not prices:
                time.sleep(2)
                continue
                
            harga_sekarang = prices[-1]
            rsi_sekarang = calculate_rsi(prices, RSI_PERIOD)
            
            # Tampilan TTY (Update satu baris)
            sys.stdout.write(f"\r[{waktu}] {SYMBOL} | Harga: ${harga_sekarang:,.2f} | RSI: {rsi_sekarang:.1f} | Status: {'MENUNGGU MOMEN...' if not posisi_terbuka else 'DALAM POSISI'} ")
            sys.stdout.flush()

            # LOGIKA EKSEKUSI (Hanya jika belum ada posisi terbuka)
            if not posisi_terbuka:
                if rsi_sekarang <= RSI_OVERSOLD:
                    print(f"\n[🔥] RSI {rsi_sekarang:.1f} (OVERSOLD)! MENGAMBIL POSISI LONG (NAIK)...")
                    res = engine.open_market_order(SYMBOL, 1, TRADE_VOL, LEVERAGE)
                    if res.get('success'):
                        print("[✅] Order Long Berhasil Dieksekusi!")
                        posisi_terbuka = True
                        time.sleep(60) # Tidur 1 menit agar tidak spam
                    
                elif rsi_sekarang >= RSI_OVERBOUGHT:
                    print(f"\n[🧊] RSI {rsi_sekarang:.1f} (OVERBOUGHT)! MENGAMBIL POSISI SHORT (TURUN)...")
                    res = engine.open_market_order(SYMBOL, 3, TRADE_VOL, LEVERAGE)
                    if res.get('success'):
                        print("[✅] Order Short Berhasil Dieksekusi!")
                        posisi_terbuka = True
                        time.sleep(60) # Tidur 1 menit agar tidak spam

            # Untuk mereset status posisi_terbuka, idealnya mengecek API apakah ada posisi yang masih jalan.
            # Namun untuk versi bare-metal cepat ini, kita beri delay panjang sebelum berburu lagi.
            if posisi_terbuka:
                time.sleep(300) # Istirahat 5 menit setelah eksekusi sebelum cek pasar lagi
                posisi_terbuka = False

            time.sleep(2) # Refresh data setiap 2 detik
            
    except KeyboardInterrupt:
        print("\n\n[!] Mesin dimatikan secara manual. Selamat beristirahat, Direktur.")
        sys.exit()

if __name__ == "__main__":
    run_auto_bot()
            
