FROM python:3.12-slim

# System deps Chromium needs on Debian/Ubuntu (playwright handles these via
# --with-deps but we also need build tools for some pip packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer-cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + all its system libs via playwright's helper.
# vipertls uses playwright under the hood; VIPERTLS_HOME tells it where to look.
ENV VIPERTLS_HOME=/app/vipertls
RUN python -m playwright install-deps chromium && \
    vipertls install-browsers

# Copy the rest of the project
COPY api.py cf_store.py ./

# Railway / Render inject PORT at runtime; fall back to 8080 for local Docker.
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
# Xvfb display for headed browser solve (vipertls escalates to headed if headless fails)
ENV DISPLAY=:99

EXPOSE 8080

# Start Xvfb (for vipertls browser solver) then uvicorn
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x800x24 -nolisten tcp & sleep 1 && uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}"]
