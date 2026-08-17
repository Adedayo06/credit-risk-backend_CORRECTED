# Use slim Python
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy & install Python deps first (leverage Docker layer cache)
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy app
COPY . /app

# Expose port (Render sets $PORT at runtime; 8001 is the local/dev default)
EXPOSE 8001

# Start FastAPI. Render injects $PORT — fall back to 8001 for local `docker run`.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8001}"]
