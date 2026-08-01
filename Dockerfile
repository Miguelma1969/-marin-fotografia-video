FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    FACE_MODEL=buffalo_sc \
    FACE_MODEL_ROOT=/opt/insightface \
    FACE_DET_SIZE=320 \
    FACE_MAX_IMAGE_DIM=2000 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake the compact model into the image. The running service will no longer
# download and unzip a large model after every restart.
RUN python scripts_download_face_model.py

RUN mkdir -p /var/data/photos /var/data/selfies /var/data/videos \
    /app/data/photos /app/data/selfies /app/data/videos

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 5"]
