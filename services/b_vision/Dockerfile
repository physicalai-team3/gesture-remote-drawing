FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
# opencv 는 libGL, mediapipe C 바인딩(0.10.3x)은 libGLESv2·libEGL 을 연다 (CPU 모드여도 필요)
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgles2 libegl1 \
    && rm -rf /var/lib/apt/lists/*
COPY services/b_vision/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Hand Landmarker 모델 (float16 v1, 7,819,105 B) — 빌드 시 1회 다운로드, sha256 이 다르면 빌드 실패
# (2026-10-29 기준 float16/latest 와 같은 파일. 모델을 바꿀 때는 URL 과 해시를 함께 바꾼다)
ARG MODEL_URL=https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
ARG MODEL_SHA256=fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1
RUN mkdir -p /models && python -c "import hashlib, sys, urllib.request; p = '/models/hand_landmarker.task'; urllib.request.urlretrieve(sys.argv[1], p); h = hashlib.sha256(open(p, 'rb').read()).hexdigest(); sys.exit(0 if h == sys.argv[2] else f'model sha256 mismatch: {h}')" "$MODEL_URL" "$MODEL_SHA256"
ENV MODEL_PATH=/models/hand_landmarker.task
COPY shared ./shared
COPY services/b_vision/app ./app
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
