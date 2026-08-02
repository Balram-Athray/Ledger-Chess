/* board.js -- renders the board from server state, handles click-to-move,
   and polls the server so the opponent's moves appear without a refresh. */

const PIECE_GLYPH = {
  wK: "\u2654", wQ: "\u2655", wR: "\u2656", wB: "\u2657", wN: "\u2658", wP: "\u2659",
  bK: "\u265A", bQ: "\u265B", bR: "\u265C", bB: "\u265D", bN: "\u265E", bP: "\u265F",
};

const boardEl = document.getElementById("board");
const statusBanner = document.getElementById("status-banner");
const moveListEl = document.getElementById("move-list");
const promoPicker = document.getElementById("promo-picker");
const resignBtn = document.getElementById("resign-btn");
const gameOverActions = document.getElementById("game-over-actions");
const clockWhiteEl = document.getElementById("clock-white");
const clockBlackEl = document.getElementById("clock-black");

let currentState = null;
let selected = null;          // square name e.g. "e2"
let pendingPromotion = null;  // {from, to}
let flip = (window.CURRENT_USER_ID === window.BLACK_ID) && !window.IS_LOCAL;
let pollTimer = null;
let clockTicker = null;

const FILES = "abcdefgh";
function sqName(row, col) { return FILES[col] + (row + 1); }

function displayOrder() {
  // returns [ [row, col], ... ] in the order squares should be painted (top-left to bottom-right)
  const rows = flip ? [0, 1, 2, 3, 4, 5, 6, 7] : [7, 6, 5, 4, 3, 2, 1, 0];
  const cols = flip ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7];
  const order = [];
  for (const r of rows) for (const c of cols) order.push([r, c]);
  return order;
}

function parseUTC(isoString) {
  if (!isoString) return null;
  // The server writes naive UTC timestamps (no trailing 'Z'/offset) --
  // without a marker, JS Date parses them as *local* time, which would
  // throw the clock off by however many hours your timezone is from UTC.
  const marked = /[Zz]|[+-]\d\d:\d\d$/.test(isoString) ? isoString : isoString + "Z";
  return new Date(marked);
}

function formatClock(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function renderClocks() {
  if (!currentState || (!clockWhiteEl && !clockBlackEl)) return;
  const tc = currentState.time_control_seconds;

  if (!tc) {
    for (const el of [clockWhiteEl, clockBlackEl]) {
      if (!el) continue;
      el.textContent = "\u221E";
      el.classList.remove("clock-running", "clock-low");
    }
    return;
  }

  let whiteLeft = currentState.white_time_left;
  let blackLeft = currentState.black_time_left;
  const turn = currentState.turn;
  const ongoing = currentState.status === "ongoing";

  if (ongoing && currentState.turn_started_at) {
    const started = parseUTC(currentState.turn_started_at).getTime();
    const elapsed = Math.max(0, (Date.now() - started) / 1000);
    if (turn === "w") whiteLeft = Math.max(0, whiteLeft - elapsed);
    else blackLeft = Math.max(0, blackLeft - elapsed);
  } else if (!ongoing && currentState.result_reason === "timeout") {
    // whoever's turn it was when the game ended is the side that flagged
    if (turn === "w") whiteLeft = 0; else blackLeft = 0;
  }

  if (clockWhiteEl) {
    clockWhiteEl.textContent = formatClock(whiteLeft);
    clockWhiteEl.classList.toggle("clock-running", ongoing && turn === "w");
    clockWhiteEl.classList.toggle("clock-low", whiteLeft <= 30);
  }
  if (clockBlackEl) {
    clockBlackEl.textContent = formatClock(blackLeft);
    clockBlackEl.classList.toggle("clock-running", ongoing && turn === "b");
    clockBlackEl.classList.toggle("clock-low", blackLeft <= 30);
  }
}

async function fetchState() {
  const res = await fetch(`/api/game/${window.GAME_ID}/state`);
  if (!res.ok) return;
  currentState = await res.json();
  render();
}

function isMyTurn() {
  if (!currentState) return false;
  if (window.IS_LOCAL) return currentState.status === "ongoing";
  const myId = window.CURRENT_USER_ID;
  const turnPlayer = currentState.turn === "w" ? currentState.white_id : currentState.black_id;
  return currentState.status === "ongoing" && myId === turnPlayer;
}

function render() {
  if (!currentState) return;
  boardEl.innerHTML = "";
  const legal = currentState.legal_moves || {};
  const targets = selected && legal[selected] ? legal[selected] : [];
  const targetSquares = targets.map(t => t.slice(0, 2));

  let checkSquare = null;
  if (currentState.in_check) {
    checkSquare = findKing(currentState.board, currentState.turn);
  }

  for (const [r, c] of displayOrder()) {
    const name = sqName(r, c);
    const piece = currentState.board[r][c];
    const div = document.createElement("div");
    const isLight = (r + c) % 2 === 1;
    div.className = "sq " + (isLight ? "light" : "dark");
    if (piece) div.classList.add("has-piece");
    if (name === selected) div.classList.add("selected");
    if (targetSquares.includes(name)) div.classList.add("move-target");
    if (checkSquare && name === checkSquare) div.classList.add("in-check");

    if (piece) {
      const span = document.createElement("span");
      span.className = piece[0] === "w" ? "piece-w" : "piece-b";
      span.textContent = PIECE_GLYPH[piece];
      div.appendChild(span);
    }
    const coord = document.createElement("span");
    coord.className = "coord";
    if (c === (flip ? 7 : 0)) coord.textContent = r + 1;
    div.appendChild(coord);

    div.addEventListener("click", () => onSquareClick(name));
    boardEl.appendChild(div);
  }

  renderStatus();
  renderMoveList();
  renderClocks();
}

function findKing(board, color) {
  for (let r = 0; r < 8; r++)
    for (let c = 0; c < 8; c++)
      if (board[r][c] === color + "K") return sqName(r, c);
  return null;
}

function renderStatus() {
  let text = "";
  const s = currentState.status;        // 'ongoing' | 'white_won' | 'black_won' | 'draw'
  const reason = currentState.result_reason;  // 'checkmate' | 'resignation' | 'stalemate' | 'draw_50move' | 'draw_insufficient' | null
  const gameOver = s !== "ongoing";

  if (s === "white_won") {
    text = reason === "resignation" ? "Black resigned &mdash; White wins." : "Checkmate &mdash; White wins.";
  } else if (s === "black_won") {
    text = reason === "resignation" ? "White resigned &mdash; Black wins." : "Checkmate &mdash; Black wins.";
  } else if (s === "draw") {
    if (reason === "stalemate") text = "Draw by stalemate.";
    else if (reason === "draw_50move") text = "Draw by the 50-move rule.";
    else if (reason === "draw_insufficient") text = "Draw &mdash; insufficient material.";
    else text = "Game drawn.";
  } else {
    const turnName = currentState.turn === "w" ? "White" : "Black";
    text = (currentState.in_check ? `${turnName} is in check. ` : "") + `${turnName} to move.`;
    if (window.IS_LOCAL) text += " (pass-and-play)";
    else if (!isMyTurn()) text += window.IS_BOT ? " Engine is thinking..." : " Waiting for opponent...";
  }
  statusBanner.innerHTML = text;
  statusBanner.style.display = "block";
  statusBanner.classList.toggle("status-banner-over", gameOver);

  if (resignBtn) resignBtn.style.display = gameOver ? "none" : "inline-block";
  if (gameOverActions) gameOverActions.style.display = gameOver ? "flex" : "none";

  if (gameOver && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (gameOver && clockTicker) {
    clearInterval(clockTicker);
    clockTicker = null;
  }
}

function renderMoveList() {
  moveListEl.innerHTML = "";
  const hist = currentState.history || [];
  for (let i = 0; i < hist.length; i += 2) {
    const num = document.createElement("div");
    num.className = "num";
    num.textContent = (i / 2 + 1) + ".";
    const w = document.createElement("div");
    w.textContent = hist[i] || "";
    const b = document.createElement("div");
    b.textContent = hist[i + 1] || "";
    moveListEl.appendChild(num);
    moveListEl.appendChild(w);
    moveListEl.appendChild(b);
  }
  moveListEl.scrollTop = moveListEl.scrollHeight;
}

function onSquareClick(name) {
  if (!currentState || currentState.status !== "ongoing") return;
  if (!isMyTurn()) return;

  const legal = currentState.legal_moves || {};
  const piece = pieceAt(name);

  if (selected) {
    const targets = legal[selected] || [];
    const match = targets.find(t => t.slice(0, 2) === name);
    if (match) {
      if (match.length > 2) {
        // promotion needed
        pendingPromotion = { from: selected, to: name };
        promoPicker.style.display = "flex";
        selected = null;
        render();
        return;
      }
      sendMove(selected, name, null);
      selected = null;
      return;
    }
  }

  if (piece && legal[name]) {
    selected = name;
  } else {
    selected = null;
  }
  render();
}

function pieceAt(name) {
  const col = FILES.indexOf(name[0]);
  const row = parseInt(name[1], 10) - 1;
  return currentState.board[row][col];
}

promoPicker.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-p]");
  if (!btn || !pendingPromotion) return;
  sendMove(pendingPromotion.from, pendingPromotion.to, btn.dataset.p);
  pendingPromotion = null;
  promoPicker.style.display = "none";
});

async function sendMove(from, to, promotion) {
  const res = await fetch(`/api/game/${window.GAME_ID}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from, to, promotion }),
  });
  if (res.ok) {
    await fetchState();
  } else {
    const err = await res.json();
    console.warn("move rejected:", err.error);
    await fetchState();
  }
}

if (resignBtn) {
  resignBtn.addEventListener("click", async () => {
    if (!confirm("Resign this game?")) return;
    await fetch(`/api/game/${window.GAME_ID}/resign`, { method: "POST" });
    await fetchState();
  });
}

fetchState();
pollTimer = setInterval(fetchState, 1500);
clockTicker = setInterval(renderClocks, 250);
