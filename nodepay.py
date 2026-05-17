import requests
import time
import uuid
import sys

# --- MASUKKAN TOKEN KAMU DI SINI ---
# Ambil kode panjang ey... yang kamu temukan di Cookie tadi
NP_TOKEN = "PASTE_KODE_TOKEN_KAMU_DI_SINI"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def send_ping():
    url = "https://nw.nodepay.ai/api/v1/network/ping"
    headers = {
        "Authorization": f"Bearer {NP_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    
    # Data identitas unik untuk "Node" kamu
    data = {
        "id": str(uuid.uuid4()),
        "browser_id": str(uuid.uuid4()),
        "timestamp": int(time.time()),
        "version": "2.2.7"
    }
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            score = res_json.get('data', {}).get('score', 0)
            return f"✅ Ping Sukses | Score: {score}"
        elif response.status_code == 401:
            return "❌ Token Salah atau Kadaluarsa. Cek lagi tokennya!"
        else:
            return f"⚠️ Server Response: {response.status_code}"
    except Exception as e:
        return f"📡 Error Koneksi: {e}"

if __name__ == "__main__":
    if NP_TOKEN == "PASTE_KODE_TOKEN_KAMU_DI_SINI":
        print("Error: Kamu belum memasukkan Token!")
        sys.exit()

    log("Nodepay Node Berjalan dalam Diam...")
    while True:
        status = send_ping()
        log(status)
        # Ping tiap 30-60 detik biar aman dan nggak dianggap spam
        time.sleep(45)
