FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    STORE_PATH=/app/instance/studio.sqlite3

WORKDIR /app

RUN useradd --create-home --uid 10001 sage

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY --chown=sage:sage . .
RUN mkdir -p /app/instance /app/logs && chown -R sage:sage /app/instance /app/logs

USER sage

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/', timeout=4)"

CMD ["sh", "startup.sh"]
