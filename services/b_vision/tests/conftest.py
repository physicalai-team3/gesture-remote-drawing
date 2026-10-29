import os
import sys
from pathlib import Path

# 저장소 루트(shared/)와 서비스 루트(app/)를 import 경로에 추가
sys.path[:0] = [str(Path(__file__).resolve().parents[3]), str(Path(__file__).resolve().parents[1])]
# API 테스트는 모델 없이 가짜 손으로 (test_detector.py 는 MediaPipe 를 직접 만든다)
os.environ.setdefault("VISION_BACKEND", "mock")
