import os
import logging
from flask import Flask, render_template, request, jsonify
import requests

# Logging für Produktion konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

FORGEJO_URL = os.environ.get("FORGEJO_URL", "https://forgejo.example.com")
FORGEJO_REPO = os.environ.get("FORGEJO_REPO", "user/repo")
FORGEJO_TOKEN = os.environ.get("FORGEJO_TOKEN", "")
SERVICE_API_KEY = os.environ.get("SERVICE_API_KEY", "")

# Einfache Sicherheits-Header für alle Antworten hinzufügen
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit_issue():
    auth_header = request.headers.get("X-API-Key")
    
    # API-Key erzwingen, falls konfiguriert
    if SERVICE_API_KEY and auth_header != SERVICE_API_KEY:
        logger.warning(f"Unautorisierter Zugriffseintrag von IP: {request.remote_addr}")
        return jsonify({"error": "Unauthorized: Ungültiger oder fehlender API-Key"}), 401

    if request.is_json:
        data = request.get_json()
        title = data.get("title")
        body = data.get("body", "")
    else:
        title = request.form.get("title")
        body = request.form.get("body", "")

    if not title or not title.strip():
        return jsonify({"error": "Titel ist ein Pflichtfeld"}), 400

    api_url = f"{FORGEJO_URL.rstrip('/')}/api/v1/repos/{FORGEJO_REPO}/issues"
    headers = {
        "Authorization": f"token {FORGEJO_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "title": title.strip(),
        "body": body.strip() if body else ""
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 201:
            logger.info(f"Issue erfolgreich erstellt in {FORGEJO_REPO}")
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": True, "message": "Issue erfolgreich erstellt!"}), 201
            return render_template("index.html", success=True)
        else:
            logger.error(f"Forgejo-Fehler ({response.status_code}): {response.text}")
            return jsonify({
                "error": "Fehler beim Erstellen des Issues in Forgejo",
                "details": response.text
            }, response.status_code)

    except requests.exceptions.RequestException as e:
        logger.exception("Verbindungsfehler zur Forgejo-API")
        return jsonify({"error": f"Verbindungsfehler: {str(e)}"}), 500

if __name__ == "__main__":
    # Fallback, falls direkt ausgeführt (wird im Container durch Gunicorn überschrieben)
    app.run(host="0.0.0.0", port=5000)