from flask import Blueprint, request, jsonify, current_app
from models import db, User, Link, Blacklist
from utils import random_slug, is_valid_domain, extract_domain, check_google_safe_browsing
import secrets
from datetime import datetime, timedelta
import asyncio

api = Blueprint("api", __name__, url_prefix="/api")

def get_api_user(request):
    api_key = request.headers.get("Authorization")
    if not api_key:
        return None
    return User.query.filter_by(api=api_key.strip()).first()

@api.route("/links", methods=["POST"])
async def api_create_link():
    user = get_api_user(request)
    if not user:
        return jsonify({"error": "Invalid API key"}), 401
    data = request.json
    long_url = data.get("long_url")
    custom = data.get("custom")
    password = data.get("password")
    expire = data.get("expire")
    one_time = data.get("one_time", False)

    if not long_url or not is_valid_domain(long_url):
        return jsonify({"error": "Invalid long_url"}), 400

    # Check blacklist
    domain = extract_domain(long_url)
    if domain and Blacklist.query.filter_by(domain=domain).first():
        return jsonify({"error": "Domain is blacklisted"}), 403

    # Google Safe Browsing
    safe = await check_google_safe_browsing(current_app.config["GOOGLE_SAFE_BROWSING_API"], long_url)
    if not safe:
        return jsonify({"error": "URL is unsafe"}), 403

    if custom:
        if Link.query.filter_by(short_url=custom).first():
            return jsonify({"error": "Custom alias already exists"}), 409
        slug = custom
    else:
        for _ in range(10):
            slug = random_slug()
            if not Link.query.filter_by(short_url=slug).first():
                break
        else:
            return jsonify({"error": "Unable to generate unique slug"}), 500

    link = Link(
        short_url=slug,
        long_url=long_url,
        owner_id=user.id,
        password=password if password else None,
        expire=datetime.fromisoformat(expire) if expire else None,
        one_time=one_time
    )
    db.session.add(link)
    db.session.commit()
    return jsonify({"short_url": slug, "long_url": long_url}), 201

@api.route("/links/<slug>", methods=["DELETE"])
async def api_delete_link(slug):
    user = get_api_user(request)
    if not user:
        return jsonify({"error": "Invalid API key"}), 401
    link = Link.query.filter_by(short_url=slug, owner_id=user.id).first()
    if not link:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(link)
    db.session.commit()
    return jsonify({"success": True})

@api.route("/links", methods=["GET"])
async def api_list_links():
    user = get_api_user(request)
    if not user:
        return jsonify({"error": "Invalid API key"}), 401
    links = Link.query.filter_by(owner_id=user.id).all()
    return jsonify([{
        "short_url": link.short_url,
        "long_url": link.long_url,
        "clicked": link.clicked,
        "expire": link.expire.isoformat() if link.expire else None,
        "one_time": link.one_time
    } for link in links])

@api.route("/links/<slug>/stats", methods=["GET"])
async def api_link_stats(slug):
    user = get_api_user(request)
    if not user:
        return jsonify({"error": "Invalid API key"}), 401
    link = Link.query.filter_by(short_url=slug, owner_id=user.id).first()
    if not link:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "clicked": link.clicked,
        "created_at": link.created_at.isoformat(),
        "expire": link.expire.isoformat() if link.expire else None,
        "one_time": link.one_time,
    })