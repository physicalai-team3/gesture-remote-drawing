# 03. 메시지 계약

> 이 문서와 [`shared/schemas.py`](../shared/schemas.py)는 **항상 함께** 수정합니다. 계약을 바꾸는 커밋은 세 사람이 모두 확인합니다.
> 예제 메시지는 [`shared/samples/`](../shared/samples/)에 있습니다. 상대방 코드 없이 이 파일로 테스트하세요.

## 0. 공통 규칙

| 항목 | 규칙 |
|---|---|
| `session` | A가 발급하는 6자 소문자+숫자 (예: `k3x9q2`) |
| `token` | A가 발급하는 페어링 토큰. 폰 URL(QR)에만 들어가며, 폰 WS 접속 시 검증 |
| `seq` | **A가 세션별로 매기는 단조 증가 정수** (0부터). 폰이 재접속해도 이어서 증가 |
| 시간 `t_ms` | epoch 밀리초 (int). **A가 프레임을 받은 시각** 기준 (폰·노트북 시계 차이 무시) |
| 좌표 | **0~1 정규화**, 원점은 좌상단, x→오른쪽, y→아래. B 출력은 **원본 이미지 기준**(반전 안 함), C 출력은 **그림판 기준**(mirror 적용 후) |
| 색 | `#rrggbb` 문자열 |
| 인코딩 | JSON UTF-8, 키는 snake_case. 이미지는 JPEG |
| 버전 | 모든 HTTP 응답·WS 첫 메시지에 `"v": 1`. 호환이 깨지는 변경 시 올림 |

---

## 1. 전체 시퀀스

```
board(PC)        A gateway                  phone            B vision        C gesture
  │ POST /api/sessions                                                          
  │───────────────▶│ {session, phone_url, qr_url}                                
  │◀───────────────│                                                              
  │ WS /ws/board?s=│                                                              
  │═══════════════▶│                                                              
  │◀── session ────│                                                              
  │                │◀═══ WS /ws/phone?s=&t= ════│  (QR 스캔)                          
  │◀── phone{connected:true}                    │                                 
  │                │◀── hello (text) ───────────│                                 
  │                │─── config (text) ─────────▶│                                 
  │                │◀── JPEG (binary) ──────────│  ┐                              
  │                │─── ack {seq} ─────────────▶│  │ 반복 (폰은 미확인 프레임 2개까지)    
  │                │── POST /v1/detect ─────────────────────────▶│                   
  │                │◀─ DetectResponse ──────────────────────────│                   
  │                │── POST /v1/interpret ─────────────────────────────────────▶│     
  │                │◀─ InterpretResponse ──────────────────────────────────────│     
  │◀─ frame_result │                                              ┘                 
  │◀─ stats (1초)  │─── stats (1초) ───────────▶│                                 
```

---

## 2. REST — board ↔ A

### `POST /api/sessions` → `201`
```json
{
  "v": 1,
  "session": "k3x9q2",
  "phone_url": "https://brave-cat-1234.trycloudflare.com/phone?s=k3x9q2&t=Zk3...",
  "qr_url": "/api/sessions/k3x9q2/qr.png",
  "public_url": "https://brave-cat-1234.trycloudflare.com"
}
```
터널 주소를 아직 모르면 `public_url`, `phone_url`은 `null`. 나중에 board WS로 `session` 메시지를 다시 보낸다.

### `GET /api/sessions/{session}` → `200` (위와 같음) / `404`
그림판 새로고침 시 `localStorage`의 세션 ID로 먼저 조회.

### `GET /api/sessions/{session}/qr.png` → PNG

### `GET /health` → `{"ok": true, "service": "a-gateway"}`  (B, C도 같은 형식)

---

## 3. WebSocket — phone ↔ A (`/ws/phone?s={session}&t={token}`)

토큰이 틀리면 A는 코드 `4401`로 닫는다. 세션이 없으면 `4404`. 다른 폰이 접속하면 기존 폰을 `4409`(replaced)로 닫는다.

### phone → A

**`hello`** (text, 접속 직후 1회)
```json
{"type": "hello", "w": 480, "h": 360, "facing": "user", "ua": "Mozilla/5.0 ..."}
```
`facing`: `"user"`(전면, 거울) | `"environment"`(후면). A는 이 값으로 C의 `mirror` 기본값을 정한다.

**프레임** (binary): **JPEG 바이트 그대로**. 헤더 없음. A가 수신 순간 `seq`, `t_ms`를 붙인다.

### A → phone

**`config`** (hello 직후, 설정 변경 시)
```json
{"type": "config", "v": 1, "fps": 15, "width": 480, "quality": 0.7, "max_inflight": 2}
```

**`ack`** (프레임 **수신 즉시**)
```json
{"type": "ack", "seq": 128}
```
폰은 ack를 받지 못한 프레임이 `max_inflight`개면 다음 캡처를 건너뛴다 → 네트워크 큐가 쌓이지 않는다.

**`stats`** (1초마다)
```json
{"type": "stats", "fps_in": 14.8, "fps_done": 14.1, "dropped": 3, "latency_ms": 42.0, "hand": true}
```

---

## 4. WebSocket — board ↔ A (`/ws/board?s={session}`)

### A → board

**`session`** (접속 직후, 터널 URL이 바뀌었을 때)
```json
{"type": "session", "v": 1, "session": "k3x9q2", "phone_url": "https://.../phone?s=k3x9q2&t=...", "qr_url": "/api/sessions/k3x9q2/qr.png"}
```

**`phone`** (폰 연결 상태 변화)
```json
{"type": "phone", "connected": true, "facing": "user"}
```

**`frame_result`** (프레임 처리 완료마다) — **그림판이 그리는 데 쓰는 유일한 메시지**
```json
{
  "type": "frame_result",
  "seq": 128,
  "gesture": "draw",
  "cursor": {"x": 0.512, "y": 0.334, "mode": "draw"},
  "commands": [
    {"op": "stroke_point", "id": 7, "x": 0.512, "y": 0.334}
  ],
  "landmarks": [[0.41, 0.72], [0.45, 0.70], "... 21개, 그림판 기준(mirror 적용) — 디버그 오버레이용, 손 없으면 null"],
  "timing": {"b_ms": 21.3, "c_ms": 0.4, "total_ms": 24.9}
}
```

**`stats`** (1초마다)
```json
{"type": "stats", "fps_in": 14.8, "fps_done": 14.1, "dropped": 3, "latency_ms": 24.9, "errors": {"b": 0, "c": 0}}
```

### board → A

**`config`** (사용자가 설정 변경 시. 보낸 키만 덮어씀)
```json
{"type": "config", "mirror": true, "width": 6, "palette": ["#111111", "#e53935", "#1e88e5", "#43a047", "#fdd835"]}
```

**`reset`** (그림판의 "초기화" 버튼 — C의 펜 상태만 리셋, 그림 지우기는 board가 직접)
```json
{"type": "reset"}
```

---

## 5. 그리기 명령 `commands[]` (C가 만들고, board가 실행)

| `op` | 필드 | board 동작 |
|---|---|---|
| `stroke_begin` | `id`, `x`, `y`, `color`, `width`, `tool`(`pen`\|`eraser`) | 새 획 시작 (`moveTo`) |
| `stroke_point` | `id`, `x`, `y` | 획에 점 추가 (`lineTo` / 곡선 보간) |
| `stroke_end` | `id` | 획 종료 (undo 스택에 push) |
| `set_color` | `color` | 현재 색 표시 변경 (다음 획부터 적용) |
| `clear` | — | 캔버스 전체 지우기 |
| `zoom` | `factor`, `x`, `y` | 화면 확대·축소. `factor`는 **직전 zoom 대비** 배율 변화(>1 확대, <1 축소), `(x, y)`는 확대 중심(화면 기준 0~1). 누적 배율의 범위 제한(1~4배)은 board가 한다 |

- 한 `frame_result`에 여러 명령이 올 수 있다 (예: `stroke_end` → `stroke_begin`). **배열 순서대로 실행**.
- `id`는 세션 내 단조 증가 정수. board는 모르는 `id`의 `stroke_point`는 무시한다.
- 커서(`cursor`)는 명령이 아니라 **매 프레임의 현재 위치**다. `mode`: `draw` | `hover` | `erase` | `zoom` | `idle`.
- 모든 좌표(`stroke_*`, `cursor`, `zoom`)는 **화면 기준**이다. 확대된 상태라면 board가 화면 좌표 → 그림 좌표로 변환해서 저장한다. C는 확대 상태를 모른다.
- `width`는 그림판 짧은 변 기준 **px (1000px 환산)** — board가 실제 크기에 맞춰 스케일.

---

## 6. HTTP — A ↔ B (`POST /v1/detect`)

**요청**: body = JPEG 바이트, `Content-Type: image/jpeg`

| 헤더 | 예 | 설명 |
|---|---|---|
| `X-Session` | `k3x9q2` | B가 세션별 추적 인스턴스를 고를 때 사용 |
| `X-Seq` | `128` | 그대로 응답에 돌려줌 |
| `X-Ts-Ms` | `1761710000123` | VIDEO 모드 타임스탬프 (B가 단조 증가 보정) |

**응답 `200`** (`DetectResponse`)
```json
{
  "v": 1,
  "seq": 128,
  "w": 480,
  "h": 360,
  "backend": "mediapipe",
  "infer_ms": 21.3,
  "hands": [
    {
      "handedness": "Right",
      "score": 0.97,
      "landmarks": [[0.41, 0.72, 0.0], [0.45, 0.70, -0.01], "... 총 21개 [x, y, z]"]
    }
  ]
}
```
- 손이 없으면 `"hands": []` (에러 아님).
- `landmarks[i]` = `[x, y, z]`, x·y는 이미지 기준 0~1, z는 손목 기준 상대 깊이 (작을수록 카메라에 가까움).
- `handedness`는 MediaPipe 원본 값 그대로 (전면 카메라면 좌우가 반대로 나옴 — C가 처리).
- 디코드 실패 `400`, 내부 오류 `500`.

### `DELETE /v1/sessions/{session}` → `204`
세션 종료 시 A가 호출. B는 해당 MediaPipe 인스턴스 해제.

---

## 7. HTTP — A ↔ C (`POST /v1/interpret`)

**요청** (`InterpretRequest`)
```json
{
  "v": 1,
  "session": "k3x9q2",
  "seq": 128,
  "t_ms": 1761710000123,
  "hands": [ {"handedness": "Right", "score": 0.97, "landmarks": [[0.41, 0.72, 0.0], "..."]} ],
  "config": {"mirror": true, "width": 6, "palette": ["#111111", "#e53935", "#1e88e5", "#43a047", "#fdd835"]}
}
```
`hands`는 B 응답을 **그대로** 넣는다. `config`는 A가 세션별로 보관하는 값.

**응답 `200`** (`InterpretResponse`)
```json
{
  "v": 1,
  "seq": 128,
  "gesture": "draw",
  "cursor": {"x": 0.512, "y": 0.334, "mode": "draw"},
  "commands": [{"op": "stroke_point", "id": 7, "x": 0.512, "y": 0.334}],
  "landmarks": [[0.59, 0.72], "... mirror 적용된 21개 [x, y], 손 없으면 null"],
  "debug": {"fingers": [false, true, false, false, false], "raw_gesture": "draw", "stable_count": 5}
}
```
- `gesture`: `draw` | `hover` | `erase` | `color` | `clear` | `zoom` | `none`
- `cursor`는 손이 없으면 `null`.
- `debug`는 자유 형식 (board 디버그 패널에 그대로 표시).

### `POST /v1/sessions/{session}/reset` → `200 {"commands": [...]}`
폰 끊김, board의 `reset` 시 A가 호출. 진행 중 획이 있으면 `stroke_end` 명령을 돌려주고, A는 이를 board에 전달한다.

### `DELETE /v1/sessions/{session}` → `204`

---

## 8. 계약 변경 절차

1. `shared/schemas.py`와 이 문서를 **같은 커밋**에서 수정
2. `shared/samples/*.json` 갱신 (`python tools/make_samples.py`)
3. `python -m pytest tests` 통과 확인 (샘플이 스키마에 맞는지 검사)
4. 커밋 메시지에 `[contract]` 접두어 → 나머지 두 사람이 확인 후 merge
