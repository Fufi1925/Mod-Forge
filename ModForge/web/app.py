from flask import Flask
import os, threading
from .config import SESSION_SECRET

flask_app = Flask(__name__,
                  template_folder='templates',
                  static_folder='static',
                  static_url_path='/static')
flask_app.secret_key = SESSION_SECRET
flask_app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 6

from . import routes   # Routen registrieren

def run_flask():
    port = int(os.getenv("PORT", "7860"))
    flask_app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()
