FROM python:3.11-slim

WORKDIR /app

# Ultralytics writes config here; /root/.config is often read-only on HF / minimal images
RUN mkdir -p /app/.ultralytics
ENV YOLO_CONFIG_DIR=/app/.ultralytics

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    git-lfs \
    ffmpeg \
    libsm6 \
    libxext6 \
    cmake \
    rsync \
    libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set Python path to backend package only (avoid /app module shadowing)
ENV PYTHONPATH=/app/backend:$PYTHONPATH

# Expose port (7860 for HF Spaces; Render overrides via PORT env var)
EXPOSE 7860

# Run the real backend API app (not the standalone fallback)
# PORT env var is set automatically by Render; HF Spaces doesn't set it so 7860 is used.
CMD sh -c "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-7860}"
