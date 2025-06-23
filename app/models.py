# Ordner: /coldNet/app/
# Datei: models.py

from . import db, login_manager
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False) # Länge für moderne Hashes erhöht
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.relationship('Note', backref='author', lazy=True)

    def __repr__(self):
        return f"User('{self.email}', Admin: {self.is_admin})"
    def set_password(self, password):
        self.password = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password, password)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f"Note('{self.title}', '{self.created_at}')"

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filepath = db.Column(db.String(1000), unique=True, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255))
    category = db.Column(db.String(100))
    genre = db.Column(db.String(100))
    year = db.Column(db.Integer)
    description = db.Column(db.Text)
    thumbnail_url = db.Column(db.String(1000))

    def __repr__(self):
        return f"Video('{self.title}', '{self.filename}')"
