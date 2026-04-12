# ── Stage 1: frontend build ───────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python deps (build wheels in isolation) ─────────────────────────
FROM python:3.11-slim AS python-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 3: final runtime image ─────────────────────────────────────────────
FROM python:3.11-slim

# Minimal runtime deps only — no build tools, no node, no npm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    chromium \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Point Playwright to system Chromium — no browser download needed
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/bin
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# Copy pre-built Python packages from builder
COPY --from=python-builder /install /usr/local

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend dist
COPY --from=frontend-builder /app/frontend/dist ./backend/static/dist

# Pre-create storage skeleton (Railway volume mounts over this)
RUN mkdir -p storage/projects storage/meme_library

EXPOSE 8000

WORKDIR /app/backend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
