# syntax=docker/dockerfile:1.7
# Second Brain AI — production image (Round 3 / G-B1). Three stages:
#   1. css      Tailwind v4 build (node only here)
#   2. builder  Python virtualenv with CPU-only torch (compiler only here)
#   3. runtime  slim Python + git, non-root user, no node/compiler
# Build:  docker compose build      Run: docker compose up -d   (see docs/DEPLOY.md)

# ---------- 1. CSS ------------------------------------------------------------
FROM node:22-bookworm-slim AS css
WORKDIR /build/ai_manager
COPY ai_manager/package.json ai_manager/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ai_manager/static ./static
COPY ai_manager/templates ./templates
COPY ai_manager/core ./core
RUN npm run build

# ---------- 2. Python dependencies -------------------------------------------
FROM python:3.12-slim-bookworm AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc g++ \
 && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
# CPU-only torch first (the CUDA wheels are several GB and useless on the VM).
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.13.0" \
 && pip install -r requirements.txt

# ---------- 3. Runtime --------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    TZ=Europe/Bucharest \
    HF_HOME=/data/hf_cache \
    LLAMA_INDEX_CACHE_DIR=/data/hf_cache/llama_index \
    DJANGO_SETTINGS_MODULE=ai_manager.settings
RUN apt-get update \
 && apt-get install -y --no-install-recommends git tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --home-dir /app --shell /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
# Code is owned by root and read-only for the app user (B-42); only the data
# folders (volumes) belong to "app".
COPY ai_manager ./ai_manager
COPY --from=css /build/ai_manager/static/css/styles.css ./ai_manager/static/css/styles.css
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh \
 && mkdir -p /data/hf_cache ai_manager/logs ai_manager/staticfiles ai_manager/chroma_db ai_manager/obsidian_data \
 && chown -R app:app /data ai_manager/logs ai_manager/staticfiles ai_manager/chroma_db ai_manager/obsidian_data
USER app
WORKDIR /app/ai_manager
EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["web"]
