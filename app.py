import os
import logging
import base64
from io import BytesIO
from flask import Flask, render_template, request, jsonify
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

FORGEJO_URL = os.environ.get("FORGEJO_URL", "https://forgejo.example.com")
FORGEJO_REPO = os.environ.get("FORGEJO_REPO", "user/repo")
FORGEJO_TOKEN = os.environ.get("FORGEJO_TOKEN", "")
FORGEJO_LABEL_ID = os.environ.get("FORGEJO_LABEL_ID", "")

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
    name = request.form.get("name", "").strip()
    title = request.form.get("title", "").strip()
    body_text = request.form.get("body", "").strip()
    
    uploaded_files = request.files.getlist("attachments")
    screenshot_data = request.form.get("screenshot_base64", "").strip()

    # Prüfen, ob mindestens ein Feld, ein Anhang oder ein Screenshot ausgefüllt wurde
    has_files = any(f and f.filename for f in uploaded_files)
    if not any([name, title, body_text, has_files, screenshot_data]):
        return jsonify({"error": "Es muss mindestens ein Feld oder ein Anhang/Screenshot ausgefüllt werden."}), 400

    # Platzhalter für den Titel, falls leer
    issue_title = title if title else "[Automatisches Support-Ticket über Webformular]"

    headers = {
        "Authorization": f"token {FORGEJO_TOKEN}"
    }

    # 1. Schritt: Issue ERST erstellen, um die Issue-Nummer zu erhalten
    formatted_body = f"""### Neue Einreichung über das Webformular

**Eingereicht von:** {name if name else "Anonym"}  

---

#### Beschreibung:
{body_text if body_text else "*Keine Beschreibung angegeben.*"}

---
*Automatisch generiert über das Supportformular.*
"""

    issue_api_url = f"{FORGEJO_URL.rstrip('/')}/api/v1/repos/{FORGEJO_REPO}/issues"
    issue_payload = {
        "title": issue_title,
        "body": formatted_body
    }

    # Label-ID dynamisch hinzufügen, falls per ENV-Variable gesetzt
    if FORGEJO_LABEL_ID:
        try:
            # Forgejo API erwartet Label-IDs als Integer im Array
            issue_payload["labels"] = [int(FORGEJO_LABEL_ID)]
        except ValueError:
            # Falls versehentlich ein String eingetragen wurde, als String übergeben
            issue_payload["labels"] = [FORGEJO_LABEL_ID]

    try:
        issue_res = requests.post(
            issue_api_url, 
            json=issue_payload, 
            headers={**headers, "Content-Type": "application/json"}, 
            timeout=10
        )
        
        if issue_res.status_code != 201:
            logger.error(f"Forgejo-Fehler beim Erstellen des Issues ({issue_res.status_code}): {issue_res.text}")
            return jsonify({
                "error": "Fehler beim Erstellen des Issues in Forgejo",
                "details": issue_res.text
            }, issue_res.status_code)

        issue_data = issue_res.json()
        issue_number = issue_data.get("number")
        logger.info(f"Issue #{issue_number} erfolgreich in {FORGEJO_REPO} erstellt.")

    except requests.exceptions.RequestException as e:
        logger.exception("Verbindungsfehler zur Forgejo-API beim Erstellen des Issues")
        return jsonify({"error": f"Verbindungsfehler: {str(e)}"}), 500

    attachment_markdowns = []
    upload_url = f"{FORGEJO_URL.rstrip('/')}/api/v1/repos/{FORGEJO_REPO}/issues/{issue_number}/assets"

    # 2a. Schritt: Normale Dateianhänge hochladen
    for file in uploaded_files:
        if file and file.filename:
            files_payload = {
                'attachment': (file.filename, file.stream, file.content_type or 'application/octet-stream')
            }
            try:
                upload_res = requests.post(upload_url, files=files_payload, headers=headers, timeout=30)
                if upload_res.status_code == 201:
                    res_data = upload_res.json()
                    file_url = res_data.get("browser_download_url")
                    file_name = res_data.get("name", file.filename)
                    if file_url:
                        if file.content_type and file.content_type.startswith("image/"):
                            attachment_markdowns.append(f"![{file_name}]({file_url})")
                        else:
                            attachment_markdowns.append(f"[{file_name}]({file_url})")
                        logger.info(f"Anhang erfolgreich zu Issue #{issue_number} hochgeladen: {file_name}")
            except Exception:
                logger.exception(f"Fehler beim Hochladen des Anhangs {file.filename}")

    # 2b. Schritt: Screenshot hochladen (falls vorhanden)
    if screenshot_data:
        try:
            if "," in screenshot_data:
                screenshot_data = screenshot_data.split(",")[1]
            
            img_bytes = base64.b64decode(screenshot_data)
            screenshot_file = BytesIO(img_bytes)
            
            screenshot_payload = {
                'attachment': ('screenshot.png', screenshot_file, 'image/png')
            }
            
            upload_res = requests.post(upload_url, files=screenshot_payload, headers=headers, timeout=30)
            if upload_res.status_code == 201:
                res_data = upload_res.json()
                file_url = res_data.get("browser_download_url")
                file_name = res_data.get("name", "screenshot.png")
                if file_url:
                    attachment_markdowns.append(f"![{file_name}]({file_url})")
                    logger.info(f"Screenshot erfolgreich zu Issue #{issue_number} hochgeladen.")
        except Exception:
            logger.exception("Fehler beim Verarbeiten/Hochladen des Screenshots.")

    # 3. Schritt: Issue-Beschreibung aktualisieren, falls Anhänge oder Screenshots hinzugekommen sind
    if attachment_markdowns:
        attachments_section = "\n\n---\n#### Anhänge & Screenshots:\n" + "\n".join(attachment_markdowns)
        updated_body = formatted_body + attachments_section
        
        update_url = f"{FORGEJO_URL.rstrip('/')}/api/v1/repos/{FORGEJO_REPO}/issues/{issue_number}"
        try:
            requests.patch(
                update_url, 
                json={"body": updated_body}, 
                headers={**headers, "Content-Type": "application/json"}, 
                timeout=10
            )
        except Exception:
            logger.exception("Konnte Issue-Body mit Anhang-Links nicht aktualisieren.")

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "message": f"Issue #{issue_number} und Anhänge erfolgreich erstellt!"}), 201
    return render_template("index.html", success=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)