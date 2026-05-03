from flask import Flask
import os
import threading
from .config import SESSION_SECRET

flask_app = Flask(__name__)
flask_app.secret_key = SESSION_SECRET
flask_app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 6

# !!! WICHTIG – diese Zeile darf NIE fehlen !!!
from . import routes

def run_flask():
    port = int(os.getenv("PORT", "7860"))
    flask_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()
