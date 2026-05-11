from flask import Flask
import os
import threading
import random
from datetime import datetime

# NEU: Flask-SocketIO importieren
from flask_socketio import SocketIO

from .config import SESSION_SECRET
from .auth import auth_bp, get_session, require_auth

flask_app = Flask(__name__,
                  template_folder='templates',
                  static_folder='static',
                  static_url_path='/static')
flask_app.secret_key = SESSION_SECRET
flask_app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 6

# NEU: SocketIO initialisieren
socketio = SocketIO(flask_app)

# Auth‑Blueprint (OAuth2) registrieren
flask_app.register_blueprint(auth_bp)

# Deine bestehenden Routen (Landing, Dashboard, Live …)
from . import routes

# NEU: Hintergrund-Thread, der die Live-Daten sendet
def background_emitter():
    while True:
        socketio.sleep(3)  # alle 3 Sekunden
        status = {
            "systems": {
                "database": True,   # hier echte Werte einbauen
                "api": True,
                "raid": True,
                "automod": True
            },
            "protection": {
                # Beispielwerte – ersetze sie durch echte aus deinem Bot/System
                "raid": random.randint(88, 98),
                "spam": random.randint(80, 95),
                "scam": random.randint(92, 100),
                "invite": random.randint(85, 97)
            },
            "activity": [
                # Echte Logs aus deiner Datenbank / deinem Bot
                {
                    "kind": "spam",
                    "text": "Spam-Nachricht von @User gelöscht",
                    "ts": datetime.now().isoformat()
                },
                {
                    "kind": "invite",
                    "text": "Discord-Invite gelöscht",
                    "ts": datetime.now().isoformat()
                }
                # weitere Einträge...
            ]
        }
        socketio.emit('status_update', status)

# NEU: Emitter starten, sobald ein Client verbindet (optional)
# Du kannst ihn auch direkt beim Start starten.
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# run_flask ersetzen: Statt flask_app.run() benutzen wir socketio.run()
def run_flask():
    port = int(os.getenv("PORT", "7860"))
    # Wichtig: socketio.run() statt flask_app.run()
    socketio.run(flask_app, host="0.0.0.0", port=port, debug=False)

def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()

# Hintergrund-Emitter starten, sobald der Server läuft.
# Das machen wir am besten in run_flask() selbst, bevor socketio.run() läuft.
# Du kannst es so einbauen:
def run_flask():
    port = int(os.getenv("PORT", "7860"))
    # Starte den Emitter als Hintergrund-Task
    socketio.start_background_task(background_emitter)
    socketio.run(flask_app, host="0.0.0.0", port=port, debug=False)
