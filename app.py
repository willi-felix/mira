import libsql_client
import threading
import string
import random
import time
import requests
import ipaddress
import re
from datetime import datetime
from urllib.parse import urlparse
from functools import wraps
from flask import Flask, request, jsonify, redirect, render_template

app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

class DatabaseManager:
    def __init__(self):
        self.db_url = "libsql://01filinfyi-minyoongi.turso.io"
        self.auth_token = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3MzkxNjQxOTEsImlkIjoiMDUxMDYyMjEtM2M3Ny00OTRjLThiZTQtMWQ2ZjhmZmFiNTQ2In0.Hm4pZ3SRHeQkcH6dUvRYR43Vci4uZK_2z4vaquc-OK3_SLVeUVvsTPLtn2Pi5aMyki5rbf5vnBzBDUmnOmieBg"
        self.pool_lock = threading.Lock()
        self.connection_pool = []
        self.max_connections = float('inf')
        self.ensure_table_schema()
    def ensure_table_schema(self):
        with libsql_client.create_client_sync(self.db_url, auth_token=self.auth_token) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS api (api TEXT PRIMARY KEY, type TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS link (shorten_id TEXT PRIMARY KEY, long_url TEXT NOT NULL, click_count INTEGER DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    def get_connection(self):
        with self.pool_lock:
            if self.connection_pool:
                return self.connection_pool.pop()
            else:
                try:
                    return libsql_client.create_client_sync(self.db_url, auth_token=self.auth_token)
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
        "enterprise": {"minute": None, "hour": None, "day": None}
    }
    if api_type == "enterprise":
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
    if ((limits[api_type]["minute"] is not None and usage["minute"]["count"] >= limits[api_type]["minute"]) or
        (limits[api_type]["hour"] is not None and usage["hour"]["count"] >= limits[api_type]["hour"]) or
        (limits[api_type]["day"] is not None and usage["day"]["count"] >= limits[api_type]["day"])):
        return False
    usage["minute"]["count"] += 1
    usage["hour"]["count"] += 1
    usage["day"]["count"] += 1
    return True

def get_api_key_info(key):
    conn = db_manager.get_connection()
    try:
        result = conn.execute("SELECT type FROM api WHERE api = ?", (key,))
        if result.rows and len(result.rows) > 0:
            row = result.rows[0]
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

def is_valid_alias_format(alias):
    pattern = r'^[A-Za-z0-9_-]{3,15}$'
    return re.match(pattern, alias) is not None

def alias_exists(alias):
    conn = db_manager.get_connection()
    try:
        result = conn.execute("SELECT 1 FROM link WHERE shorten_id = ?", (alias,))
        return result.rows and len(result.rows) > 0
    finally:
        db_manager.return_connection(conn)

def generate_short_code():
    characters = string.ascii_letters + string.digits
    for length in range(6, 11):
        max_possible = len(characters) ** length
        conn = db_manager.get_connection()
        try:
            result = conn.execute("SELECT COUNT(*) FROM link WHERE LENGTH(shorten_id) = ?", (length,))
            count_codes = result.rows[0][0] if result.rows and len(result.rows) > 0 else 0
        finally:
            db_manager.return_connection(conn)
        if count_codes < max_possible:
            for _ in range(100):
                code = ''.join(random.choices(characters, k=length))
                conn = db_manager.get_connection()
                try:
                    result = conn.execute("SELECT 1 FROM link WHERE shorten_id = ?", (code,))
                    if not (result.rows and len(result.rows) > 0):
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
    custom_alias = data.get("alias")
    if custom_alias:
        if not is_valid_alias_format(custom_alias):
            return jsonify({"error": "Invalid alias format"}), 400
        if alias_exists(custom_alias):
            return jsonify({"error": "Alias already exists"}), 409
        short_code = custom_alias
    else:
        short_code = generate_short_code()
    conn = db_manager.get_connection()
    try:
        conn.execute("INSERT INTO link (shorten_id, long_url) VALUES (?, ?)", (short_code, long_url))
    finally:
        db_manager.return_connection(conn)
    return jsonify({"short_url": f"https://go.is-app.top/{short_code}"}), 201

@app.route('/<shorten_id>', methods=['GET'])
def redirect_url(shorten_id):
    conn = db_manager.get_connection()
    try:
        result = conn.execute("SELECT long_url, click_count FROM link WHERE shorten_id = ?", (shorten_id,))
        if result.rows and len(result.rows) > 0:
            row = result.rows[0]
            long_url = row[0]
            conn.execute("UPDATE link SET click_count = click_count + 1 WHERE shorten_id = ?", (shorten_id,))
            return redirect(long_url)
        return jsonify({"error": "URL not found"}), 404
    finally:
        db_manager.return_connection(conn)

@app.route('/api/info/<shorten_id>', methods=['GET'])
@require_api_key
def link_info(shorten_id):
    conn = db_manager.get_connection()
    try:
        result = conn.execute("SELECT long_url, created_at, click_count FROM link WHERE shorten_id = ?", (shorten_id,))
        if result.rows and len(result.rows) > 0:
            row = result.rows[0]
            return jsonify({"long_url": row[0], "created_at": row[1], "click_count": row[2]}), 200
        return jsonify({"error": "URL not found"}), 404
    finally:
        db_manager.return_connection(conn)

@app.route('/api/delete/<shorten_id>', methods=['DELETE'])
@require_api_key
def delete_link(shorten_id):
    conn = db_manager.get_connection()
    try:
        conn.execute("DELETE FROM link WHERE shorten_id = ?", (shorten_id,))
        return jsonify({"message": "Link deleted"}), 200
    finally:
        db_manager.return_connection(conn)

@app.route('/api/version', methods=['GET'])
def api_version():
    return jsonify({"api_version": "v1"}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/')
def index():
    return render_template("index.html")

if __name__ == '__main__':
    app.run(debug=True)
