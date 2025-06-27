# Ordner: /coldNet/app/
# Datei: __init__.py

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
import shutil  # Import für Dateioperationen

# --- Initialisierung der Erweiterungen ---
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'main.login'
login_manager.login_message_category = 'info'
migrate = Migrate()


def create_app():
    """Erstellt und konfiguriert eine Instanz der Flask-Anwendung."""
    app = Flask(__name__, instance_relative_config=True)

    # --- Konfiguration ---
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dein-sehr-geheimer-und-schwer-zu-erratender-schluessel')

    if not os.path.exists(app.instance_path):
        os.makedirs(app.instance_path)

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(app.instance_path, "coldnet.db")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    app.config['KI_SERVER_URL_LOCAL'] = 'http://192.168.86.206:8080'
    app.config['KI_SERVER_URL_PUBLIC'] = 'http://coldnet.dedyn.io:80'

    # --- Konfiguration für den Video-Dienst ---
    VIDEO_BASE_PATH = '/mnt/nas_videos/jokaja/Unreal Engine/videos'
    app.config['VIDEO_FOLDER'] = VIDEO_BASE_PATH
    app.config['ALLOWED_VIDEO_EXTENSIONS'] = {'.mp4', '.webm', '.ogg', '.mkv'}

    # --- Konfiguration für Thumbnails ---
    # Dieser Ordner wird innerhalb des 'static'-Verzeichnisses erstellt.
    # Wichtig: Die Konfiguration wird hier gesetzt, damit sie für alle Teile der App verfügbar ist.
    thumbnail_folder_path = os.path.join(app.static_folder, 'thumbnails')
    app.config['THUMBNAIL_FOLDER'] = thumbnail_folder_path
    if not os.path.exists(thumbnail_folder_path):
        os.makedirs(thumbnail_folder_path)

    # --- Erweiterungen mit der App verbinden ---
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # --- Blueprints (Routen) registrieren ---
    # Dies geschieht, nachdem die gesamte Konfiguration abgeschlossen ist.
    from .routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    # --- Erstellt die Datenbanktabellen, falls sie nicht existieren ---
    with app.app_context():
        db.create_all()

    return app
