import random
import string
from urllib.parse import urlparse
from datetime import datetime
import httpx
import os

def random_slug(length=6):
    return ''.join(random.choices(string.ascii_letters, k=length))

def is_valid_domain(url):
    try:
        result = urlparse(url)
        return bool(result.netloc)
    except:
        return False

def extract_domain(url):
    try:
        return urlparse(url).netloc.lower()
    except:
        return None

async def check_google_safe_browsing(api_key, url):
    endpoint = "https://safebrowsing.googleapis.com/v4/threatMatches:find?key=" + api_key
    body = {
        "client": {"clientId": "miraurl", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes":      ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes":    ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries":    [{"url": url}]
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(endpoint, json=body, timeout=10)
        data = resp.json()
        return not bool(data.get("matches"))