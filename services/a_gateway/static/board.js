// 그림판: A 의 frame_result.commands 를 실행한다. 계약: docs/03-messages.md §4·§5
const $ = (id) => document.getElementById(id);
const board = $("board"), overlay = $("overlay");
const bctx = board.getContext("2d"), octx = overlay.getContext("2d");

// ── 획 저장소 (undo·리사이즈 시 다시 그리기 위해 정규화 좌표로 보관) ──
const strokes = [];          // 완료된 획: {tool, color, width, pts:[[x,y],...]}
const live = new Map();      // 진행 중 획: id → stroke
let currentColor = "#111111";
let lastCursor = null, lastLandmarks = null;

function scale() { return Math.min(board.width, board.height) / 1000; }
function px(x, y) { return [x * board.width, y * board.height]; }

function drawSegment(s, i) {
  const [x0, y0] = px(...s.pts[Math.max(0, i - 1)]), [x1, y1] = px(...s.pts[i]);
  bctx.save();
  bctx.globalCompositeOperation = s.tool === "eraser" ? "destination-out" : "source-over";
  bctx.strokeStyle = s.color;
  bctx.lineWidth = s.width * scale() * (s.tool === "eraser" ? 5 : 1);
  bctx.lineCap = bctx.lineJoin = "round";
  bctx.beginPath(); bctx.moveTo(x0, y0); bctx.lineTo(x1, y1); bctx.stroke();
  bctx.restore();
}

function redraw() {
  bctx.clearRect(0, 0, board.width, board.height);
  for (const s of [...strokes, ...live.values()]) s.pts.forEach((_, i) => drawSegment(s, i));
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
      const s = { tool: cmd.tool, color: cmd.color, width: cmd.width, pts: [[cmd.x, cmd.y]] };
      live.set(cmd.id, s); drawSegment(s, 0); break;
    }
    case "stroke_point": {
      const s = live.get(cmd.id); if (!s) break;   // 모르는 id 는 무시 (계약 §5)
      s.pts.push([cmd.x, cmd.y]); drawSegment(s, s.pts.length - 1); break;
    }
    case "stroke_end": {
      const s = live.get(cmd.id); if (!s) break;
      live.delete(cmd.id); strokes.push(s); break;
    }
    case "set_color": currentColor = cmd.color; $("curColor").style.background = cmd.color; break;
    case "clear": strokes.length = 0; live.clear(); redraw(); break;
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
    const r = lastCursor.mode === "erase" ? 30 * scale() : 8 * scale() + 4;
    octx.beginPath(); octx.arc(x, y, r, 0, Math.PI * 2);
    octx.fillStyle = { draw: currentColor, hover: "rgba(0,0,0,.15)", erase: "rgba(209,73,91,.15)", idle: "rgba(0,0,0,.08)" }[lastCursor.mode];
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
    } else if (m.type === "frame_result") {
      m.commands.forEach(run);
      lastCursor = m.cursor; lastLandmarks = m.landmarks;
      hudFrame = { gesture: m.gesture, ...m.timing };
    } else if (m.type === "stats") hudStats = m;
    $("hud").textContent =
      `gesture ${hudFrame.gesture ?? "-"}  B ${hudFrame.b_ms ?? "-"}ms  C ${hudFrame.c_ms ?? "-"}ms\n` +
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
$("clear").onclick = () => { strokes.length = 0; live.clear(); redraw(); send({ type: "reset" }); };
$("save").onclick = () => {
  const a = document.createElement("a");
  a.download = `drawing-${Date.now()}.png`;
  const tmp = document.createElement("canvas"); tmp.width = board.width; tmp.height = board.height;
  const t = tmp.getContext("2d"); t.fillStyle = "#fff"; t.fillRect(0, 0, tmp.width, tmp.height); t.drawImage(board, 0, 0);
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
