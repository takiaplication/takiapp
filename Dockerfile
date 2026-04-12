# ── Stage 1: frontend build ───────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python deps ──────────────────────────────────────────────────────
# Isolated build stage so gcc/g++ never land in the final image.
FROM python:3.11-slim AS python-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .

# ⚠️  Install CPU-only PyTorch BEFORE requirements.txt.
#    easyocr depends on torch; if torch is already present pip won't reinstall
#    the default CUDA build (~2.5 GB). CPU wheel is ~200 MB — saves ~2.3 GB.
RUN pip install --no-cache-dir \
    torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu

# Now install everything else (torch already satisfied, CUDA skipped)
RUN pip install --no-cache-dir -r requirements.txt


# ── Stage 3: final runtime image ─────────────────────────────────────────────
FROM python:3.11-slim

# Runtime only — no gcc, no node, no npm
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

# Tell Playwright to use the system Chromium (no browser download)
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/bin
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

# Copy pre-built Python packages and scripts from builder
COPY --from=python-builder /usr/local/lib/python3.11/site-packages \
                           /usr/local/lib/python3.11/site-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin

WORKDIR /app

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend dist so FastAPI can serve it as static files
COPY --from=frontend-builder /app/frontend/dist ./backend/static/dist

# Pre-create storage skeleton (Railway volume mounts over /app/storage)
RUN mkdir -p storage/projects storage/meme_library

EXPOSE 8000

WORKDIR /app/backend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
