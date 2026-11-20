# Backend image (build context = repository root, because db/schema.sql lives outside backend/).
# Built for Hugging Face Spaces (Docker SDK): listens on 7860 and runs as a non-root user.
# Includes Chromium for the Playwright-rendered portals.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face runs containers as uid 1000.
RUN useradd -m -u 1000 user
COPY --chown=user backend/ /app/backend/
COPY --chown=user db/ /app/db/
USER user

EXPOSE 7860

# Run exactly ONE worker: the scheduler and the crawl lock are in-process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
