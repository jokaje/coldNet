# Ordner: /coldNet/app/
# Datei: routes.py

from flask import (
    render_template, request, jsonify, Blueprint, redirect, url_for,
    abort, Response, stream_with_context, current_app, send_from_directory, flash
)
from .models import User, Note, Video
from . import db
from flask_login import login_user, logout_user, login_required, current_user
import requests
import json
import os
import re
import shutil
from functools import wraps

main = Blueprint('main', __name__)
REQUESTS_TIMEOUT = (1000, 300)


# --- Hilfsfunktionen ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin: abort(403)
        return f(*args, **kwargs)

    return decorated_function


def allowed_video_file(filename):
    return '.' in filename and os.path.splitext(filename)[1].lower() in current_app.config['ALLOWED_VIDEO_EXTENSIONS']


def get_active_ki_server_url():
    local_url = current_app.config['KI_SERVER_URL_LOCAL']
    public_url = current_app.config['KI_SERVER_URL_PUBLIC']

    try:
        requests.get(f"{local_url}/health", timeout=1)
        current_app.logger.info("KI-Server lokal erreichbar.")
        return local_url
    except requests.exceptions.RequestException:
        current_app.logger.info("KI-Server lokal nicht erreichbar, wechsle zu öffentlicher URL.")
        return public_url


# --- Seiten-Routen ---
@main.route('/')
def index():
    if current_user.is_authenticated: return redirect(url_for('main.dashboard'))
    return render_template('index.html')


@main.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


@main.route('/admin')
@login_required
@admin_required
def admin_panel():
    return render_template('admin.html')


@main.route('/chat')
@login_required
def chat():
    return render_template('chat.html')


@main.route('/notes')
@login_required
def notes():
    return render_template('notes.html')


@main.route('/video-stream')
@login_required
def video_stream():
    search_query = request.args.get('search', '').lower()
    selected_category = request.args.get('category', "Alle")
    query = Video.query
    if search_query:
        query = query.filter(Video.title.ilike(f'%{search_query}%'))
    if selected_category != "Alle":
        query = query.filter_by(category=selected_category)

    all_videos = query.order_by(Video.category, Video.title).all()

    categories_from_db = db.session.query(Video.category).distinct().order_by(Video.category).all()
    categories = ["Alle"] + [cat[0] for cat in categories_from_db if cat[0]]

    videos_categorized = {}
    for video in all_videos:
        cat = video.category or 'Unkategorisiert'
        if cat not in videos_categorized:
            videos_categorized[cat] = []
        videos_categorized[cat].append(video)

    return render_template('video_stream.html', videos_categorized=videos_categorized, categories=categories,
                           selected_category=selected_category, search_query=request.args.get('search', ''))


@main.route('/video_files/<path:filepath>')
@login_required
def serve_video_file(filepath):
    video_folder = current_app.config['VIDEO_FOLDER']
    return send_from_directory(video_folder, filepath, as_attachment=False)


@main.route('/scan-videos')
@login_required
@admin_required
def scan_videos():
    base_path = current_app.config['VIDEO_FOLDER']
    thumbnail_dest_folder = current_app.config['THUMBNAIL_FOLDER']

    if not os.path.exists(base_path):
        flash(f"Video-Ordner {base_path} nicht gefunden!", "error")
        return redirect(url_for('main.video_stream'))

    db_videos = {v.filepath: v for v in Video.query.all()}
    fs_videos = set()
    videos_added = 0
    thumbnails_found = 0
    metadata_found = 0

    for dirpath, _, filenames in os.walk(base_path):
        image_files = {f.lower() for f in filenames if f.lower().endswith(('.jpg', '.png', '.webp'))}
        json_files = {f.lower() for f in filenames if f.lower().endswith('.json')}

        for filename in filenames:
            if not allowed_video_file(filename):
                continue

            full_path = os.path.join(dirpath, filename)
            relative_path = os.path.relpath(full_path, base_path).replace('\\', '/')
            fs_videos.add(relative_path)

            if relative_path not in db_videos:
                video_name_base = os.path.splitext(filename)[0]

                metadata = {}
                potential_json_file = f"{video_name_base.lower()}.json"
                if potential_json_file in json_files:
                    original_json_filename = next((f for f in filenames if f.lower() == potential_json_file), None)
                    if original_json_filename:
                        json_path = os.path.join(dirpath, original_json_filename)
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                metadata = json.load(f)
                            metadata_found += 1
                        except Exception as e:
                            current_app.logger.error(f"Konnte JSON-Datei nicht lesen {json_path}: {e}")

                thumbnail_url = None
                for img_ext in ['.jpg', '.png', '.webp']:
                    potential_thumb_name = f"{video_name_base.lower()}{img_ext}"
                    if potential_thumb_name in image_files:
                        original_thumb_filename = next((f for f in filenames if f.lower() == potential_thumb_name),
                                                       None)
                        if original_thumb_filename:
                            source_thumb_path = os.path.join(dirpath, original_thumb_filename)
                            unique_thumb_name = f"{video_name_base}_{hash(relative_path)}{img_ext}"
                            dest_thumb_path = os.path.join(thumbnail_dest_folder, unique_thumb_name)
                            try:
                                shutil.copy2(source_thumb_path, dest_thumb_path)
                                thumbnail_url = url_for('static', filename=f'thumbnails/{unique_thumb_name}',
                                                        _external=False)
                                thumbnails_found += 1
                                break
                            except Exception as e:
                                current_app.logger.error(f"Konnte Thumbnail nicht kopieren: {e}")

                title = metadata.get('title', video_name_base.replace('.', ' ').replace('_', ' ').strip())
                description = metadata.get('description', 'Keine Beschreibung verfügbar.')
                year = metadata.get('year')
                genre = metadata.get('genre')
                category = os.path.basename(dirpath) if dirpath != base_path else "Unkategorisiert"

                new_video = Video(
                    filepath=relative_path,
                    filename=filename,
                    title=title,
                    category=category,
                    year=year,
                    genre=genre,
                    description=description,
                    thumbnail_url=thumbnail_url
                )
                db.session.add(new_video)
                videos_added += 1

    videos_to_remove = set(db_videos.keys()) - fs_videos
    if videos_to_remove:
        for video_path in videos_to_remove:
            video_obj = db_videos.get(video_path)
            if video_obj and video_obj.thumbnail_url:
                thumb_filename = os.path.basename(video_obj.thumbnail_url)
                thumb_disk_path = os.path.join(thumbnail_dest_folder, thumb_filename)
                if os.path.exists(thumb_disk_path):
                    try:
                        os.remove(thumb_disk_path)
                    except OSError as e:
                        current_app.logger.error(f"Konnte Thumbnail nicht löschen {thumb_disk_path}: {e}")

        Video.query.filter(Video.filepath.in_(videos_to_remove)).delete(synchronize_session=False)

    db.session.commit()
    flash(
        f"Scan abgeschlossen. {videos_added} neue Videos, {metadata_found} Metadaten, {thumbnails_found} Thumbnails und {len(videos_to_remove)} entfernte Einträge.",
        "success")
    return redirect(url_for('main.video_stream'))


# --- API-Routen ---
@main.route('/api/register', methods=['POST'])
def register():
    data = request.get_json();
    if not data or 'email' not in data or 'password' not in data: return jsonify({'error': 'Fehlende Daten'}), 400
    if User.query.filter_by(email=data['email']).first(): return jsonify({'error': 'E-Mail bereits vergeben.'}), 409
    is_first_user = User.query.first() is None
    new_user = User(email=data['email'], is_admin=is_first_user)
    new_user.set_password(data['password'])
    db.session.add(new_user);
    db.session.commit()
    msg = 'Registrierung erfolgreich.' + (' Du bist Admin.' if is_first_user else '')
    return jsonify({'message': msg}), 201


@main.route('/api/login', methods=['POST'])
def login():
    data = request.get_json();
    if not data or 'email' not in data or 'password' not in data: return jsonify({'error': 'Fehlende Daten'}), 400
    user = User.query.filter_by(email=data['email']).first()
    if user and user.check_password(data['password']):
        login_user(user, remember=True)
        return jsonify({'message': 'Anmeldung erfolgreich.', 'is_admin': user.is_admin}), 200
    return jsonify({'error': 'Ungültige Anmeldedaten.'}), 401


@main.route('/api/logout', methods=['POST'])
@login_required
def logout():
    logout_user();
    return jsonify({'message': 'Abmeldung erfolgreich.'}), 200


@main.route('/api/admin/status', methods=['GET'])
@login_required
@admin_required
def get_ki_server_status():
    try:
        ki_server_url = get_active_ki_server_url()
        health_response = requests.get(f"{ki_server_url}/health", timeout=REQUESTS_TIMEOUT[0])
        health_response.raise_for_status()
        models_response = requests.get(f"{ki_server_url}/models", timeout=REQUESTS_TIMEOUT[0])
        models_response.raise_for_status()
        return jsonify(
            {'ki_status': health_response.json(), 'available_models': models_response.json().get('models', [])}), 200
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'KI-Server nicht erreichbar: {e}'}), 502


@main.route('/api/admin/load_model', methods=['POST'])
@login_required
@admin_required
def load_ki_model():
    data = request.get_json();
    if not data or 'model' not in data: return jsonify({'error': 'Modellname fehlt'}), 400
    try:
        ki_server_url = get_active_ki_server_url()
        response = requests.post(f"{ki_server_url}/load_model", json={'model': data['model']},
                                 timeout=REQUESTS_TIMEOUT[1])
        response.raise_for_status()
        return jsonify(response.json()), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Fehler bei Kommunikation mit KI-Server: {e}'}), 502


@main.route('/api/notes', methods=['GET'])
@login_required
def get_notes():
    notes = Note.query.filter_by(user_id=current_user.id).order_by(Note.created_at.desc()).all()
    return jsonify(
        [{'id': note.id, 'title': note.title, 'content': note.content, 'created_at': note.created_at.isoformat()} for
         note in notes])


@main.route('/api/notes', methods=['POST'])
@login_required
def create_note():
    data = request.get_json()
    if not data or 'title' not in data or 'content' not in data: return jsonify(
        {'error': 'Titel und Inhalt sind erforderlich'}), 400
    new_note = Note(title=data['title'], content=data['content'], author=current_user)
    db.session.add(new_note);
    db.session.commit()
    return jsonify({'message': 'Notiz erstellt', 'id': new_note.id}), 201


@main.route('/api/notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.author != current_user: abort(403)
    db.session.delete(note);
    db.session.commit()
    return jsonify({'message': 'Notiz gelöscht'})


@main.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.get_json()
    if not data or 'messages' not in data or not data['messages']:
        return jsonify({'error': 'Fehlende Nachrichten'}), 400
    try:
        ki_server_url = get_active_ki_server_url()
        health_response = requests.get(f"{ki_server_url}/health", timeout=REQUESTS_TIMEOUT[0])
        ki_status = health_response.json()
        loaded_model = ki_status.get('loaded_model_name')
        if not loaded_model: return jsonify({'error': 'Auf dem KI-Server ist kein Modell geladen.'}), 503

        # --- SCHRITT 1: Analyse der Benutzerabsicht (Intent) ---
        # Hier wird eine schnelle Anfrage an die KI gesendet, um herauszufinden,
        # ob sich die Nachricht auf Notizen bezieht.
        # Deswegen wird hier "stream: False" gesetzt. Das ist gewollt und korrekt.
        current_app.logger.info("Schritt 1: Prüfe Chat-Absicht (Intent). Stream ist absichtlich 'False'.")
        last_user_message = data['messages'][-1]['content']
        router_system_prompt = "Antworte NUR mit 'NOTIZEN' oder 'ALLGEMEIN'."
        router_user_prompt = f"Analyse: '{last_user_message}'. Bezieht es sich auf Notizen, Aufgaben, Listen oder Erinnerungen?"
        router_payload = {"model": loaded_model, "messages": [{"role": "system", "content": router_system_prompt},
                                                              {"role": "user", "content": router_user_prompt}],
                          "stream": False}  # WICHTIG: Kein Stream für die schnelle Intent-Analyse
        router_response = requests.post(f"{ki_server_url}/api/chat", json=router_payload, timeout=REQUESTS_TIMEOUT[0])
        intent = router_response.json().get('message', {}).get('content', 'ALLGEMEIN').strip().upper()
        current_app.logger.info(f"Chat-Absicht erkannt: {intent}")

        # --- SCHRITT 2: Vorbereitung und Senden der finalen Anfrage ---
        messages_to_send = data['messages']
        # Wenn die Absicht 'NOTIZEN' ist, füge relevanten Kontext hinzu.
        if "NOTIZEN" in intent:
            current_app.logger.info("Füge Notizen als Kontext zur Anfrage hinzu.")
            user_notes = Note.query.filter_by(user_id=current_user.id).order_by(Note.created_at.desc()).limit(5).all()
            if user_notes:
                notes_context = "Kontext aus Notizen:\n" + "\n".join(
                    [f"- Titel: '{n.title}', Inhalt: '{n.content[:100]}...'" for n in user_notes])
                messages_to_send.insert(-1, {"role": "system", "content": notes_context})

        # Dies ist die finale Anfrage, die die sichtbare Antwort an den Benutzer generiert.
        # Hier wird "stream: True" gesetzt, damit die Antwort Wort für Wort im Chat erscheint.
        current_app.logger.info("Schritt 2: Sende finale Anfrage an die KI. Stream ist 'True'.")
        final_payload = {"model": loaded_model, "messages": messages_to_send, "stream": True}
        ki_response = requests.post(f"{ki_server_url}/api/chat", json=final_payload, stream=True,
                                    timeout=REQUESTS_TIMEOUT[1])
        ki_response.raise_for_status()

        # Streamt die Antwort der KI an den Browser
        def generate():
            for chunk in ki_response.iter_content(chunk_size=1024): yield chunk

        return Response(stream_with_context(generate()), content_type=ki_response.headers['Content-Type'])

    except Exception as e:
        current_app.logger.error(f"Fehler in /api/chat: {e}")
        return jsonify({'error': f'Ein interner Fehler ist aufgetreten: {e}'}), 500
