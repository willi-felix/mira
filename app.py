import os
from flask import Flask, request, render_template, redirect, url_for, flash, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from models import db, User, Link, Blacklist
from utils import random_slug, is_valid_domain, extract_domain, check_google_safe_browsing
from mailer import send_new_user_email, send_reset_password_email
from auth import login_manager
from passlib.hash import bcrypt
from datetime import datetime
import secrets
import asyncio

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    app.config['GOOGLE_SAFE_BROWSING_API'] = os.environ['GOOGLE_SAFE_BROWSING_API']
    app.config['RESEND_API'] = os.environ['RESEND_API']
    app.config['RESEND_EMAIL'] = os.environ['RESEND_EMAIL']
    app.config['SITE_NAME'] = os.environ.get('SITE_NAME', 'MiraURL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    from api import api as api_blueprint
    app.register_blueprint(api_blueprint)

    with app.app_context():
        db.create_all()

    @app.context_processor
    def inject_site_name():
        return dict(SITE_NAME=app.config['SITE_NAME'])

    @app.before_request
    def check_first_setup():
        if request.endpoint not in ('setup', 'static') and User.query.count() == 0:
            return redirect(url_for('setup'))

    @app.route('/setup', methods=['GET', 'POST'])
    def setup():
        if User.query.count() > 0:
            return redirect(url_for('login'))
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            api_key = secrets.token_hex(16)
            user = User(email=email, role='admin', api=api_key)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Admin created, please login.', 'success')
            return redirect(url_for('login'))
        return render_template('setup.html')

    @app.route('/', methods=['GET'])
    def index():
        return render_template('index.html')

    @app.route('/login/', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid credentials', 'danger')
        return render_template('login.html')

    @app.route('/logout/')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    @app.route('/dashboard/', methods=['GET', 'POST'])
    @login_required
    def dashboard():
        # Create link
        if request.method == 'POST':
            long_url = request.form['long_url']
            custom = request.form.get('custom')
            password = request.form.get('password')
            expire = request.form.get('expire')
            one_time = bool(request.form.get('one_time'))
            domain = extract_domain(long_url)
            if domain and Blacklist.query.filter_by(domain=domain).first():
                flash("Domain is blacklisted", "danger")
                return redirect(url_for('dashboard'))
            safe = asyncio.run(check_google_safe_browsing(app.config["GOOGLE_SAFE_BROWSING_API"], long_url))
            if not safe:
                flash("This link is unsafe!", "danger")
                return redirect(url_for('dashboard'))
            if custom:
                if Link.query.filter_by(short_url=custom).first():
                    flash("Custom alias already exists", "danger")
                    return redirect(url_for('dashboard'))
                slug = custom
            else:
                for _ in range(10):
                    slug = random_slug()
                    if not Link.query.filter_by(short_url=slug).first():
                        break
                else:
                    flash("Unable to generate unique slug", "danger")
                    return redirect(url_for('dashboard'))
            link = Link(
                short_url=slug,
                long_url=long_url,
                owner_id=current_user.id,
                expire=datetime.fromisoformat(expire) if expire else None,
                one_time=one_time
            )
            # Always hash password if present!
            if password:
                link.set_password(password)
            db.session.add(link)
            db.session.commit()
            flash(f"Short link created: {request.url_root.rstrip('/')}/{slug}", "success")
            return redirect(url_for('dashboard'))

        # --- Pagination logic ---
        links_page = int(request.args.get('links_page', 1))
        users_page = int(request.args.get('users_page', 1))
        PAGE_SIZE = 5

        # Your links
        your_links_query = Link.query.filter_by(owner_id=current_user.id).order_by(Link.created_at.desc())
        links_count = your_links_query.count()
        links_paged = your_links_query.offset((links_page-1)*PAGE_SIZE).limit(PAGE_SIZE).all()
        links_has_next = links_count > links_page*PAGE_SIZE

        # Users' links (for admin)
        users_links_paged, users_links_has_next = [], False
        users = []
        if current_user.role == 'admin':
            users_links_query = Link.query.filter(Link.owner_id != current_user.id).order_by(Link.created_at.desc())
            users_links_count = users_links_query.count()
            users_links_paged = users_links_query.offset((users_page-1)*PAGE_SIZE).limit(PAGE_SIZE).all()
            users_links_has_next = users_links_count > users_page*PAGE_SIZE
            users = User.query.filter(User.id != current_user.id).order_by(User.created_at.asc()).all()

        return render_template(
            'dashboard.html',
            links_paged=links_paged,
            links_page=links_page,
            links_has_next=links_has_next,
            users_links_paged=users_links_paged,
            users_page=users_page,
            users_links_has_next=users_links_has_next,
            users=users
        )

    @app.route('/dashboard/create_user/', methods=['POST'])
    @login_required
    def dashboard_create_user():
        if current_user.role != 'admin':
            abort(403)
        email = request.form['email']
        password = secrets.token_urlsafe(10)
        api_key = secrets.token_hex(16)
        if User.query.filter_by(email=email).first():
            flash("Email already exists", "danger")
            return redirect(url_for('dashboard'))
        user = User(email=email, role='user', api=api_key)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        org = app.config['SITE_NAME']
        site_url = request.url_root.rstrip('/')
        asyncio.run(send_new_user_email(email, password, org, site_url))
        flash("User created and notified via email", "success")
        return redirect(url_for('dashboard'))

    @app.route('/dashboard/reset_password/<int:user_id>', methods=['POST'])
    @login_required
    def dashboard_reset_password(user_id):
        if current_user.role != 'admin':
            abort(403)
        user = User.query.get_or_404(user_id)
        if user.role == 'admin':
            flash("Cannot reset password for admin", "danger")
            return redirect(url_for('dashboard'))
        password = secrets.token_urlsafe(10)
        user.set_password(password)
        db.session.commit()
        org = app.config['SITE_NAME']
        site_url = request.url_root.rstrip('/')
        asyncio.run(send_reset_password_email(user.email, password, org, site_url))
        flash(f"Password reset and sent to {user.email}", "success")
        return redirect(url_for('dashboard'))

    @app.route('/<slug>', methods=['GET', 'POST'])
    def redirect_slug(slug):
        link = Link.query.filter_by(short_url=slug).first()
        if not link:
            return render_template('404.html'), 404
        if link.expire and datetime.utcnow() > link.expire:
            db.session.delete(link)
            db.session.commit()
            return render_template('404.html'), 404
        if link.password:
            if request.method == 'POST':
                password = request.form['password']
                if not link.check_password(password):
                    return render_template('password_protect.html', slug=slug, error="Wrong password")
            else:
                return render_template('password_protect.html', slug=slug)
        link.clicked += 1
        db.session.commit()
        url = link.long_url
        if link.one_time:
            db.session.delete(link)
            db.session.commit()
        return redirect(url)

    @app.route('/dashboard/delete_link/<slug>', methods=['POST'])
    @login_required
    def dashboard_delete_link(slug):
        link = Link.query.filter_by(short_url=slug, owner_id=current_user.id).first()
        if not link:
            abort(404)
        db.session.delete(link)
        db.session.commit()
        flash("Link deleted", "success")
        return redirect(url_for('dashboard'))

    @app.route('/dashboard/blacklist', methods=['POST'])
    @login_required
    def dashboard_blacklist():
        if current_user.role != "admin":
            abort(403)
        domain = request.form['domain'].lower()
        if not domain:
            flash("Domain is required", "danger")
            return redirect(url_for('dashboard'))
        if Blacklist.query.filter_by(domain=domain).first():
            flash("Domain already blacklisted", "danger")
            return redirect(url_for('dashboard'))
        bl = Blacklist(domain=domain)
        db.session.add(bl)
        db.session.commit()
        flash("Domain added to blacklist", "success")
        return redirect(url_for('dashboard'))

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
