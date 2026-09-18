# Stage 1: Build-Abhängigkeiten installieren
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Minimales Runtime-Image
FROM python:3.11-slim

WORKDIR /app

# Unprivilegierten Systembenutzer anlegen
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Python-Pakete aus dem Builder-Stage kopieren
COPY --from=builder /root/.local /home/appuser/.local
COPY --from=builder /app /app

# Quellcode kopieren und Rechte anpassen
COPY . .
RUN chown -R appuser:appuser /app

USER appuser

# PATH für die installierten Python-Pakete erweitern
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Start via Gunicorn statt Flask-Development-Server
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5000 --workers ${WORKERS:-2} --threads 2 --timeout 60 --access-logfile '-' --error-logfile '-' wsgi:app"]