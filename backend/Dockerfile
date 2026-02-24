FROM python:3.11-slim

WORKDIR /app

# install build tools & client for waiting on Postgres
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
       postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# copy and install python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy application code
COPY . .

# expose port and provide default command
EXPOSE 8000

CMD ["sh", "-c", "\
until pg_isready -h \"${DB_HOST:-db}\" -p \"${DB_PORT:-5432}\"; do \
  echo waiting for database...; \
  sleep 1; \
 done; \
 uvicorn app.main:app --host 0.0.0.0 --port 8000\"]
