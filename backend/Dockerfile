FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN rm -rf /app/data

ARG CACHEBUST=3
COPY . .

RUN mkdir -p /app/knowledge_base/books /app/knowledge_base/chroma_db

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --limit-concurrency 100 --timeout-keep-alive 600 --h11-max-incomplete-event-size 104857600"]
