import os
import time
import hmac
import hashlib
import requests
import pandas as pd
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

# Gunakan API Key & Secret dari screenshot tadi
API_KEY = os.getenv("MEXC_API_KEY")
SECRET_KEY = os.getenv("MEXC_SECRET_KEY")

class MEXCFuturesEngine:
    def __init__(self):
        self.base_url = "https://fapi.mexc.com" # Endpoint khusus Futures

    def generate_signature(self, params):
        query_string = urlencode(params)
        return hmac.new(
            SECRET_KEY.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def get_ticker(self, symbol="BTC_USDT"):
        # Mengambil harga real-time untuk dashboard TTY
        url = f"{self.base_url}/api/v1/contract/ticker?symbol={symbol}"
        return requests.get(url).json()

    def place_order(self, symbol, side, vol, price, leverage=10):
        # Fungsi "Eksekusi Cuan" - Menggunakan Leverage
        endpoint = "/api/v1/private/order/submit"
        timestamp = int(time.time() * 1000)
        
        params = {
            "symbol": symbol,
            "side": side,            # 1 untuk Open Long, 3 untuk Open Short
            "vol": vol,              # Jumlah kontrak
            "leverage": leverage,
            "type": 1,               # Market Order agar instan
            "openType": 1,           # Isolated Margin (Aman buat modal kecil)
            "timestamp": timestamp
        }
        
        params["signature"] = self.generate_signature(params)
        headers = {"ApiKey": API_KEY, "Request-Time": str(timestamp)}
        
        res = requests.post(self.base_url + endpoint, params=params, headers=headers)
        return res.json()

# Contoh penggunaan di Alacritty
if __name__ == "__main__":
    engine = MEXCFuturesEngine()
    print(f"[*] Menghubungkan ke MEXC... Harga BTC Saat Ini: {engine.get_ticker()['data']['lastPrice']}")
  
