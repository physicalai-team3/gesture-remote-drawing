// 그림판: A 의 frame_result.commands 를 실행한다. 계약: docs/03-messages.md §4·§5
const $ = (id) => document.getElementById(id);
const board = $("board"), overlay = $("overlay");
const bctx = board.getContext("2d"), octx = overlay.getContext("2d");

// ── 획 저장소 (undo·리사이즈·확대 시 다시 그리기 위해 '그림 좌표'(확대 1배 기준 0~1)로 보관) ──
const strokes = [];          // 완료된 획: {tool, color, width, pts:[[x,y],...]}
const live = new Map();      // 진행 중 획: id → stroke
let currentColor = "#111111", penWidth = 6;
let lastCursor = null, lastLandmarks = null;
const ERASER_MULT = 5;       // 지우개는 펜 굵기의 5배

function scale() { return Math.min(board.width, board.height) / 1000; }
function px(x, y) { return [x * board.width, y * board.height]; }   // 화면 좌표 → 픽셀 (커서·랜드마크)
const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];

// ── 확대·축소: 화면에 보이는 영역 = 그림 좌표 [ox, ox+1/s] × [oy, oy+1/s] ──
// C 가 보내는 좌표는 모두 화면 기준이라, 획은 toWorld 로 그림 좌표로 바꿔 저장하고 wpx 로 다시 화면에 그린다.
const MAX_ZOOM = 4;
const view = { s: 1, ox: 0, oy: 0 };
const toWorld = (x, y) => [view.ox + x / view.s, view.oy + y / view.s];
const wpx = (x, y) => px((x - view.ox) * view.s, (y - view.oy) * view.s);

function zoomAt(f, x, y) {
  const s2 = Math.min(MAX_ZOOM, Math.max(1, view.s * f));
  const [wx, wy] = toWorld(x, y);   // 확대 중심 아래의 그림 위치는 그대로 두고, 그림판 밖은 보이지 않게
  view.ox = Math.min(Math.max(wx - x / s2, 0), 1 - 1 / s2);
  view.oy = Math.min(Math.max(wy - y / s2, 0), 1 - 1 / s2);
  view.s = s2;
  redraw();
}
function resetZoom() { Object.assign(view, { s: 1, ox: 0, oy: 0 }); redraw(); }

// 점들을 중점끼리 2차 곡선으로 잇는다 (15fps 에서도 선이 각지지 않게).
// 점 i 가 들어오면 '이전 중점 → (제어점 i-1) → 새 중점' 구간을 그리고, 마지막 반 구간은 획이 끝날 때 drawTail 로 채운다.
function stroke(s, path) {
  bctx.save();
  bctx.globalCompositeOperation = s.tool === "eraser" ? "destination-out" : "source-over";
  bctx.strokeStyle = s.color;
  bctx.lineWidth = s.width * view.s * scale() * (s.tool === "eraser" ? ERASER_MULT : 1);
  bctx.lineCap = bctx.lineJoin = "round";
  bctx.beginPath(); path(); bctx.stroke();
  bctx.restore();
}

function drawSegment(s, i) {
  const p = s.pts;
  if (i === 0) stroke(s, () => { bctx.moveTo(...wpx(...p[0])); bctx.lineTo(...wpx(...p[0])); });   // 점 하나도 보이게
  else if (i === 1) stroke(s, () => { bctx.moveTo(...wpx(...p[0])); bctx.lineTo(...wpx(...mid(p[0], p[1]))); });
  else stroke(s, () => {
    bctx.moveTo(...wpx(...mid(p[i - 2], p[i - 1])));
    bctx.quadraticCurveTo(...wpx(...p[i - 1]), ...wpx(...mid(p[i - 1], p[i])));
  });
}

function drawTail(s) {
  const p = s.pts, n = p.length;
  if (n >= 2) stroke(s, () => { bctx.moveTo(...wpx(...mid(p[n - 2], p[n - 1]))); bctx.lineTo(...wpx(...p[n - 1])); });
}

function redraw() {
  bctx.clearRect(0, 0, board.width, board.height);
  for (const s of strokes) { s.pts.forEach((_, i) => drawSegment(s, i)); drawTail(s); }
  for (const s of live.values()) s.pts.forEach((_, i) => drawSegment(s, i));
}

function resize() {
  const r = board.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  for (const c of [board, overlay]) { c.width = r.width * dpr; c.height = r.height * dpr; }
  redraw();
}
window.addEventListener("resize", resize);

function run(cmd) {
  switch (cmd.op) {
    case "stroke_begin": {
      // 굵기는 화면에서 보이는 굵기가 되도록 그림 좌표로 환산 (확대해서 그리면 그만큼 가는 선 = 정밀하게)
      const s = { tool: cmd.tool, color: cmd.color, width: cmd.width / view.s, pts: [toWorld(cmd.x, cmd.y)] };
      penWidth = cmd.width; live.set(cmd.id, s); drawSegment(s, 0); break;
    }
    case "stroke_point": {
      const s = live.get(cmd.id); if (!s) break;   // 모르는 id 는 무시 (계약 §5)
      s.pts.push(toWorld(cmd.x, cmd.y)); drawSegment(s, s.pts.length - 1); break;
    }
    case "stroke_end": {
      const s = live.get(cmd.id); if (!s) break;
      live.delete(cmd.id); drawTail(s); strokes.push(s); break;
    }
    case "set_color": currentColor = cmd.color; $("curColor").style.background = cmd.color; break;
    case "clear": strokes.length = 0; live.clear(); redraw(); break;
    case "zoom": zoomAt(cmd.factor, cmd.x, cmd.y); break;
  }
}

// ── 오버레이: 커서 + (디버그) 랜드마크 ──
const BONES = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],
               [9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];
function drawOverlay() {
  octx.clearRect(0, 0, overlay.width, overlay.height);
  if ($("debug").checked && lastLandmarks) {
    octx.strokeStyle = "rgba(42,157,143,.6)"; octx.lineWidth = 2;
    for (const [a, b] of BONES) {
      octx.beginPath(); octx.moveTo(...px(...lastLandmarks[a])); octx.lineTo(...px(...lastLandmarks[b])); octx.stroke();
    }
  }
  if (lastCursor) {
    const [x, y] = px(lastCursor.x, lastCursor.y);
    const r = lastCursor.mode === "erase" ? penWidth * ERASER_MULT / 2 * scale() : 8 * scale() + 4;   // 지우개는 실제 지우는 크기
    octx.beginPath(); octx.arc(x, y, r, 0, Math.PI * 2);
    octx.fillStyle = { draw: currentColor, hover: "rgba(0,0,0,.15)", erase: "rgba(209,73,91,.15)",
                       zoom: "rgba(42,157,143,.25)", idle: "rgba(0,0,0,.08)" }[lastCursor.mode];
    octx.fill(); octx.strokeStyle = "#555"; octx.lineWidth = 1; octx.stroke();
  }
  requestAnimationFrame(drawOverlay);
}

// ── 세션·WS ──
let ws, hudStats = {}, hudFrame = {};
async function getSession() {
  const saved = localStorage.getItem("session");
  if (saved) {
    const r = await fetch(`/api/sessions/${saved}`);
    if (r.ok) return r.json();
  }
  const s = await (await fetch("/api/sessions", { method: "POST" })).json();
  localStorage.setItem("session", s.session);
  return s;
}

function showSession(m) {
  $("sid").textContent = m.session;
  $("phoneUrl").textContent = m.public_url ? m.phone_url : "⚠ 터널 주소 확인 중 — 폰 카메라는 HTTPS 에서만 동작합니다";
  $("qr").src = `${m.qr_url}?t=${Date.now()}`;
}

function connect(sid) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/board?s=${sid}`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "session") showSession(m);
    else if (m.type === "phone") {
      $("phoneDot").classList.toggle("on", m.connected);
      $("phoneTxt").textContent = m.connected ? `폰 연결됨${m.facing ? ` (${m.facing})` : ""}` : "폰 연결 대기";
      $("pair").classList.toggle("hidden", m.connected);
      if (m.facing) $("mirror").checked = m.facing !== "environment";   // A 가 facing 으로 정한 mirror 기본값과 맞춤
    } else if (m.type === "frame_result") {
      m.commands.forEach(run);
      lastCursor = m.cursor; lastLandmarks = m.landmarks;
      hudFrame = { gesture: m.gesture, ...m.timing };
    } else if (m.type === "stats") hudStats = m;
    $("hud").textContent =
      `gesture ${hudFrame.gesture ?? "-"}  zoom ${view.s.toFixed(1)}x  B ${hudFrame.b_ms ?? "-"}ms  C ${hudFrame.c_ms ?? "-"}ms\n` +
      `fps in ${hudStats.fps_in ?? "-"} / done ${hudStats.fps_done ?? "-"}  drop ${hudStats.dropped ?? "-"}  ` +
      `latency ${hudStats.latency_ms ?? "-"}ms  err B${hudStats.errors?.b ?? 0}/C${hudStats.errors?.c ?? 0}`;
  };
  ws.onclose = (ev) => {
    if (ev.code === 4404) { localStorage.removeItem("session"); location.reload(); return; }
    setTimeout(() => connect(sid), 1000);
  };
}

const send = (m) => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify(m));
$("undo").onclick = () => { strokes.pop(); redraw(); };
window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); $("undo").click(); }
  else if (e.key === "0") resetZoom();   // 원래 크기로
});
$("clear").onclick = () => { strokes.length = 0; live.clear(); redraw(); send({ type: "reset" }); };
$("save").onclick = () => {
  const a = document.createElement("a");
  a.download = `drawing-${Date.now()}.png`;
  const saved = { ...view };
  Object.assign(view, { s: 1, ox: 0, oy: 0 }); redraw();   // 확대 상태와 상관없이 그림 전체를 저장
  const tmp = document.createElement("canvas"); tmp.width = board.width; tmp.height = board.height;
  const t = tmp.getContext("2d"); t.fillStyle = "#fff"; t.fillRect(0, 0, tmp.width, tmp.height); t.drawImage(board, 0, 0);
  Object.assign(view, saved); redraw();
  a.href = tmp.toDataURL("image/png"); a.click();
};
$("mirror").onchange = (e) => send({ type: "config", mirror: e.target.checked });
$("showQr").onclick = () => $("pair").classList.toggle("hidden");   // 다른 폰으로 다시 연결할 때

(async () => {
  resize();
  $("curColor").style.background = currentColor;
  const s = await getSession();
  showSession(s);
  connect(s.session);
  requestAnimationFrame(drawOverlay);
})();
