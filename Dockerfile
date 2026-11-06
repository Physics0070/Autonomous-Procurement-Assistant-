# One image, one site: builds the web app, then serves it and the API from the same server.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/ml ./ml
COPY --from=web /web/dist /app/static
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 STORAGE_LOCAL_PATH=/data/storage ENVIRONMENT=production
RUN mkdir -p /data/storage
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
