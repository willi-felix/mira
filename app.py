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
from concurrent.futures import ThreadPoolExecutor
from cachetools import TTLCache

app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

executor = ThreadPoolExecutor(max_workers=10)
alias_cache = TTLCache(maxsize=1000, ttl=60)
info_cache = TTLCache(maxsize=1000, ttl=30)

def with_backoff(max_retries=3, initial_delay=0.1, backoff_factor=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(delay)
                    delay *= backoff_factor
        return wrapper
    return decorator

def get_system_load():
    return executor._work_queue.qsize()

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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api (
                    api TEXT PRIMARY KEY, 
                    type TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS link (
                    shorten_id TEXT PRIMARY KEY, 
                    long_url TEXT NOT NULL, 
                    click_count INTEGER DEFAULT 0, 
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    password TEXT,
                    max_clicks INTEGER DEFAULT 0,
                    expire_at DATETIME
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    word TEXT PRIMARY KEY
                )
            """)
    def get_connection(self):
        with self.pool_lock:
            if self.connection_pool:
                return self.connection_pool.pop()
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

def is_internal_url(url):
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc.endswith("filin.fyi")
    except:
        return False

def check_rate_limit(api_key, api_type):
    now = time.time()
    base_limits = {
        "developer": {"minute": 5, "hour": 50, "day": 150},
        "production": {"minute": 30, "hour": 150, "day": 500},
        "enterprise": {"minute": None, "hour": None, "day": None}
    }
    load = get_system_load()
    factor = max(0.5, 1 - (load / 100))
    limits = {}
    for key, periods in base_limits.items():
        limits[key] = {}
        for period, value in periods.items():
            limits[key][period] = int(value * factor) if value is not None else None
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

def get_retry_after(api_key, api_type):
    now = time.time()
    usage = api_usage.get(api_key, {})
    base_limits = {
        "developer": {"minute": 5, "hour": 50, "day": 500},
        "production": {"minute": 25, "hour": 250, "day": 500}
    }
    load = get_system_load()
    factor = max(0.5, 1 - (load / 100))
    limits = {}
    for key, periods in base_limits.items():
        limits[key] = {}
        for period, value in periods.items():
            limits[key][period] = int(value * factor)
    retry_times = []
    for period in ["minute", "hour", "day"]:
        limit = limits.get(api_type, {}).get(period)
        if limit is not None and period in usage and usage[period]["count"] >= limit:
            retry_times.append(usage[period]["reset"] - now)
    return int(min(retry_times)) if retry_times else 0

@with_backoff(max_retries=3)
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
            retry_after = get_retry_after(key, api_key_info["type"])
            response = jsonify({"error": "Rate limit exceeded"})
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return response
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
    response = requests.post(
        "https://safebrowsing.googleapis.com/v4/threatMatches:find?key=AIzaSyBapgOJzBGyrJqui9eA1w_xfOawtCU7Q6Q",
        json=payload
    )
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
    if alias in alias_cache:
        return alias_cache[alias]
    conn = db_manager.get_connection()
    try:
        result = conn.execute("SELECT 1 FROM link WHERE shorten_id = ?", (alias,))
        exists = result.rows and len(result.rows) > 0
        alias_cache[alias] = exists
        return exists
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

def evaluate_link_risk(url):
    score = 0.0
    lower_url = url.lower()
    if "free" in lower_url:
        score += 0.3
    if "click" in lower_url:
        score += 0.2
    if "win" in lower_url:
        score += 0.2
    suspicious_keywords = ["login", "verify", "update", "account", "bank", "paypal", "confirm", "urgent", "alert", "redirect", "out?url="]
    for keyword in suspicious_keywords:
        if keyword in lower_url:
            score += 0.2
    if len(url) > 150:
        score += 0.2
    elif len(url) > 100:
        score += 0.1
    digits = sum(c.isdigit() for c in url)
    ratio = digits / len(url)
    if ratio > 0.3:
        score += 0.2
    parsed = urlparse(url)
    if parsed.port and parsed.port not in [80, 443]:
        score += 0.2
    query = parsed.query
    if query:
        params = query.split('&')
        if len(params) > 3:
            score += 0.1
        if len(query) > 50:
            score += 0.1
        special_chars = sum(1 for c in query if not c.isalnum() and c not in ['=', '&', '%'])
        if special_chars > 5:
            score += 0.1
    return score

def contains_blacklisted_word(url):
    conn = db_manager.get_connection()
    try:
        result = conn.execute("SELECT word FROM blacklist")
        if result.rows:
            for row in result.rows:
                banned = row[0].lower()
                if banned in url.lower():
                    return True, banned
        return False, None
    finally:
        db_manager.return_connection(conn)

@app.route('/api/shorten', methods=['POST'])
@require_api_key
def shorten_url():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "No URL provided"}), 400
    long_url = data['url']
    if is_internal_url(long_url):
        return jsonify({"error": "Cannot shorten an internal link"}), 400
    if not is_valid_url(long_url):
        return jsonify({"error": "Invalid URL format"}), 400
    if not is_safe_url(long_url):
        return jsonify({"error": "URL is flagged as unsafe"}), 400
    blacklisted, banned_word = contains_blacklisted_word(long_url)
    if blacklisted:
        return jsonify({"error": "URL contains banned word", "banned_word": banned_word}), 400
    risk_score = evaluate_link_risk(long_url)
    if risk_score >= 0.5:
        return jsonify({"error": "Link risk too high", "risk_score": risk_score}), 400
    custom_alias = data.get("alias")
    if custom_alias:
        if not is_valid_alias_format(custom_alias):
            return jsonify({"error": "Invalid alias format"}), 400
        if alias_exists(custom_alias):
            return jsonify({"error": "Alias already exists"}), 409
        short_code = custom_alias
    else:
        short_code = generate_short_code()
    pwd = data.get("password")
    max_clicks = data.get("max_clicks", 0)
    exp = data.get("expire_at")
    expire_at = datetime.fromisoformat(exp).isoformat() if exp else None

    @with_backoff(max_retries=3)
    def db_insert():
        conn = db_manager.get_connection()
        try:
            conn.execute(
                "INSERT INTO link (shorten_id, long_url, password, max_clicks, expire_at) VALUES (?, ?, ?, ?, ?)",
                (short_code, long_url, pwd, max_clicks, expire_at)
            )
        finally:
            db_manager.return_connection(conn)

    executor.submit(db_insert).result()
    return jsonify({"short_url": f"https://filin.is-app.top/{short_code}"}), 201

@app.route('/<shorten_id>', methods=['GET'])
def redirect_url(shorten_id):
    @with_backoff(max_retries=3)
    def db_query():
        conn = db_manager.get_connection()
        try:
            return conn.execute("SELECT long_url, click_count, password, max_clicks, expire_at FROM link WHERE shorten_id = ?", (shorten_id,))
        finally:
            db_manager.return_connection(conn)
    result = executor.submit(db_query).result()
    if not (result.rows and len(result.rows) > 0):
        return jsonify({"error": "URL not found"}), 404
    row = result.rows[0]
    long_url, click_count, pwd, max_clicks, expire_at = row[0], row[1], row[2], row[3], row[4]
    if expire_at:
        try:
            if datetime.now() > datetime.fromisoformat(expire_at):
                @with_backoff(max_retries=3)
                def db_delete():
                    conn = db_manager.get_connection()
                    try:
                        conn.execute("DELETE FROM link WHERE shorten_id = ?", (shorten_id,))
                    finally:
                        db_manager.return_connection(conn)
                executor.submit(db_delete)
                return jsonify({"error": "Link expired"}), 410
        except Exception:
            pass
    if max_clicks and int(max_clicks) > 0 and int(click_count) >= int(max_clicks):
        @with_backoff(max_retries=3)
        def db_delete():
            conn = db_manager.get_connection()
            try:
                conn.execute("DELETE FROM link WHERE shorten_id = ?", (shorten_id,))
            finally:
                db_manager.return_connection(conn)
        executor.submit(db_delete)
        return jsonify({"error": "Link deleted due to click limit"}), 410
    if pwd:
        return render_template("password.html", shorten_id=shorten_id)
    @with_backoff(max_retries=3)
    def db_update():
        conn = db_manager.get_connection()
        try:
            conn.execute("UPDATE link SET click_count = click_count + 1 WHERE shorten_id = ?", (shorten_id,))
            if max_clicks and int(max_clicks) > 0 and int(click_count) + 1 >= int(max_clicks):
                conn.execute("DELETE FROM link WHERE shorten_id = ?", (shorten_id,))
        finally:
            db_manager.return_connection(conn)
    executor.submit(db_update)
    return redirect(long_url)

@app.route('/verify/<shorten_id>', methods=['POST'])
def verify_password(shorten_id):
    provided_pwd = request.form.get("password")
    if not provided_pwd:
        return render_template("password.html", shorten_id=shorten_id, error="Password required")
    @with_backoff(max_retries=3)
    def db_query():
        conn = db_manager.get_connection()
        try:
            return conn.execute("SELECT long_url, click_count, password, max_clicks, expire_at FROM link WHERE shorten_id = ?", (shorten_id,))
        finally:
            db_manager.return_connection(conn)
    result = executor.submit(db_query).result()
    if not (result.rows and len(result.rows) > 0):
        return jsonify({"error": "URL not found"}), 404
    row = result.rows[0]
    long_url, click_count, stored_pwd, max_clicks, expire_at = row[0], row[1], row[2], row[3], row[4]
    if expire_at:
        try:
            if datetime.now() > datetime.fromisoformat(expire_at):
                @with_backoff(max_retries=3)
                def db_delete():
                    conn = db_manager.get_connection()
                    try:
                        conn.execute("DELETE FROM link WHERE shorten_id = ?", (shorten_id,))
                    finally:
                        db_manager.return_connection(conn)
                executor.submit(db_delete)
                return jsonify({"error": "Link expired"}), 410
        except Exception:
            pass
    if provided_pwd != stored_pwd:
        return render_template("password.html", shorten_id=shorten_id, error="Incorrect password")
    @with_backoff(max_retries=3)
    def db_update():
        conn = db_manager.get_connection()
        try:
            conn.execute("UPDATE link SET click_count = click_count + 1 WHERE shorten_id = ?", (shorten_id,))
            if max_clicks and int(max_clicks) > 0 and int(click_count) + 1 >= int(max_clicks):
                conn.execute("DELETE FROM link WHERE shorten_id = ?", (shorten_id,))
        finally:
            db_manager.return_connection(conn)
    executor.submit(db_update)
    return redirect(long_url)

@app.route('/api/info/<shorten_id>', methods=['GET'])
@require_api_key
def link_info(shorten_id):
    if shorten_id in info_cache:
        return jsonify(info_cache[shorten_id]), 200
    @with_backoff(max_retries=3)
    def db_query():
        conn = db_manager.get_connection()
        try:
            return conn.execute("SELECT long_url, created_at, click_count, password, max_clicks, expire_at FROM link WHERE shorten_id = ?", (shorten_id,))
        finally:
            db_manager.return_connection(conn)
    result = executor.submit(db_query).result()
    if result.rows and len(result.rows) > 0:
        row = result.rows[0]
        info = {
            "long_url": row[0],
            "created_at": row[1],
            "click_count": row[2],
            "password": row[3],
            "max_clicks": row[4],
            "expire_at": row[5]
        }
        info_cache[shorten_id] = info
        return jsonify(info), 200
    return jsonify({"error": "URL not found"}), 404

@app.route('/api/delete/<shorten_id>', methods=['DELETE'])
@require_api_key
def delete_link(shorten_id):
    @with_backoff(max_retries=3)
    def db_delete():
        conn = db_manager.get_connection()
        try:
            conn.execute("DELETE FROM link WHERE shorten_id = ?", (shorten_id,))
        finally:
            db_manager.return_connection(conn)
    executor.submit(db_delete)
    return jsonify({"message": "Link deleted"}), 200

@app.route('/api/version', methods=['GET'])
def api_version():
    return jsonify({"api_version": "v1"}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/api')
def api_page():
    return render_template('api.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

if __name__ == '__main__':
    app.run(debug=True)
