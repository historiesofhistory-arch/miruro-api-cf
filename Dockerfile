FROM python:3.11-slim

WORKDIR /app

# Install system deps + REAL Google Chrome (not Chrome-for-Testing which CF detects)
# + Xvfb for headed browser on a server
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 ca-certificates \
    xvfb xauth \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb || true \
    && apt-get install -yf --no-install-recommends \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api.py cf_solver.py cf_store.py ./

# Environment
ENV PYTHONUNBUFFERED=1
ENV CHROME_PATH=/usr/bin/google-chrome
ENV DISPLAY=:99

# Expose the default FastAPI port
EXPOSE 8000

# Start Xvfb (for headed Chrome to bypass CF) then uvicorn
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x800x24 -nolisten tcp & sleep 1 && uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
