FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN cp data/invesgo_connector.py /app/data/invesgo_connector.py 2>/dev/null || true
RUN cp data/data_processor.py /app/data/data_processor.py 2>/dev/null || true

# Copy knowledge base books
RUN mkdir -p /app/knowledge_base/books /app/knowledge_base/chroma_db

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
