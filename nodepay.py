import requests
import time
import uuid
import sys

# --- TOKEN UTUH (SUDAH DIBERSIHKAN DARI SPASI) ---
NP_TOKEN = "eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwia2lkIjoiZkJIakdsTUllYW5jTm1RVFI2ZHdVNjlkTFZOV0VrN3M2dFFvc3RkcVNBQzk1dmpoMHA5NElnMVl6S2dxb1ZiU1IwRVQ2ai1qWHBqZVNNWjRac2RIOWcifQ..Lng1BHGEhypJQBtOvTqWkw.7zS8n-sCAor-PpQ6C9ghWHNVjlPmScoVm6WHzBuNi_w5tLPwe5Iip_NAbiO5h5q9sx5qU-7HQn0uICvMxBXVVaWOx6KNPL8gbzPVY7nz0o65IFTzfrPL1Phi2JPNcb_VsrydnUVkr68xnVDyloXZTzD_Fd5YMwfqIavtBZsdLjcY6Q9Yhg3DRv_cyJOuaURbmg0E_HOcMJiVqxZBdF1e4L4Lu72JJo_46HiKW2G4-pNwOmmwz0-V_hpU66rJApc1og1xV8o5HES6NbcDYGsZLs4cn3zCe8zK3ajxmuKAQCXFGoE87o4ZrsLYBAAovpnZqlpnelfBheRYcAnn0FDEiWKcJeyGqPWd8SAJ4y-snPIVUvHyr-iKKWSRfn9krMti9uM4feygtIV0DBMDd0eGgmGeWo-pZpcFbMHjqUozPvyJVXWQh7gKPqKXZND18204peWoFqK4PoN6IGY_BQdOJwDbNmcshElYyGfpElvCfGf_tGXitg0EU6xNDL_j1d3cL3asZrI9lqV0eaIjtn4wz0SpAXF6XszHBE92saldtBdPafRwhvOXUyYpycX3uuQpRhFFHr-4YHpu_NWjp73TfmRra2iSNUABEvdE2EcFE8ulr0_XDie_jlE-cY9XM-D7cJBokf3tE3onaDw_2nUZtA8I7ql76W1sUtoh-oZ-HXw_Qg34Hzwn6kVdHc7Zx2fqmxmttqscYiMut0jnJ-9Nr4bdX0VnCZfvRUxmCmmwDPDfM0GI1rRRuRZivzDAGTXl_XyTEXU1eXHGCMqyQkSCnDSKBKvBU3q7N4FjAHRjmvmyUugWPlqeGdUtzihDw6Q-9Q-b4fWroox3wl4Ya6_7xjNwsvukwlsogp36JLpNcu1g6729IWsrxv8b5iilIHjafxBK33WqtU8PsqGZxQeOrwNROkoIbiCz9qw0N_bAU3My1S-ZwnR4RYZYHm-zTyo90M_q0FLhgF4AM3bO-Y89Lr0iaWPXplxMylYnPaCb4Vwxi2xJWCiAA4jAuYWiWtgU0Aj2CcWC6LSasIQQi9MYnIOk324XzwRy60B5yJzphnpwytAegK2D-Ej2jDlTzcdqwFFnlSqJJB_kTtDOztABzDi3sWpphQ536bXauGM3YIIYSeErN9_lPpB5k833JwX-MFSHQV0tdJ2db7KNQ9OZFWl1wPi1E3xefWfig5AO6vrYFghTMjpg_38heeKoju5k.ar0tRRHL7TNOHCLgRAPHSMvsAgFnS-0TrAP1ltUzgJc"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def send_ping():
    url = "https://nw.nodepay.ai/api/v1/network/ping"
    headers = {
        "Authorization": f"Bearer {NP_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Origin": "https://app.nodepay.ai",
        "Referer": "https://app.nodepay.ai/"
    }
    
    data = {
        "id": str(uuid.uuid4()),
        "browser_id": str(uuid.uuid4()),
        "timestamp": int(time.time()),
        "version": "2.2.7"
    }
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=15)
        if response.status_code == 200:
            score = response.json().get('data', {}).get('score', 0)
            return f"SUKSES | Score: {score}"
        else:
            return f"FAILED | Status: {response.status_code} | Msg: {response.text[:50]}"
    except Exception as e:
        return f"ERROR: {str(e)}"

if __name__ == "__main__":
    log("Nodepay Node Aktif. Memulai misi...")
    while True:
        status = send_ping()
        log(status)
        # Ping tiap 60 detik (1 menit) biar aman
        time.sleep(60)
