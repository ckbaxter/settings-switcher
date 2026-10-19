# Build-Kontext ist das Repo-Root:  docker build -f runner/Dockerfile -t settings-switcher-runner .
# Die Image-Version muss zur Playwright-Version in runner/requirements.txt passen.
FROM mcr.microsoft.com/playwright/python:v1.64.0-noble

WORKDIR /app
COPY runner/requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY shared/ ./shared/
COPY runner/runner.py ./runner.py

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

USER pwuser
ENTRYPOINT ["python3", "/app/runner.py"]
