FROM python:3.11-slim

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

# Render sets PORT at runtime; local runs can use default.
# JSON-form CMD cannot expand $PORT — shell form is required.
# Logs to stdout/stderr so Render shows boot errors; do not import Playwright on GET / (see app.index).
CMD gunicorn app:app \
  --bind 0.0.0.0:${PORT:-10000} \
  --timeout 300 \
  --workers 1 \
  --access-logfile - \
  --error-logfile - \
  --capture-output
