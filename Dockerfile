FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY infra/requirements-gateway.txt .
RUN pip install --no-cache-dir -r requirements-gateway.txt

COPY . .

EXPOSE 8000
CMD uvicorn services.gateway.main:app --host 0.0.0.0 --port ${PORT:-8000}
