from flask import Flask
import os
import threading
from .config import SESSION_SECRET
from .auth import auth_bp, get_session, require_auth

flask_app = Flask(__name__,
                  template_folder='templates',
                  static_folder='static',
                  static_url_path='/static')
flask_app.secret_key = SESSION_SECRET
flask_app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 6

# Auth‑Blueprint (OAuth2) registrieren
flask_app.register_blueprint(auth_bp)

# Deine bestehenden Routen (Landing, Dashboard, Live …)
from . import routes

def run_flask():
    port = int(os.getenv("PORT", "7860"))
    flask_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()
