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
        "title": title,
        "body": formatted_body
    }

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

    # 2. Schritt: Anhänge an das erstellte Issue hochladen (WICHTIG: Endpunkt heißt 'assets')
    uploaded_files = request.files.getlist("attachments")
    attachment_markdowns = []

    for file in uploaded_files:
        if file and file.filename:
            # Korrekter API-Pfad mit /assets und optionalem Dateinamen als Parameter
            upload_url = f"{FORGEJO_URL.rstrip('/')}/api/v1/repos/{FORGEJO_REPO}/issues/{issue_number}/assets?name={file.filename}"
            
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
                else:
                    logger.error(f"Fehler beim Hochladen des Anhangs {file.filename} ({upload_res.status_code}): {upload_res.text}")
            except requests.exceptions.RequestException as e:
                logger.exception(f"Netzwerkfehler beim Hochladen des Anhangs {file.filename}")

    # 3. Schritt: Falls Anhänge hochgeladen wurden, das Issue mit den Markdown-Links aktualisieren
    if attachment_markdowns:
        attachments_section = "\n\n---\n#### Anhänge:\n" + "\n".join(attachment_markdowns)
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