# MarkFeed — container image for Hugging Face Spaces (Docker SDK) or any VPS.
#
# Builds the full offline stack: Tesseract (Bengali + English) + the Python
# OCR/conversion backend + FastAPI server. No cloud APIs, no LLM.

FROM python:3.11-slim

# --- system deps -----------------------------------------------------------
#  tesseract-ocr            : the OCR engine (pytesseract + img2table shell out to it)
#  tesseract-ocr-ben/-eng   : Bengali + English language data
#  libgl1 / libglib2.0-0    : required by PaddleOCR / OpenCV at import time
#  libgomp1                 : OpenMP runtime used by paddlepaddle
#  curl                     : to fetch the higher-accuracy Bengali model below
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ben \
        tesseract-ocr-eng \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Optional but recommended: overlay the higher-accuracy "best" Bengali model.
# The apt package ships the smaller "fast" model; this upgrades Bengali quality.
RUN TESSDATA=$(dirname $(find / -name eng.traineddata 2>/dev/null | head -1)) && \
    curl -fsSL -o "$TESSDATA/ben.traineddata" \
      https://github.com/tesseract-ocr/tessdata_best/raw/main/ben.traineddata || true

# --- python deps -----------------------------------------------------------
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- app -------------------------------------------------------------------
COPY . .

# Hugging Face Spaces routes traffic to port 7860 by default.
ENV PORT=7860 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8
EXPOSE 7860

# Pre-create the runtime job dir (history is auto-capped to the last 10 jobs).
RUN mkdir -p jobs

CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT}"]
