from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import User, db

login_manager = LoginManager()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))