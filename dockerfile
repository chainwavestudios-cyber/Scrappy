FROM python:3.11-slim

# Render: set Health Check Path to /health (or /). Never use /campaign/cities — it
# imports Playwright and will time out or OOM during deploy health probes.

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

RUN chmod +x /app/docker-entrypoint.sh

# Exec-form CMD + entrypoint: reliable PORT expansion on Render (avoids flaky multi-line shell CMD).
# In Render UI: Health Check Path = /health
CMD ["/bin/sh", "/app/docker-entrypoint.sh"]
