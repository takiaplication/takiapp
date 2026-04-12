# ── Stage 1: build frontend ───────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ── Stage 2: production image ─────────────────────────────────────────────────
FROM python:3.11-slim

# Use system Chromium to avoid playwright install-deps font package issues
RUN apt-get update && apt-get install -y \
    ffmpeg \
    chromium \
    chromium-driver \
    fonts-liberation \
    fonts-noto \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Tell Playwright to use the system Chromium instead of downloading its own
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/bin
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# Python deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend into backend/static/dist so FastAPI can serve it
COPY --from=frontend-builder /app/frontend/dist ./backend/static/dist

# Storage dir is a Railway volume — pre-create skeleton for clean startup
RUN mkdir -p storage/projects storage/meme_library

EXPOSE 8000

WORKDIR /app/backend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
