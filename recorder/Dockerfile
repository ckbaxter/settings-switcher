# Editor mit Live-Browser. Build-Kontext ist das Repo-Root (siehe docker-compose.yml).
# Die Image-Version muss zur Playwright-Version in requirements-dev.txt / runner/requirements.txt passen.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

WORKDIR /app
COPY editor/requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt \
    && pip install --no-cache-dir --break-system-packages playwright==1.56.0

COPY shared/ ./shared/
COPY editor/ ./editor/

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    SS_PROFILES_DIR=/profiles \
    RECORDER_ENABLED=1

USER pwuser
EXPOSE 8080
CMD ["uvicorn", "--factory", "editor.app:create_app_from_env", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
