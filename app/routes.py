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
import random
from functools import wraps

main = Blueprint('main', __name__)
# Standard-Timeout für die meisten Anfragen
REQUESTS_TIMEOUT = (10, 300) 
# Längerer Timeout speziell für die Tool-Dispatch-Anfrage
TOOL_DISPATCH_TIMEOUT = 30


# --- KI-Werkzeuge ---

def _tool_create_note(title: str, content: str):
    """
    Erstellt eine neue Notiz für den aktuell angemeldeten Benutzer.
    """
    if not title or not content:
        return {"status": "error", "message": "Titel und Inhalt sind für die Notiz erforderlich."}
    
    try:
        new_note = Note(title=title, content=content, author=current_user)
        db.session.add(new_note)
        db.session.commit()
        confirmations = [
            f"Alles klar, ich habe die Notiz '{title}' für dich gespeichert.",
            f"Erledigt! Deine Notiz '{title}' wurde angelegt.",
            f"Verstanden, ich habe es für dich unter '{title}' notiert."
        ]
        return {"status": "success", "message": random.choice(confirmations)}
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Erstellen der Notiz: {e}")
        return {"status": "error", "message": "Ein interner Fehler hat das Speichern der Notiz verhindert."}

def _tool_search_notes(query: str):
    """
    Durchsucht die Notizen des aktuell angemeldeten Benutzers.
    Wird auch verwendet, wenn der Benutzer allgemeine Fragen stellt,
    um zu prüfen, ob relevante Notizen existieren.
    """
    if not query:
        return {"status": "error", "message": "Ein Suchbegriff ist erforderlich."}
        
    try:
        search_term = f"%{query}%"
        notes = Note.query.filter(
            Note.user_id == current_user.id,
            db.or_(
                Note.title.ilike(search_term),
                Note.content.ilike(search_term)
            )
        ).order_by(Note.created_at.desc()).limit(5).all()

        if not notes:
            return {"status": "success", "message": f"Ich konnte keine Notizen zum Thema '{query}' finden."}

        result_string = f"Ich habe {len(notes)} relevante Notiz(en) zu '{query}' gefunden:\n\n"
        for i, note in enumerate(notes, 1):
            content_preview = note.content[:150] + "..." if len(note.content) > 150 else note.content
            result_string += f"**{i}. {note.title}** (ID: {note.id})\n{content_preview}\n\n"
                    
        result_string += "---\n*Soll ich dir eine bestimmte Notiz vollständig anzeigen?*"
        return {"status": "success", "message": result_string}
    except Exception as e:
        current_app.logger.error(f"Fehler beim Durchsuchen der Notizen: {e}")
        return {"status": "error", "message": "Ein interner Fehler hat das Durchsuchen der Notizen verhindert."}

def _tool_list_notes(limit: int = 5, offset: int = 0):
    """
    Listet alle Notizen des Benutzers auf mit Paginierung.
    """
    try:
        # KORREKTUR: Fängt None-Werte ab und setzt sie auf Standardwerte.
        limit = limit if limit is not None else 5
        offset = offset if offset is not None else 0

        total_notes = Note.query.filter_by(user_id=current_user.id).count()
        notes = Note.query.filter_by(user_id=current_user.id)\
                         .order_by(Note.created_at.desc())\
                         .offset(offset)\
                         .limit(limit)\
                         .all()

        if not notes:
            return {"status": "success", "message": "Du hast noch keine Notizen erstellt." if offset == 0 else "Keine weiteren Notizen vorhanden."}

        result_string = f"Hier sind deine Notizen ({offset + 1}-{offset + len(notes)} von {total_notes}):\n\n"
                
        for i, note in enumerate(notes, 1):
            content_preview = note.content[:100] + "..." if len(note.content) > 100 else note.content
            result_string += f"**{offset + i}. {note.title}** (ID: {note.id})\n{content_preview}\n*Erstellt: {note.created_at.strftime('%d.%m.%Y %H:%M')}*\n\n"

        if offset + len(notes) < total_notes:
            remaining = total_notes - (offset + len(notes))
            result_string += f"---\n*Du hast noch {remaining} weitere Notiz(en). Soll ich die nächsten anzeigen?*"
            
        return {"status": "success", "message": result_string}
    except Exception as e:
        current_app.logger.error(f"Fehler beim Auflisten der Notizen: {e}")
        return {"status": "error", "message": "Ein Fehler ist beim Laden deiner Notizen aufgetreten."}

def _tool_get_note_details(note_id: int):
    """
    Zeigt die vollständigen Details einer spezifischen Notiz an.
    """
    try:
        # KORREKTUR: Stellt sicher, dass note_id eine Zahl ist.
        if not isinstance(note_id, int):
             return {"status": "error", "message": f"Die ID der Notiz muss eine Zahl sein."}
        note = Note.query.filter_by(id=note_id, user_id=current_user.id).first()
                
        if not note:
            return {"status": "error", "message": f"Notiz mit ID {note_id} wurde nicht gefunden."}

        result_string = f"**{note.title}**\n\n{note.content}\n\n*Erstellt: {note.created_at.strftime('%d.%m.%Y um %H:%M Uhr')}*"
        return {"status": "success", "message": result_string}
    except Exception as e:
        current_app.logger.error(f"Fehler beim Laden der Notiz-Details: {e}")
        return {"status": "error", "message": "Ein Fehler ist beim Laden der Notiz aufgetreten."}

def _tool_delete_note(note_id: int):
    """
    Löscht eine spezifische Notiz des Benutzers.
    """
    try:
        # KORREKTUR: Stellt sicher, dass note_id eine Zahl ist.
        if not isinstance(note_id, int):
             return {"status": "error", "message": f"Die ID der Notiz muss eine Zahl sein."}
        note = Note.query.filter_by(id=note_id, user_id=current_user.id).first()
                
        if not note:
            return {"status": "error", "message": f"Notiz mit ID {note_id} wurde nicht gefunden."}

        note_title = note.title
        db.session.delete(note)
        db.session.commit()
                
        confirmations = [
            f"Die Notiz '{note_title}' wurde erfolgreich gelöscht.",
            f"Erledigt! Ich habe '{note_title}' für dich entfernt.",
        ]
        return {"status": "success", "message": random.choice(confirmations)}
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Löschen der Notiz: {e}")
        return {"status": "error", "message": "Ein Fehler ist beim Löschen der Notiz aufgetreten."}


AVAILABLE_TOOLS = {
    "create_note": {
        "description": "Erstellt eine neue Notiz, einen Gedanken oder eine Liste. Wird verwendet, wenn der Benutzer sagt 'notiere', 'schreib auf', 'erstell eine Notiz' oder ähnliches. Extrahiert immer einen Titel und den dazugehörigen Inhalt.",
        "function": _tool_create_note,
        "parameters": [
            {"name": "title", "type": "string", "description": "Der Titel der Notiz, z.B. 'Einkaufsliste'."},
            {"name": "content", "type": "string", "description": "Der eigentliche Text der Notiz, z.B. 'Milch, Brot, Eier'."}
        ]
    },
    "search_notes": {
        "description": "Durchsucht die persönlichen Notizen des Benutzers. Wird verwendet, wenn der Benutzer fragt 'suche in meinen Notizen', 'was weiß ich über', 'finde meine Notiz zu' usw.",
        "function": _tool_search_notes,
        "parameters": [
            {"name": "query", "type": "string", "description": "Der Suchbegriff, nach dem in den Notizen gesucht werden soll, z.B. 'Urlaub'."}
        ]
    },
    "list_notes": {
        "description": "Listet alle Notizen des Benutzers auf. Wird verwendet bei Fragen wie 'welche Notizen habe ich', 'zeige meine Notizen', 'liste meine Notizen auf'. Unterstützt Paginierung.",
        "function": _tool_list_notes,
        "parameters": [
            {"name": "limit", "type": "integer", "description": "Anzahl der Notizen pro Seite (Standard: 5)."},
            {"name": "offset", "type": "integer", "description": "Startposition für Paginierung (Standard: 0)."}
        ]
    },
    "get_note_details": {
        "description": "Zeigt die vollständigen Details einer spezifischen Notiz an. Wird verwendet, wenn der Benutzer nach einer bestimmten Notiz fragt oder mehr Details sehen möchte.",
        "function": _tool_get_note_details,
        "parameters": [
            {"name": "note_id", "type": "integer", "description": "Die ID der Notiz, die angezeigt werden soll."}
        ]
    },
    "delete_note": {
        "description": "Löscht eine spezifische Notiz. Wird verwendet, wenn der Benutzer sagt 'lösche Notiz', 'entferne die Notiz' oder ähnliches.",
        "function": _tool_delete_note,
        "parameters": [
            {"name": "note_id", "type": "integer", "description": "Die ID der Notiz, die gelöscht werden soll."}
        ]
    }
}


# --- Hilfsfunktionen (unverändert) ---
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
        return local_url
    except requests.exceptions.RequestException:
        return public_url

# --- Seiten-Routen (unverändert) ---
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
    base_path, thumbnail_dest_folder = current_app.config['VIDEO_FOLDER'], current_app.config['THUMBNAIL_FOLDER']
    if not os.path.exists(base_path): flash(f"Video-Ordner {base_path} nicht gefunden!", "error"); return redirect(url_for('main.video_stream'))
    db_videos = {v.filepath: v for v in Video.query.all()}; fs_videos = set(); videos_added, thumbnails_found, metadata_found = 0, 0, 0
    for dirpath, _, filenames in os.walk(base_path):
        image_files = {f.lower() for f in filenames if f.lower().endswith(('.jpg', '.png', '.webp'))}; json_files = {f.lower() for f in filenames if f.lower().endswith('.json')}
        for filename in filenames:
            if not allowed_video_file(filename): continue
            full_path, relative_path = os.path.join(dirpath, filename), os.path.relpath(full_path, base_path).replace('\\', '/')
            fs_videos.add(relative_path)
            if relative_path not in db_videos:
                video_name_base = os.path.splitext(filename)[0]; metadata, thumbnail_url = {}, None
                potential_json_file = f"{video_name_base.lower()}.json"
                if potential_json_file in json_files:
                    original_json_filename = next((f for f in filenames if f.lower() == potential_json_file), None)
                    if original_json_filename:
                        try:
                            with open(os.path.join(dirpath, original_json_filename), 'r', encoding='utf-8') as f: metadata = json.load(f)
                            metadata_found += 1
                        except Exception as e: current_app.logger.error(f"JSON-Lesefehler: {e}")
                for img_ext in ['.jpg', '.png', '.webp']:
                    potential_thumb_name = f"{video_name_base.lower()}{img_ext}"
                    if potential_thumb_name in image_files:
                        original_thumb_filename = next((f for f in filenames if f.lower() == potential_thumb_name), None)
                        if original_thumb_filename:
                            try:
                                unique_thumb_name = f"{video_name_base}_{hash(relative_path)}{img_ext}"; shutil.copy2(os.path.join(dirpath, original_thumb_filename), os.path.join(thumbnail_dest_folder, unique_thumb_name))
                                thumbnail_url = url_for('static', filename=f'thumbnails/{unique_thumb_name}', _external=False); thumbnails_found += 1; break
                            except Exception as e: current_app.logger.error(f"Thumbnail-Kopierfehler: {e}")
                new_video = Video(filepath=relative_path, filename=filename, title=metadata.get('title', video_name_base.replace('.', ' ').strip()), category=os.path.basename(dirpath) if dirpath != base_path else "Unkategorisiert", year=metadata.get('year'), genre=metadata.get('genre'), description=metadata.get('description', 'Keine Beschreibung verfügbar.'), thumbnail_url=thumbnail_url)
                db.session.add(new_video); videos_added += 1
    videos_to_remove = set(db_videos.keys()) - fs_videos
    if videos_to_remove:
        for video_path in videos_to_remove:
            video_obj = db_videos.get(video_path)
            if video_obj and video_obj.thumbnail_url:
                try: os.remove(os.path.join(thumbnail_dest_folder, os.path.basename(video_obj.thumbnail_url)))
                except OSError as e: current_app.logger.error(f"Thumbnail-Löschfehler: {e}")
        Video.query.filter(Video.filepath.in_(videos_to_remove)).delete(synchronize_session=False)
    db.session.commit()
    flash(f"Scan abgeschlossen. {videos_added} neue Videos, {metadata_found} Metadaten, {thumbnails_found} Thumbnails, {len(videos_to_remove)} entfernte Einträge.", "success")
    return redirect(url_for('main.video_stream'))

# --- API-Routen (unverändert) ---
@main.route('/api/register', methods=['POST'])
def register():
    data=request.get_json();
    if not data or'email'not in data or'password'not in data:return jsonify({'error':'Fehlende Daten'}),400
    if User.query.filter_by(email=data['email']).first():return jsonify({'error':'E-Mail bereits vergeben.'}),409
    is_first_user=User.query.first()is None;new_user=User(email=data['email'],is_admin=is_first_user);new_user.set_password(data['password']);db.session.add(new_user);db.session.commit();msg='Registrierung erfolgreich.'+(' Du bist Admin.'if is_first_user else'');return jsonify({'message':msg}),201

@main.route('/api/login', methods=['POST'])
def login():
    data=request.get_json();
    if not data or'email'not in data or'password'not in data:return jsonify({'error':'Fehlende Daten'}),400
    user=User.query.filter_by(email=data['email']).first()
    if user and user.check_password(data['password']):login_user(user,remember=True);return jsonify({'message':'Anmeldung erfolgreich.','is_admin':user.is_admin}),200
    return jsonify({'error':'Ungültige Anmeldedaten.'}),401

@main.route('/api/logout',methods=['POST'])
@login_required
def logout():logout_user();return jsonify({'message':'Abmeldung erfolgreich.'}),200

@main.route('/api/admin/status',methods=['GET'])
@login_required
@admin_required
def get_ki_server_status():
    try:
        ki_server_url=get_active_ki_server_url();health_response=requests.get(f"{ki_server_url}/health",timeout=REQUESTS_TIMEOUT[0]);health_response.raise_for_status();models_response=requests.get(f"{ki_server_url}/models",timeout=REQUESTS_TIMEOUT[0]);models_response.raise_for_status();return jsonify({'ki_status':health_response.json(),'available_models':models_response.json().get('models',[])}),200
    except requests.exceptions.RequestException as e:return jsonify({'error':f'KI-Server nicht erreichbar: {e}'}),502

@main.route('/api/admin/load_model',methods=['POST'])
@login_required
@admin_required
def load_ki_model():
    data=request.get_json();
    if not data or'model'not in data:return jsonify({'error':'Modellname fehlt'}),400
    try:
        ki_server_url=get_active_ki_server_url();response=requests.post(f"{ki_server_url}/load_model",json={'model':data['model']},timeout=REQUESTS_TIMEOUT[1]);response.raise_for_status();return jsonify(response.json()),response.status_code
    except requests.exceptions.RequestException as e:return jsonify({'error':f'Fehler bei Kommunikation mit KI-Server: {e}'}),502

@main.route('/api/notes', methods=['GET'])
@login_required
def get_notes():
    notes = Note.query.filter_by(user_id=current_user.id).order_by(Note.created_at.desc()).all()
    return jsonify([{'id': note.id, 'title': note.title, 'content': note.content, 'created_at': note.created_at.isoformat()} for note in notes])

@main.route('/api/notes', methods=['POST'])
@login_required
def create_note_api():
    data = request.get_json()
    if not data or 'title' not in data or 'content' not in data: return jsonify({'error': 'Titel und Inhalt sind erforderlich'}), 400
    result = _tool_create_note(data['title'], data['content'])
    return jsonify(result)

@main.route('/api/notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_note(note_id):
    note=Note.query.get_or_404(note_id)
    if note.author!=current_user:abort(403)
    db.session.delete(note);db.session.commit()
    return jsonify({'message':'Notiz gelöscht'})


# --- FINALE CHAT-ROUTE ---
@main.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.get_json()
    if not data or 'messages' not in data or not data['messages']:
        return jsonify({'error': 'Fehlende Nachrichten'}), 400

    try:
        ki_server_url = get_active_ki_server_url()
        loaded_model = requests.get(f"{ki_server_url}/health").json().get('loaded_model_name')
        if not loaded_model:
            return jsonify({'error': 'Kein Modell auf dem KI-Server geladen.'}), 503

        user_history = data['messages']
        last_user_message = user_history[-1]['content']
        
        # --- 1. SCHRITT: Werkzeug-Dispatcher ---
        tools_for_prompt = {name: {k: v for k, v in tool_data.items() if k != 'function'} for name, tool_data in AVAILABLE_TOOLS.items()}
        tool_system_prompt = f"""Du bist ein Tool-Dispatcher. Deine Aufgabe ist es, die Benutzeranfrage zu analysieren und das passende Werkzeug auszuwählen.
**WICHTIGE REGELN:**
1. Bei JEDER Benutzeranfrage prüfst du ZUERST, ob sie mit Notizen zusammenhängt.
2. Auch bei allgemeinen Fragen sollst du prüfen, ob der Benutzer relevante Notizen haben könnte.
3. Antworte **ausschließlich** mit einem JSON-Objekt.
4. Wenn ein Werkzeug passt: `{{"tool_name": "name", "arguments": {{"arg1": "wert1"}}}}`
5. Wenn KEIN Werkzeug passt: `{{"tool_name": "none"}}`

**BEISPIELE FÜR WERKZEUG-VERWENDUNG:**
- "Welche Notizen habe ich?" → list_notes
- "Was weiß ich über Urlaub?" → search_notes mit query="Urlaub"
- "Notiere dir: Milch kaufen" → create_note
- "Zeige mir Notiz 5" → get_note_details mit note_id=5
- "Lösche die Notiz mit ID 3" → delete_note mit note_id=3
- "Hast du Infos über Python?" → search_notes mit query="Python"

**VERFÜGBARE WERKZEUGE:**
{json.dumps(tools_for_prompt, indent=2, ensure_ascii=False)}
"""
        
        tool_check_payload = {"model": loaded_model, "messages": [{"role": "system", "content": tool_system_prompt}, {"role": "user", "content": last_user_message}], "stream": False, "temperature": 0.0}
        # KORREKTUR: Längerer Timeout für diese spezifische Anfrage
        tool_response = requests.post(f"{ki_server_url}/api/chat", json=tool_check_payload, timeout=TOOL_DISPATCH_TIMEOUT)
        tool_response_content = tool_response.json().get('message', {}).get('content', '')
        current_app.logger.info(f"Dispatcher KI-Antwort: '{tool_response_content}'")

        # --- 2. SCHRITT: Werkzeug ausführen oder normales Gespräch ---
        tool_name = None
        try:
            json_match = re.search(r'\{.*\}', tool_response_content, re.DOTALL)
            if json_match:
                call_data = json.loads(json_match.group())
                tool_name = call_data.get('tool_name')
        except (json.JSONDecodeError, KeyError) as e:
            current_app.logger.error(f"Fehler beim Parsen der Dispatcher-Antwort: {e}. Fahre mit normalem Chat fort.")
            tool_name = 'none'

        # Fall 1: Ein Werkzeug wurde ausgewählt
        if tool_name and tool_name != 'none':
            tool_args = call_data.get('arguments', {})
            if tool_name in AVAILABLE_TOOLS:
                tool_function = AVAILABLE_TOOLS[tool_name]["function"]
                func_params = AVAILABLE_TOOLS[tool_name].get("parameters", [])
                final_args = {p['name']: tool_args.get(p['name']) for p in func_params if p['name'] in tool_args}

                tool_result = tool_function(**final_args)
                
                def tool_result_stream():
                    sse_data = {"message": {"content": tool_result.get("message", "Ein unerwarteter Fehler im Werkzeug ist aufgetreten.")}}
                    yield f"data: {json.dumps(sse_data)}\n\n"
                return Response(tool_result_stream(), content_type='text/event-stream')
            else:
                def error_stream():
                    sse_data = {"message": {"content": f"Die KI wollte ein unbekanntes Werkzeug namens '{tool_name}' verwenden."}}
                    yield f"data: {json.dumps(sse_data)}\n\n"
                return Response(error_stream(), content_type='text/event-stream')

        # Fall 2: Kein Werkzeug, normales Gespräch
        else:
            final_system_prompt = "Du bist coldBot, ein freundlicher und hilfsbereiter KI-Assistent. Antworte immer auf Deutsch und formuliere natürliche, konversationelle Antworten."
            messages_for_final_response = [{"role": "system", "content": final_system_prompt}] + user_history
            
            final_payload = {"model": loaded_model, "messages": messages_for_final_response, "stream": True}
            ki_response = requests.post(f"{ki_server_url}/api/chat", json=final_payload, stream=True, timeout=REQUESTS_TIMEOUT[1])
            ki_response.raise_for_status()

            return Response(stream_with_context(ki_response.iter_content(chunk_size=1024)), content_type=ki_response.headers['Content-Type'])

    except requests.exceptions.ReadTimeout as e:
        current_app.logger.error(f"Timeout-Fehler in /api/chat: {e}", exc_info=True)
        error_payload = {"message": {"content": "Der KI-Server hat zu lange für eine Antwort gebraucht. Bitte versuche es in einem Moment erneut."}}
        def error_stream():
            yield f"data: {json.dumps(error_payload)}\n\n"
        return Response(error_stream(), content_type='text/event-stream', status=504) # 504 Gateway Timeout
    except Exception as e:
        current_app.logger.error(f"Schwerer Fehler in /api/chat: {e}", exc_info=True)
        error_payload = {
            "message": {
                "content": f"Es ist ein schwerwiegender Serverfehler aufgetreten. (Fehlertyp: {type(e).__name__})"
            }
        }
        def error_stream():
            yield f"data: {json.dumps(error_payload)}\n\n"
        return Response(error_stream(), content_type='text/event-stream', status=500)
