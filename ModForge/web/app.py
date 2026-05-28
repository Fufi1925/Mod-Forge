from flask import Flask
import os
import threading
import random
from datetime import datetime

# Flask-SocketIO importieren
from flask_socketio import SocketIO

from .config import SESSION_SECRET
from .auth import auth_bp, get_session, require_auth

flask_app = Flask(__name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static')
flask_app.secret_key = SESSION_SECRET
flask_app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 6

# SocketIO initialisieren
socketio = SocketIO(flask_app)

# Auth-Blueprint (OAuth2) registrieren
flask_app.register_blueprint(auth_bp)

# Deine bestehenden Routen (Landing, Dashboard, Live …)
from . import routes

# Hintergrund-Thread, der die Live-Daten sendet
def background_emitter():
    while True:
        socketio.sleep(3)  # alle 3 Sekunden
        status = {
            "systems": {
                "database": True,
                "api": True,
                "raid": True,
                "automod": True
            },
            "protection": {
                "raid": random.randint(88, 98),
                "spam": random.randint(80, 95),
                "scam": random.randint(92, 100),
                "invite": random.randint(85, 97)
            },
            "activity": [
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
            ]
        }
        socketio.emit('status_update', status)


@socketio.on('connect')
def handle_connect():
    print('Client connected')


@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')


def run_flask():
    port = int(os.getenv("PORT", "7860"))
    # Starte den Emitter als Hintergrund-Task
    socketio.start_background_task(background_emitter)
    socketio.run(flask_app, host="0.0.0.0", port=port, debug=False)


def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()
