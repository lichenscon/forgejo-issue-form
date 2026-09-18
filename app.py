import os
import logging
from flask import Flask, render_template, request, jsonify
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

FORGEJO_URL = os.environ.get("FORGEJO_URL", "https://forgejo.example.com")
FORGEJO_REPO = os.environ.get("FORGEJO_REPO", "user/repo")
FORGEJO_TOKEN = os.environ.get("FORGEJO_TOKEN", "")

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
    # Formulardaten auslesen
    name = request.form.get("name", "Anonym").strip()
    title = request.form.get("title", "").strip()
    body_text = request.form.get("body", "").strip()

    if not title:
        return jsonify({"error": "Titel ist ein Pflichtfeld"}), 400

    # Saubere HTML-Formatierung für das Issue (Markdown/HTML-Mix, den Forgejo rendert)
    formatted_body = f"""### Neue Einreichung über das Webformular

**Eingereicht von:** {name if name else "Anonym"}  

---

#### Beschreibung:
{body_text if body_text else "*Keine Beschreibung angegeben.*"}

---
*Automatisch generiert über das Kontakt- und Supportformular.*
"""

    api_url = f"{FORGEJO_URL.rstrip('/')}/api/v1/repos/{FORGEJO_REPO}/issues"
    headers = {
        "Authorization": f"token {FORGEJO_TOKEN}"
    }
    
    # Payload für das Issue (JSON-Daten für den Post-Request)
    data = {
        "title": title,
        "body": formatted_body
    }

    files = []
    try:
        # Anhänge einsammeln und für den Multipart-Upload vorbereiten
        uploaded_files = request.files.getlist("attachments")
        for file in uploaded_files:
            if file and file.filename:
                # Flask liebt Dateiobjekte im Format ('files', (filename, stream, content_type))
                files.append(('files', (file.filename, file.read(), file.content_type)))

        # Wenn Anhänge vorhanden sind, nutzt Gitea/Forgejo multipart/form-data statt application/json
        if files:
            # Bei Multipart-Uploads müssen die JSON-Felder als einfache Form-Felder übergeben werden
            response = requests.post(api_url, data=data, files=files, headers=headers, timeout=15)
        else:
            headers["Content-Type"] = "application/json"
            response = requests.post(api_url, json=data, headers=headers, timeout=10)
        
        if response.status_code == 201:
            logger.info(f"Issue erfolgreich in {FORGEJO_REPO} erstellt (mit {len(files)} Anhang/Anhängen).")
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": True, "message": "Issue und Anhänge erfolgreich erstellt!"}), 201
            return render_template("index.html", success=True)
        else:
            logger.error(f"Forgejo-Fehler ({response.status_code}): {response.text}")
            return jsonify({
                "error": "Fehler beim Erstellen des Issues in Forgejo",
                "details": response.text
            }), response.status_code

    except requests.exceptions.RequestException as e:
        logger.exception("Verbindungsfehler zur Forgejo-API")
        return jsonify({"error": f"Verbindungsfehler: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)