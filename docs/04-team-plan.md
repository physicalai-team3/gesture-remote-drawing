# 04. 3인 분업 계획

## 1. 역할 분담 — 1인 1컨테이너

| | 👤 팀원 1 — **연결** | 👤 팀원 2 — **눈** | 👤 팀원 3 — **두뇌와 손** |
|---|---|---|---|
| 컨테이너 | **A gateway** + cloudflared + compose | **B vision** | **C gesture** + 그림판 렌더링 |
| 파일 | `services/a_gateway/app/**`, `services/a_gateway/static/phone.html`, `static/board.html`(레이아웃), `docker-compose*.yml`, `.env.example`, `tools/fake_phone.py`, `tools/check_a.py` | `services/b_vision/**`, `tools/replay_landmarks.py` | `services/c_gesture/**`, `services/a_gateway/static/board.js`, `shared/fake_hand.py`, `tools/make_samples.py` |
| 핵심 과제 | QR 페어링·토큰, 폰 카메라 → WS, 최신 프레임 슬롯, B·C 호출 조율, 재접속, 통계 | MediaPipe CPU 추론 속도(목표 < 35ms), 검출 안정성(조명·거리), 세션별 추적 인스턴스 | 손가락 판정 규칙, 스무딩·디바운스·상태 머신, 그리기 명령 → 캔버스(획·지우개·undo·커서) |
| 계약 | §2~§4 (board·phone ↔ A) | §6 (A ↔ B) | §5 (그리기 명령), §7 (A ↔ C) |
| 상대 없이 개발 | B를 `VISION_BACKEND=mock`으로 | `replay_landmarks.py`로 웹캠 → B 직접 호출 | `shared/samples/`, 단위 테스트, mock B로 전체 띄워 board 확인 |

**왜 board.js가 팀원 3인가?** 그리기 명령(§5)을 만드는 쪽(C)과 실행하는 쪽(board)이 같은 사람이면, 명령 형식을 바꿔도 팀 간 조율이 필요 없다. A는 `frame_result`를 **그대로 전달**만 한다. 또한 A(백엔드+폰+인프라)가 가장 무겁고 C가 가장 가벼워서 작업량도 맞춰진다.

**공동 소유**: `shared/schemas.py`, `docs/03-messages.md`. 수정할 때는 3명 모두 확인한다.

## 2. 타임라인 (하루)

| 시간 | 팀원 1 (A) | 팀원 2 (B) | 팀원 3 (C + board) | 합류 |
|---|---|---|---|---|
| **0:00–0:30** | 함께: 문서 읽기, `shared/schemas.py` 확정, 브랜치 생성 | ← | ← | ✅ **계약 동결** |
| 0:30–2:00 | 세션/QR API, board WS, cloudflared URL 반영 | MediaPipe 이미지 빌드, `/v1/detect`, 지연 측정 | 손가락 판정 + 제스처 분류 + 단위 테스트 | |
| 2:00–3:00 | `phone.html` 카메라 → JPEG → WS, ack 흐름 제어 | `replay_landmarks.py`로 실제 손 확인, VIDEO/IMAGE 모드 비교 | `board.js`: 명령 실행, 커서, undo (mock B로 확인) | |
| **3:00–3:30** | **1차 통합**: `docker compose up` → 폰 QR → 커서가 움직이는지 | ← | ← | ✅ **E2E 1차** |
| 3:30–5:00 | 타임아웃·재접속·통계 HUD, 폰 2대 접속 처리 | 조명·거리별 검출률 확인, 임계값 조정, CPU 스레드 튜닝 | One Euro, 디바운스, 점프 가드, color/clear 제스처 | |
| 5:00–6:00 | 보안 점검(토큰, 크기 제한), PNG 저장 | 팀원 3과 짝으로 실제 손 튜닝 | 실제 손 튜닝 (`EXTEND_RATIO`, `DEBOUNCE_FRAMES`), 디버그 오버레이 | |
| **6:00–7:00** | **2차 통합 + 데모 리허설** | ← | ← | ✅ **데모** |

## 3. Git 협업 규칙

```
main ────────────●───────────────●  (통합 시점에만 merge)
               ╱ │ ╲           ╱ │ ╲
feat/gateway  ●──●  │         ●──●  │      ← 팀원 1
feat/vision    ●──●─┘          ●──●─┘     ← 팀원 2
feat/gesture    ●──●──●─────────●──●──●   ← 팀원 3
```

- 브랜치: `feat/gateway`(1), `feat/vision`(2), `feat/gesture`(3)
- **각자 자기 파일만 수정** (위 표) → merge 충돌이 거의 없다. `static/board.html`의 레이아웃은 팀원 1, `static/board.js`는 팀원 3.
- `shared/`, `docs/03-messages.md` 수정은 커밋 메시지 `[contract] ...` + 단톡방에 바로 공유.
- 통합 시점(3:00, 6:00)에 `main`으로 merge한 뒤 셋 다 `git pull`.

## 4. 서로 기다리지 않고 개발하는 법

### 팀원 1 (A) — B 없이
```bash
VISION_BACKEND=mock docker compose up -d --build     # B가 가짜 손을 돌려줌
python tools/fake_phone.py --phone-url "<그림판 QR 아래 주소>"   # 폰 없이 프레임 송출
python tools/check_a.py                                         # 통합 체크리스트(§5) 중 A 항목 자동 점검
```
mock B는 **검지가 원을 그리고 3초마다 draw ↔ hover로 바뀌는** 손을 돌려준다. 그림판에 점선 원이 그려지면 A가 정상이다.

### 팀원 2 (B) — A 없이
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build b-vision c-gesture
python tools/replay_landmarks.py --src 0      # 웹캠 → B → C, 랜드마크 뼈대와 그림을 창에 표시
curl -X POST --data-binary @hand.jpg -H "Content-Type: image/jpeg" localhost:8001/v1/detect
python tools/bench_vision.py --src hand.mp4   # infer_ms p50·p95, 검출률, 첫 프레임 지연 (--sessions 2 = 폰 2대)
cd services/b_vision && python -m pytest tests  # mock 으로 계약 테스트 (MODEL_PATH 를 주면 실제 MediaPipe 테스트도)
```

### 팀원 3 (C + board) — A·B 없이
```bash
cd services/c_gesture && python -m pytest tests     # 가짜 손(shared/fake_hand.py)으로 규칙·상태 머신 테스트
python tools/make_samples.py                         # 계약 샘플 재생성
VISION_BACKEND=mock docker compose up -d --build     # 전체를 띄워 board.js 렌더링 확인
```
실제 손 튜닝은 팀원 2의 `replay_landmarks.py`를 같이 쓴다. 창에 `fingers`/`raw_gesture`가 표시된다.

## 5. 통합 체크리스트

- [ ] `curl localhost:8000/health`, B·C `/health` 모두 `ok` (1)
- [ ] 그림판 접속 → QR 표시 → 폰 스캔 → board에 "폰 연결됨" (1)
- [ ] HUD: `fps_done` ≥ 10, B `infer_ms` < 35 (2)
- [ ] ☝️ 그리기 / ✌️ 이동 / ✋ 지우개 / 🤟 색 변경 / ✊ 1.5초 전체 지우기 (3)
- [ ] 손을 화면 밖으로 → 획이 300ms 안에 끝남 (3)
- [ ] 폰 새로고침 / 그림판 새로고침 후 재연결 (1)
- [ ] `docker compose stop b-vision` → A가 죽지 않고 `errors.b` 증가 (1·2)
