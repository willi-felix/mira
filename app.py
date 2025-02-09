import sqlitecloud
import threading
import string
import random
import time
import requests
import ipaddress
from datetime import datetime
from urllib.parse import urlparse
from functools import wraps
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlitecloud://cuavg1yfnz.g2.sqlite.cloud:8860/filin.sqlite?apikey=padSix0bECiV7bqbOiEa9NRkbd8ms8OhFwiG2bZhiFM'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

class DatabaseManager:
    def __init__(self):
        self.db_url = "sqlitecloud://cuavg1yfnz.g2.sqlite.cloud:8860/filin.sqlite?apikey=padSix0bECiV7bqbOiEa9NRkbd8ms8OhFwiG2bZhiFM"
        self.pool_lock = threading.Lock()
        self.connection_pool = []
        self.max_connections = 5
        self.ensure_table_schema()
    def ensure_table_schema(self):
        with sqlitecloud.connect(self.db_url) as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS api (api TEXT PRIMARY KEY, type TEXT NOT NULL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS link (shorten_id TEXT PRIMARY KEY, long_url TEXT NOT NULL)")
            conn.commit()
    def get_connection(self):
        with self.pool_lock:
            if self.connection_pool:
                return self.connection_pool.pop()
            else:
                try:
                    return sqlitecloud.connect(self.db_url)
                except Exception as e:
                    print(f"Failed to create new connection: {e}")
                    return None
    def return_connection(self, conn):
        with self.pool_lock:
            if len(self.connection_pool) < self.max_connections:
                self.connection_pool.append(conn)
            else:
                conn.close()

db_manager = DatabaseManager()

api_usage = {}

def check_rate_limit(api_key, api_type):
    now = time.time()
    limits = {
        "developer": {"minute": 5, "hour": 50, "day": 500},
        "production": {"minute": 25, "hour": 250, "day": 500},
        "admin": {"minute": None, "hour": None, "day": None}
    }
    if api_type == "admin":
        return True
    if api_key not in api_usage:
        api_usage[api_key] = {
            "minute": {"count": 0, "reset": now + 60},
            "hour": {"count": 0, "reset": now + 3600},
            "day": {"count": 0, "reset": now + 86400}
        }
    usage = api_usage[api_key]
    for period, seconds in (("minute", 60), ("hour", 3600), ("day", 86400)):
        if now > usage[period]["reset"]:
            usage[period]["count"] = 0
            usage[period]["reset"] = now + seconds
    if (limits[api_type]["minute"] is not None and usage["minute"]["count"] >= limits[api_type]["minute"]) or (limits[api_type]["hour"] is not None and usage["hour"]["count"] >= limits[api_type]["hour"]) or (limits[api_type]["day"] is not None and usage["day"]["count"] >= limits[api_type]["day"]):
        return False
    usage["minute"]["count"] += 1
    usage["hour"]["count"] += 1
    usage["day"]["count"] += 1
    return True

def get_api_key_info(key):
    conn = db_manager.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT type FROM api WHERE api = ?", (key,))
        row = cursor.fetchone()
        if row:
            return {"api": key, "type": row[0]}
        return None
    finally:
        db_manager.return_connection(conn)

def require_api_key(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        if not key:
            return jsonify({"error": "API key missing"}), 401
        api_key_info = get_api_key_info(key)
        if not api_key_info:
            return jsonify({"error": "Invalid API key"}), 401
        if not check_rate_limit(key, api_key_info["type"]):
            return jsonify({"error": "Rate limit exceeded"}), 429
        return func(*args, **kwargs)
    return wrapper

def is_valid_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return False
        if not parsed.netloc:
            return False
        host = parsed.netloc.split(':')[0]
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            return True
    except Exception:
        return False

def is_safe_url(url):
    payload = {
        "client": {"clientId": "filin", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}]
        }
    }
    response = requests.post("https://safebrowsing.googleapis.com/v4/threatMatches:find?key=AIzaSyBapgOJzBGyrJqui9eA1w_xfOawtCU7Q6Q", json=payload)
    if response.status_code == 200:
        data = response.json()
        if "matches" in data:
            return False
        return True
    return False

def generate_short_code():
    characters = string.ascii_letters + string.digits
    for length in range(6, 11):
        max_possible = len(characters) ** length
        conn = db_manager.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM link WHERE LENGTH(shorten_id) = ?", (length,))
            count_codes = cursor.fetchone()[0]
        finally:
            db_manager.return_connection(conn)
        if count_codes < max_possible:
            for _ in range(100):
                code = ''.join(random.choices(characters, k=length))
                conn = db_manager.get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1 FROM link WHERE shorten_id = ?", (code,))
                    if not cursor.fetchone():
                        return code
                finally:
                    db_manager.return_connection(conn)
    raise Exception("Exhausted all possibilities up to length 10")

@app.route('/api/shorten', methods=['POST'])
@require_api_key
def shorten_url():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "No URL provided"}), 400
    long_url = data['url']
    if not is_valid_url(long_url):
        return jsonify({"error": "Invalid URL format"}), 400
    if not is_safe_url(long_url):
        return jsonify({"error": "URL is flagged as unsafe"}), 400
    short_code = generate_short_code()
    conn = db_manager.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO link (shorten_id, long_url) VALUES (?, ?)", (short_code, long_url))
        conn.commit()
    finally:
        db_manager.return_connection(conn)
    return jsonify({"short_url": f"https://go.is-app.top/{short_code}"}), 201

@app.route('/<shorten_id>', methods=['GET'])
def redirect_url(shorten_id):
    conn = db_manager.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT long_url FROM link WHERE shorten_id = ?", (shorten_id,))
        row = cursor.fetchone()
        if row:
            return redirect(row[0])
        return jsonify({"error": "URL not found"}), 404
    finally:
        db_manager.return_connection(conn)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(debug=True)
