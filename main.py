# Ordner: /coldNet/
# Datei: main.py

from app import create_app

# Erstellt eine Instanz deiner Anwendung mit der Factory-Funktion
app = create_app()

if __name__ == '__main__':
    # Startet den Flask-Entwicklungsserver
    # debug=True sorgt dafür, dass der Server bei Code-Änderungen automatisch neu startet.
    app.run(host='0.0.0.0', port=5000, debug=True)
