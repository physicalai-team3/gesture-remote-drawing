FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
# opencv 는 libGL, mediapipe C 바인딩(0.10.3x)은 libGLESv2·libEGL 을 연다 (CPU 모드여도 필요)
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgles2 libegl1 \
    && rm -rf /var/lib/apt/lists/*
COPY services/b_vision/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Hand Landmarker 모델 (float16, ~7.5MB) — 빌드 시 1회 다운로드
ARG MODEL_URL=https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
RUN mkdir -p /models && python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/models/hand_landmarker.task')" "$MODEL_URL"
ENV MODEL_PATH=/models/hand_landmarker.task
COPY shared ./shared
COPY services/b_vision/app ./app
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
