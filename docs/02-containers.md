# 02. 컨테이너 상세

> 환경변수 기본값은 [`.env.example`](../.env.example). 포트는 모두 도커 내부망 기준이며 **호스트에는 A의 8000만 공개**한다.

## Container A — gateway (웹/보안 서버) · `:8000`

| 항목 | 내용 |
|---|---|
| 위치 | [`services/a_gateway/`](../services/a_gateway/) |
| 역할 | 세션·QR 페어링, 폰/그림판 WebSocket, 정적 페이지(`board.html`, `phone.html`), B·C 호출 조율, 통계 |
| 상태 | `SessionStore` (메모리). 세션: id, token, 폰 WS, 그림판 WS 목록, 최신 프레임 슬롯, config, stats |
| 공개 경로 | `/` → 그림판, `/phone` → 폰 페이지, `/api/*` REST, `/ws/*` WebSocket |

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PUBLIC_URL` | (빈 값) | 비우면 cloudflared `/quicktunnel`에서 자동 조회 |
| `CLOUDFLARED_METRICS` | `http://cloudflared:2000` | 터널 URL 조회 주소 |
| `B_URL` | `http://b-vision:8001` | |
| `C_URL` | `http://c-gesture:8002` | |
| `STAGE_TIMEOUT_MS` | `1000` | B·C 호출 타임아웃 |
| `TARGET_FPS` | `15` | 폰에 알려주는 전송 fps |
| `FRAME_WIDTH` | `480` | 폰에 알려주는 프레임 폭 |
| `JPEG_QUALITY` | `0.7` | 폰 JPEG 품질 |
| `MAX_FRAME_BYTES` | `300000` | 이보다 큰 프레임은 거부 |
| `SESSION_TTL_S` | `600` | 폰·그림판이 모두 끊긴 세션 삭제까지 |

## Container B — vision (영상 분석 엔진) · `:8001`

| 항목 | 내용 |
|---|---|
| 위치 | [`services/b_vision/`](../services/b_vision/) |
| 역할 | JPEG → RGB 디코드 → MediaPipe Hand Landmarker → 21개 랜드마크 (정규화 x,y,z) |
| 상태 | 세션별 `HandLandmarker` (VIDEO 모드는 타임스탬프가 단조 증가해야 해서 세션마다 분리). 최대 `MAX_SESSIONS`개, LRU로 정리 |
| 모델 | `hand_landmarker.task` (float16, ~7.5MB). Dockerfile에서 빌드 시 다운로드 |
| 백엔드 | `VISION_BACKEND=mediapipe` (실제) / `mock` (가짜 손: 원을 그리는 검지 — A 개발용) |

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `VISION_BACKEND` | `mediapipe` | `mediapipe` \| `mock` |
| `NUM_HANDS` | `1` | 1이면 가장 빠름 |
| `MIN_DETECTION_CONF` | `0.5` | 손바닥 검출 임계값 |
| `MIN_TRACKING_CONF` | `0.5` | 추적 임계값 (낮으면 덜 끊기고, 높으면 덜 튐) |
| `RUNNING_MODE` | `video` | `video`(추적, 빠름) \| `image`(매 프레임 검출, 안정적이지만 느림) |
| `MAX_SESSIONS` | `4` | |
| `OMP_NUM_THREADS` | `2` | |

**MediaPipe 21개 랜드마크 번호** (C가 사용):
```
0 손목  | 엄지 1-2-3-4 | 검지 5-6-7-8 | 중지 9-10-11-12 | 약지 13-14-15-16 | 소지 17-18-19-20
         (MCP-PIP-DIP-TIP 순, 엄지는 CMC-MCP-IP-TIP)
```

## Container C — gesture (동작 인식 엔진) · `:8002`

| 항목 | 내용 |
|---|---|
| 위치 | [`services/c_gesture/`](../services/c_gesture/) |
| 역할 | 좌표 변화량 계산, 제어 규칙 판별, 그리기 명령 생성 |
| 상태 | 세션별 `GestureSession`: One Euro 필터, 제스처 디바운스, 현재 펜 상태, 진행 중 stroke id, 현재 색 |
| 처리 순서 | ① mirror 적용 → ② 손가락 펴짐 판정 → ③ 제스처 분류 → ④ N프레임 디바운스 → ⑤ 커서 스무딩 → ⑥ 상태 머신 → ⑦ commands |

### 제스처 규칙 (초기값, 실험 후 조정)

| 제스처 | 손 모양 | 동작 | 트리거 |
|---|---|---|---|
| `draw` | ☝️ 검지만 폄 | 펜 내림, 검지 끝(8)으로 그리기 | 상태 유지 |
| `hover` | ✌️ 검지+중지 폄 | 펜 올림, 커서만 이동 | 상태 유지 |
| `erase` | ✋ 검지~소지 4개 폄 (엄지 무관) | 지우개, 손바닥 중심(9)으로 지우기 | 상태 유지 |
| `color` | 🤟 검지+중지+약지 폄 | 다음 색으로 변경 | **진입 순간 1회** |
| `zoom` | 🤏 검지만 펴고 엄지를 옆으로 벌림 (`thumb_spread` > `ZOOM_THUMB_OUT`) | 엄지 끝~검지 끝 거리 변화로 확대·축소, 중심은 핀치 시작 위치 | 상태 유지 |
| `clear` | ✊ 주먹 (엄지 무관) `CLEAR_HOLD_MS`(1500ms) 유지 | 전체 지우기 | 유지 시간 충족 시 1회 |
| `none` | 손 없음 / 그 외 | 펜 올림 | `LOST_HAND_MS` 후 stroke 종료 + 제스처 상태 초기화 |

엄지 '펴짐 비율'은 모든 제스처에서 무시한다 (사람마다 엄지 자세가 제각각이고 판정도 가장 흔들림). 대신 핀치는 엄지 끝의 **위치**로 판정한다: `thumb_spread` = 엄지 끝~검지 뿌리 거리 / 손 크기(손목~중지 뿌리). 실측값은 엄지 접은 그리기 0.18~0.33, 핀치 1.29~1.56이다. 핀치를 꽉 오므리다 검지가 굽어도, 이미 zoom 상태라면 주먹(clear)으로 넘어가지 않는다. 손이 여러 개면 `score`가 가장 높은 손을 쓴다.

**손가락 펴짐 판정** (회전에 강하게): 손가락 끝(TIP)이 PIP 관절보다 손목에서 `EXTEND_RATIO`배 이상 멀면 "폄". 엄지는 끝(4)과 소지 MCP(17) 거리 vs 엄지 IP(3)와 17 거리로 판정.

**떨림·튐 방지**
- One Euro Filter (`MIN_CUTOFF=1.0`, `BETA=0.02`): 천천히 움직일 땐 강하게, 빠를 땐 약하게 스무딩.
- 디바운스: 같은 제스처가 `DEBOUNCE_FRAMES`(3) 연속이어야 상태 전환.
- 점프 가드: 한 프레임에 **필터 전** 커서가 `JUMP_MAX`(0.25) 이상 움직이면 획을 끊고 새로 시작 (필터 후 좌표로는 순간이동이 뭉개져 못 잡음). 필터도 리셋해 커서가 새 위치로 바로 이동.
- 가장자리 확대: 카메라 가장자리 `EDGE_MARGIN`(0.1)을 버리고 안쪽 80%를 그림판 전체로 늘린다. 손이 화면 끝에 가면 MediaPipe가 놓치기 쉬워서, 손을 덜 움직여도 그림판 끝까지 닿게 한다.
- 최소 이동: `MIN_MOVE`(0.003)보다 적게 움직이면 `stroke_point`를 보내지 않음 (명령 수 절감).

| 환경변수 | 기본값 |
|---|---|
| `DEBOUNCE_FRAMES` | `3` |
| `EXTEND_RATIO` | `1.15` |
| `LOST_HAND_MS` | `300` |
| `CLEAR_HOLD_MS` | `1500` |
| `JUMP_MAX` | `0.25` |
| `MIN_MOVE` | `0.003` |
| `ONE_EURO_MIN_CUTOFF` | `1.0` |
| `ONE_EURO_BETA` | `0.02` |
| `EDGE_MARGIN` | `0.1` |
| `ZOOM_THUMB_OUT` | `0.8` |
| `ZOOM_GAIN` | `1.0` (핀치 거리 1.0 변화당 e^gain 배. 오므림 0.1 → 활짝 1.4 ≈ 3.7배) |
| `ZOOM_DEADBAND` | `0.05` (핀치 거리가 이만큼 변해야 zoom 명령) |
| `SESSION_TTL_S` | `600` (A와 공유, 이 시간 동안 안 쓰인 세션 정리) |

## cloudflared (터널)

`cloudflare/cloudflared` 이미지로 `tunnel --url http://a-gateway:8000` 실행 → `https://xxxx.trycloudflare.com` 발급. A가 metrics 포트(`:2000/quicktunnel`)에서 주소를 읽어 QR에 넣는다. 조회가 안 되면 로그(`docker compose logs cloudflared`)에서 URL을 찾아 `.env`의 `PUBLIC_URL`에 넣는다.
