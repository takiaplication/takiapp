# ── Stage 1: build frontend ───────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # outputs to /app/frontend/dist


# ── Stage 2: production image ─────────────────────────────────────────────────
FROM python:3.11-slim

# System deps: ffmpeg + Chromium dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    # Playwright / Chromium runtime deps
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    libx11-xcb1 libxcb-dri3-0 libxshmfence1 libgles2 \
    fonts-liberation fonts-noto-color-emoji ca-certificates \
    wget curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only to keep image lean)
RUN pip install playwright && \
    playwright install chromium && \
    playwright install-deps chromium

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend into backend/static/dist so FastAPI can serve it
COPY --from=frontend-builder /app/frontend/dist ./backend/static/dist

# Storage dir is a Railway volume — just pre-create the skeleton so the
# app starts cleanly even without a mounted volume.
RUN mkdir -p storage/projects storage/meme_library

EXPOSE 8000

WORKDIR /app/backend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
