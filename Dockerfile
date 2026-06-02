FROM python:3.11-slim

WORKDIR /app

# Ultralytics writes config here; /root/.config is often read-only on HF / minimal images
RUN mkdir -p /app/.ultralytics
ENV YOLO_CONFIG_DIR=/app/.ultralytics

# Install only the system libraries actually needed at runtime:
#   ffmpeg          — openai-whisper audio decoding
#   libsm6 libxext6 libgl1 libglib2.0-0 — OpenCV headless shared libs
#   tesseract-ocr   — pytesseract OCR binary
# --no-install-recommends keeps the dep tree small (avoids pulling in GTK, cmake, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

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
CMD sh -c "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-7860} --log-level info --access-log"
