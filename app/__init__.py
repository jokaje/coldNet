import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate

# --- Initialisierung der Erweiterungen (OHNE Bcrypt) ---
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'main.login'
login_manager.login_message_category = 'info'
migrate = Migrate()


def create_app():
    """Erstellt und konfiguriert eine Instanz der Flask-Anwendung."""
    app = Flask(__name__, instance_relative_config=True)

    # --- Konfiguration ---
    # WICHTIG: Für den Produktivbetrieb sollte dieser Schlüssel aus einer Umgebungsvariable geladen werden
    app.config['SECRET_KEY'] = 'dein-sehr-geheimer-und-schwer-zu-erratender-schluessel'

    if not os.path.exists(app.instance_path):
        os.makedirs(app.instance_path)

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(app.instance_path, "coldnet.db")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # --- NEU: Konfiguration der KI-Server-Adressen ---
    # Die lokale Adresse für schnelle Verbindungen im Heimnetzwerk
    app.config['KI_SERVER_URL_LOCAL'] = 'http://192.168.86.206:8080'
    # Die öffentliche Adresse für den Zugriff von außerhalb
    app.config['KI_SERVER_URL_PUBLIC'] = 'http://coldnet.dedyn.io:80'


    # Konfiguration für den Video-Dienst
    # Passe diesen Pfad an den Speicherort deiner Videos an.
    VIDEO_BASE_PATH = '/mnt/nas_videos/jokaja/Unreal Engine/videos'
    app.config['VIDEO_FOLDER'] = VIDEO_BASE_PATH
    app.config['ALLOWED_VIDEO_EXTENSIONS'] = {'.mp4', '.webm', '.ogg', '.mkv'}

    # --- Erweiterungen mit der App verbinden ---
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # --- Blueprints (Routen) registrieren ---
    from .routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    # --- Erstellt die Datenbanktabellen, falls sie nicht existieren ---
    with app.app_context():
        db.create_all()

    return app
