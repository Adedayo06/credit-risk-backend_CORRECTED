# Use slim Python
FROM python:3.11-slim
 
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
 
# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*
 
# Workdir
WORKDIR /app
 
# Copy & install Python deps first (leverage Docker layer cache)
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
 
# Copy app
COPY . /app
 
# Expose port for App Runner
EXPOSE 8000
 
# Start FastAPI (adjust module:app path if needed)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]