# Build-Kontext ist das Repo-Root (siehe docker-compose.yml).
FROM python:3.14-slim

WORKDIR /app
COPY editor/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY editor/ ./editor/

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SS_PROFILES_DIR=/profiles

USER 1000:1000
EXPOSE 8080
CMD ["uvicorn", "--factory", "editor.app:create_app_from_env", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
