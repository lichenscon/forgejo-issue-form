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
    name = request.form.get("name", "Anonym").strip()
    title = request.form.get("title", "").strip()
    body_text = request.form.get("body", "").strip()

    if not title:
        return jsonify({"error": "Titel ist ein Pflichtfeld"}), 400

    headers = {
        "Authorization": f"token {FORGEJO_TOKEN}"
    }

    # 1. Schritt: Anhänge über den offiziellen Forgejo-Anhang-Endpunkt hochladen
    uploaded_files = request.files.getlist("attachments")
    attachment_uuids = []

    for file in uploaded_files:
        if file and file.filename:
            upload_url = f"{FORGEJO_URL.rstrip('/')}/api/v1/repos/{FORGEJO_REPO}/assets"
            
            # Datei für den Upload vorbereiten
            files_payload = {
                'attachment': (file.filename, file.read(), file.content_type)
            }
            
            try:
                upload_res = requests.post(upload_url, files=files_payload, headers=headers, timeout=15)
                if upload_res.status_code == 201:
                    uuid = upload_res.json().get("uuid")
                    if uuid:
                        attachment_uuids.append(uuid)
                        logger.info(f"Anhang erfolgreich zu Forgejo hochgeladen: {file.filename} (UUID: {uuid})")
                else:
                    logger.error(f"Fehler beim Hochladen des Anhangs {file.filename}: {upload_res.text}")
            except requests.exceptions.RequestException as e:
                logger.exception(f"Netzwerkfehler beim Hochladen des Anhangs {file.filename}")

    # 2. Schritt: Formatierter Beschreibungstext
    formatted_body = f"""### Neue Einreichung über das Webformular

**Eingereicht von:** {name if name else "Anonym"}  

---

#### Beschreibung:
{body_text if body_text else "*Keine Beschreibung angegeben.*"}

---
*Automatisch generiert über das Kontakt- und Supportformular.*
"""

    # 3. Schritt: Issue erstellen und die hochgeladenen Attachment-UUIDs mit übergeben
    issue_api_url = f"{FORGEJO_URL.rstrip('/')}/api/v1/repos/{FORGEJO_REPO}/issues"
    issue_payload = {
        "title": title,
        "body": formatted_body
    }
    
    # Falls Attachments hochgeladen wurden, übergibt Forgejo diese im Feld "files" als Array von UUID-Strings
    if attachment_uuids:
        issue_payload["files"] = attachment_uuids

    try:
        response = requests.post(issue_api_url, json=issue_payload, headers={**headers, "Content-Type": "application/json"}, timeout=10)
        
        if response.status_code == 201:
            logger.info(f"Issue erfolgreich in {FORGEJO_REPO} erstellt.")
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": True, "message": "Issue und Anhänge erfolgreich erstellt!"}), 201
            return render_template("index.html", success=True)
        else:
            logger.error(f"Forgejo-Fehler beim Erstellen des Issues ({response.status_code}): {response.text}")
            return jsonify({
                "error": "Fehler beim Erstellen des Issues in Forgejo",
                "details": response.text
            }), response.status_code

    except requests.exceptions.RequestException as e:
        logger.exception("Verbindungsfehler zur Forgejo-API")
        return jsonify({"error": f"Verbindungsfehler: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)