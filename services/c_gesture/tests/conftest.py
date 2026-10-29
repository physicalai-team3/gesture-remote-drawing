import sys
from pathlib import Path

# 저장소 루트(shared/)와 서비스 루트(app/)를 import 경로에 추가
sys.path[:0] = [str(Path(__file__).resolve().parents[3]), str(Path(__file__).resolve().parents[1])]
