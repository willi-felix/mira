from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy.sql import func
from passlib.hash import bcrypt
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default="user")  # admin/user
    api = db.Column(db.String(32), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())

    links = db.relationship('Link', backref='owner', lazy=True)

    def set_password(self, raw_password):
        self.password = bcrypt.hash(raw_password)
    def check_password(self, raw_password):
        if not self.password:
            return True
        return bcrypt.verify(raw_password, self.password)

class Link(db.Model):
    __tablename__ = 'links'
    id = db.Column(db.Integer, primary_key=True)
    short_url = db.Column(db.String(32), unique=True, nullable=False)
    long_url = db.Column(db.Text, nullable=False)
    clicked = db.Column(db.Integer, default=0)
    password = db.Column(db.String(255), nullable=True)
    expire = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    one_time = db.Column(db.Boolean, nullable=False, default=False)

    def set_password(self, password):
        # For link password (hash if not None/empty)
        self.password = bcrypt.hash(password) if password else None

    def check_password(self, password):
        # Defensive: avoid ValueError if self.password is not a valid bcrypt hash
        if not self.password:
            return False
        try:
            return bcrypt.verify(password, self.password)
        except Exception:
            return False

class Blacklist(db.Model):
    __tablename__ = 'blacklist'
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255), unique=True, nullable=False)
