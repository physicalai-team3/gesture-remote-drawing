"""B(/v1/detect) 속도·검출률 측정 (팀원 2). 폰과 같은 조건(가로 480px, JPEG 품질 70)으로 보낸다.

  # 서버(B 컨테이너)로 측정
  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build b-vision
  python tools/bench_vision.py --src hand.mp4
  python tools/bench_vision.py --src hand.mp4 --sessions 2        # 폰 2대 동시 접속 흉내
  # 컨테이너 없이 같은 코드를 직접 실행 (pip install mediapipe==0.10.35, 모델 파일 필요)
  MODEL_PATH=hand_landmarker.task python tools/bench_vision.py --src hand.mp4 --local
  MODEL_PATH=hand_landmarker.task RUNNING_MODE=image python tools/bench_vision.py --src hand.mp4 --local

--src: 웹캠 번호, 동영상, 이미지 1장, 이미지 폴더. 이미지는 --frames 만큼 반복해서 보낸다.
주의: VIDEO 모드는 앞 프레임의 손 위치를 따라가므로, 서로 다른 사진을 번갈아 보내면 바뀔 때마다
1프레임씩 놓친다(검출률이 낮게 나옴). 사진 폴더의 검출률은 RUNNING_MODE=image 로, 속도는 동영상으로 잰다.
"""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_frames(src: str, width: int, quality: int, limit: int) -> list[bytes]:
    """원본 → 폰과 같은 크기·품질의 JPEG 바이트 목록."""
    p = Path(src)
    if p.is_dir():
        images = [cv2.imread(str(f)) for f in sorted(p.iterdir()) if f.suffix.lower() in IMAGE_EXT]
    elif p.suffix.lower() in IMAGE_EXT:
        images = [cv2.imread(str(p))]
    else:
        cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
        images = []
        while len(images) < limit:
            ok, frame = cap.read()
            if not ok:
                break
            images.append(frame)
        cap.release()
    images = [im for im in images if im is not None]
    if not images:
        sys.exit(f"프레임을 읽지 못했습니다: {src}")
    out = []
    for i in range(limit):
        im = images[i % len(images)]
        im = cv2.resize(im, (width, int(width * im.shape[0] / im.shape[1])))
        out.append(cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes())
    return out


def parse_server_timing(value: str) -> dict[str, float]:
    """'decode;dur=2.1, wait;dur=0.0, infer;dur=18.3' → {'decode': 2.1, ...}"""
    out = {}
    for part in value.split(","):
        name, _, dur = part.strip().partition(";dur=")
        if dur:
            out[name] = float(dur)
    return out


def run_http(base: str, session: str, frames: list[bytes], fps: float, rows: list[dict]) -> None:
    import httpx

    with httpx.Client(timeout=5.0) as client:
        client.delete(f"{base}/v1/sessions/{session}")  # 새 세션으로 시작 → 첫 프레임 비용도 잰다
        for seq, jpg in enumerate(frames):
            t0 = time.perf_counter()
            r = client.post(f"{base}/v1/detect", content=jpg, headers={
                "Content-Type": "image/jpeg", "X-Session": session, "X-Seq": str(seq), "X-Ts-Ms": str(int(time.time() * 1000))})
            rtt = (time.perf_counter() - t0) * 1000
            r.raise_for_status()
            body = r.json()
            st = parse_server_timing(r.headers.get("server-timing", ""))
            rows.append({"session": session, "seq": seq, "rtt": rtt, "infer": body["infer_ms"],
                         "decode": st.get("decode"), "wait": st.get("wait"), "hands": len(body["hands"])})
            if fps:
                time.sleep(max(0.0, 1 / fps - (time.perf_counter() - t0)))
        client.delete(f"{base}/v1/sessions/{session}")


def run_local(session: str, frames: list[bytes], fps: float, rows: list[dict]) -> None:
    sys.path[:0] = [str(ROOT), str(ROOT / "services" / "b_vision")]
    from app.detector import make_detector

    det = make_detector()
    for seq, jpg in enumerate(frames):
        t0 = time.perf_counter()
        rgb = cv2.cvtColor(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        t1 = time.perf_counter()
        hands = det.detect(session, rgb, int(time.time() * 1000))
        t2 = time.perf_counter()
        rows.append({"session": session, "seq": seq, "rtt": (t2 - t0) * 1000, "infer": (t2 - t1) * 1000,
                     "decode": (t1 - t0) * 1000, "wait": 0.0, "hands": len(hands)})
        if fps:
            time.sleep(max(0.0, 1 / fps - (time.perf_counter() - t0)))
    det.close_all()


def summarize(rows: list[dict], label: str) -> None:
    rest = [r for r in rows if r["seq"] > 0]  # 첫 프레임(손바닥 검출 + 인스턴스 생성)은 따로
    first = [r for r in rows if r["seq"] == 0]

    def stat(key: str, data: list[dict]) -> str:
        v = np.array([r[key] for r in data if r[key] is not None])
        if not len(v):
            return "-"
        return f"p50 {np.percentile(v, 50):6.1f}  p95 {np.percentile(v, 95):6.1f}  max {v.max():6.1f}"

    print(f"\n== {label}: 세션 {len({r['session'] for r in rows})}개, 프레임 {len(rows)}개")
    for key, name in (("infer", "infer_ms"), ("decode", "decode_ms"), ("wait", "wait_ms"), ("rtt", "요청 전체 ms")):
        print(f"  {name:<12} {stat(key, rest)}")
    print(f"  첫 프레임    infer {np.mean([r['infer'] for r in first]):.1f}ms, 요청 전체 {np.mean([r['rtt'] for r in first]):.1f}ms")
    print(f"  검출률       {np.mean([r['hands'] > 0 for r in rows]) * 100:.1f}%  (손이 1개 이상 나온 프레임 비율)")
    p95 = np.percentile([r["infer"] for r in rest], 95) if rest else float("nan")
    print(f"  목표 infer p95 < 35ms: {'통과' if p95 < 35 else '미달'}")


def main(a: argparse.Namespace) -> None:
    frames = load_frames(a.src, a.width, a.quality, a.frames)
    rows: list[dict] = []
    if a.local:
        run_local("bench", frames, a.fps, rows)
        label = f"local backend={os.getenv('VISION_BACKEND', 'mediapipe')} mode={os.getenv('RUNNING_MODE', 'video')}"
    else:
        import httpx

        try:
            print("B:", httpx.get(f"{a.b}/health", timeout=3.0).json())
        except httpx.HTTPError as e:
            sys.exit(f"B 에 연결하지 못했습니다 ({a.b}): {e}")
        threads =[threading.Thread(target=run_http, args=(a.b, f"bench{i}", frames, a.fps, rows)) for i in range(a.sessions)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        label = f"http {a.b}"
    summarize(rows, f"{label} src={a.src} {a.width}px q{a.quality}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="0", help="웹캠 번호, 동영상, 이미지, 이미지 폴더")
    p.add_argument("--b", default="http://localhost:8001")
    p.add_argument("--frames", type=int, default=300, help="보낼 프레임 수 (세션마다)")
    p.add_argument("--fps", type=float, default=0, help="초당 전송 상한 (0 = 응답 오는 대로, 폰 기본은 15)")
    p.add_argument("--sessions", type=int, default=1, help="동시 세션 수 (폰 여러 대 흉내)")
    p.add_argument("--width", type=int, default=480)
    p.add_argument("--quality", type=int, default=70)
    p.add_argument("--local", action="store_true", help="서버 없이 app/detector.py 를 직접 실행")
    main(p.parse_args())
