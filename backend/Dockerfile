# Backend image for Render (build context = repository root, because db/schema.sql lives outside backend/).
# Includes Chromium for the Playwright-rendered portals.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium

COPY backend/ /app/backend/
COPY db/ /app/db/

# Render injects $PORT. Run exactly ONE worker: the scheduler and the crawl lock are in-process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
