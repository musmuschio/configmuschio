import os
import sys
import time
import hmac
import hashlib
import requests
import json
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# [1] KONFIGURASI PROFESIONAL
# ==========================================
API_KEY = os.getenv("MEXC_API_KEY", "").strip()
SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "").strip()

if not API_KEY or not SECRET_KEY:
    print("❌ ERROR: Kunci MEXC tidak ditemukan di .env!")
    sys.exit(1)

SYMBOL = "BTC_USDT"     
LEVERAGE = 20           
TRADE_VOL = 1           # Pastikan 1 ini sesuai dengan contract size minimum di MEXC

# Parameter RSI & Manajemen Risiko Asli
RSI_PERIOD = 14         
RSI_OVERSOLD = 30       
RSI_OVERBOUGHT = 70     

TAKE_PROFIT_PERCENT = 1.5  # Ambil untung jika untung 1.5%
STOP_LOSS_PERCENT = 1.0    # Potong rugi jika minus 1.0%
COOLDOWN_TIME = 60         # Jeda setelah transaksi (detik)

# ==========================================
# [2] ENGINE RAW API (BERDASARKAN KOREKSI DIREKTUR)
# ==========================================
class MexcEngine:
    def __init__(self):
        self.base_url = "https://contract.mexc.com"
        self.session = requests.Session()

    def _generate_signature(self, timestamp, payload=""):
        sign_str = f"{API_KEY}{timestamp}{payload}"
        return hmac.new(
            SECRET_KEY.encode(),
            sign_str.encode(),
            hashlib.sha256
        ).hexdigest()

    def _request(self, method, endpoint, params=None):
        url = self.base_url + endpoint
        timestamp = str(int(time.time() * 1000))
        payload = json.dumps(params) if params else ""

        headers = {
            "ApiKey": API_KEY,
            "Request-Time": timestamp,
            "Content-Type": "application/json",
            "Signature": self._generate_signature(timestamp, payload)
        }

        try:
            # PENTING: verify=False dihapus. Gunakan standar SSL + WARP.
            if method == "GET":
                response = self.session.get(url, headers=headers, params=params, timeout=10)
            else:
                response = self.session.post(url, headers=headers, data=payload, timeout=10)

            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}", "text": response.text}

            try:
                return response.json()
            except Exception:
                return {"success": False, "error": "Invalid JSON", "text": response.text}

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timeout"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Connection error"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- API ENDPOINTS ---
    def get_balance(self):
        res = self._request("GET", "/api/v1/private/account/assets")
        if res.get("success") and res.get("data"):
            for asset in res["data"]:
                if asset["currency"] == "USDT":
                    return float(asset["availableBalance"])
        return 0.0

    def get_klines(self, symbol):
        # Menggunakan K-Line (Candle 1 Menit)
        res = self._request("GET", f"/api/v1/contract/kline/{symbol}?interval=Min1&limit=50")
        if res.get("success") and "data" in res:
            return [float(p) for p in res["data"]["close"]]
        return []

    def get_real_position(self, symbol):
        # Mencegah halusinasi: Cek langsung ke exchange apakah ada posisi terbuka
        res = self._request("GET", "/api/v1/private/position/open_positions")
        if res.get("success") and res.get("data"):
            for pos in res["data"]:
                if pos["symbol"] == symbol and pos["vol"] > 0:
                    return {
                        "positionType": pos["positionType"], # 1: Long, 2: Short
                        "holdAvgPrice": float(pos["holdAvgPrice"]),
                        "vol": pos["vol"]
                    }
        return None

    def execute_order(self, symbol, side, vol, leverage):
        data = {
            "symbol": symbol, "price": "", "vol": vol, "leverage": leverage,
            "side": side, "type": 5, "openType": 1
        }
        action = {1: "OPEN LONG", 2: "CLOSE LONG", 3: "OPEN SHORT", 4: "CLOSE SHORT"}
        print(f"\n[!] TRANSMISI API: {action[side]} | Vol: {vol} | Lev: {leverage}x")
        return self._request("POST", "/api/v1/private/order/submit", params=data)

# ==========================================
# [3] OTAK ALGORITMA (CANDLE-BASED RSI)
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
# [4] TERMINAL TTY LOOP (VANGUARD ARCHITECTURE)
# ==========================================
def run_autonomous_bot():
    engine = MexcEngine()
    print(f"\n[*] PROTOKOL VANGUARD AKTIF | MODE: HIATUS SAFE")
    saldo = engine.get_balance()
    print(f"[✅] Engine & Network Validated. Amunisi: ${saldo:.4f} USDT\n")
    print("="*80)

    waktu_mulai_cooldown = 0
    fail_count = 0

    while True:
        waktu_sekarang = datetime.now().strftime("%H:%M:%S")
        timestamp_sekarang = time.time()
        
        # 1. PENGAMBILAN DATA (Candle Asli)
        prices = engine.get_klines(SYMBOL)
        if not prices:
            fail_count += 1
            sys.stdout.write(f"\r[!] Gagal mengambil data. Retrying... ({fail_count})")
            time.sleep(2)
            continue
            
        fail_count = 0 # Reset jika sukses
        harga_sekarang = prices[-1]
        rsi_sekarang = calculate_rsi(prices, RSI_PERIOD)

        # 2. SINKRONISASI STATE (Cek Posisi Asli di Server MEXC)
        posisi_aktif = engine.get_real_position(SYMBOL)

        # 3. LOGIKA TAMPILAN RADAR
        if posisi_aktif:
            tipe = "LONG" if posisi_aktif["positionType"] == 1 else "SHORT"
            entry = posisi_aktif["holdAvgPrice"]
            
            # Hitung PNL persentase
            if tipe == "LONG":
                pnl_pct = ((harga_sekarang - entry) / entry) * 100 * LEVERAGE
            else:
                pnl_pct = ((entry - harga_sekarang) / entry) * 100 * LEVERAGE
                
            teks_status = f"POSISI {tipe} ⏳ | Entry: ${entry:,.2f} | PNL: {pnl_pct:+.2f}%"
        else:
            sisa_cooldown = int(COOLDOWN_TIME - (timestamp_sekarang - waktu_mulai_cooldown))
            if sisa_cooldown > 0:
                teks_status = f"PENDINGINAN MESIN ❄️ ({sisa_cooldown}d)"
            else:
                teks_status = "MENGINTAI MOMEN 🎯"

        sys.stdout.write(f"\r[{waktu_sekarang}] {SYMBOL} | Harga: ${harga_sekarang:,.2f} | RSI: {rsi_sekarang:05.1f} | {teks_status}".ljust(95))
        sys.stdout.flush()

        # 4. LOGIKA EKSEKUSI TRADING
        if posisi_aktif:
            # Logika Take Profit & Stop Loss Nyata
            tipe = "LONG" if posisi_aktif["positionType"] == 1 else "SHORT"
            if pnl_pct >= TAKE_PROFIT_PERCENT:
                print(f"\n[🎯] TAKE PROFIT TERCAPAI ({pnl_pct:+.2f}%)! MENUTUP POSISI...")
                engine.execute_order(SYMBOL, 2 if tipe == "LONG" else 4, posisi_aktif["vol"], LEVERAGE)
                waktu_mulai_cooldown = time.time()
                
            elif pnl_pct <= -STOP_LOSS_PERCENT:
                print(f"\n[🩸] STOP LOSS TERCAPAI ({pnl_pct:+.2f}%)! MEMOTONG KERUGIAN...")
                engine.execute_order(SYMBOL, 2 if tipe == "LONG" else 4, posisi_aktif["vol"], LEVERAGE)
                waktu_mulai_cooldown = time.time()

        else:
            sisa_cooldown = int(COOLDOWN_TIME - (timestamp_sekarang - waktu_mulai_cooldown))
            if sisa_cooldown <= 0:
                if rsi_sekarang <= RSI_OVERSOLD:
                    print(f"\n[🔥] RSI {rsi_sekarang:.1f} (OVERSOLD)! MEMBUKA POSISI LONG...")
                    engine.execute_order(SYMBOL, 1, TRADE_VOL, LEVERAGE)
                    time.sleep(2) # Beri waktu server memproses sebelum next loop

                elif rsi_sekarang >= RSI_OVERBOUGHT:
                    print(f"\n[🧊] RSI {rsi_sekarang:.1f} (OVERBOUGHT)! MEMBUKA POSISI SHORT...")
                    engine.execute_order(SYMBOL, 3, TRADE_VOL, LEVERAGE)
                    time.sleep(2) # Beri waktu server memproses sebelum next loop

        time.sleep(2) # Detak loop utama

if __name__ == "__main__":
    backoff = 5
    while True:
        try:
            run_autonomous_bot()
        except KeyboardInterrupt:
            print("\n\n[!] Mesin dimatikan secara manual. Selamat berhiatus!")
            sys.exit()
        except Exception as e:
            print(f"\n\n[☠️] SYSTEM CRASH: {e}")
            print(f"[⚙️] Auto-Revive aktif. Backoff {backoff} detik...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60) # Exponential backoff max 60s
        
