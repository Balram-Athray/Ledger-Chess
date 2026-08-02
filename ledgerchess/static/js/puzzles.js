/* puzzles.js -- single-move puzzle trainer. No polling (it's single-player,
   synchronous); reuses the same board rendering approach as board.js but
   simplified since there's no opponent and no multi-move games here. */

const PIECE_GLYPH = {
  wK: "\u2654", wQ: "\u2655", wR: "\u2656", wB: "\u2657", wN: "\u2658", wP: "\u2659",
  bK: "\u265A", bQ: "\u265B", bR: "\u265C", bB: "\u265D", bN: "\u265E", bP: "\u265F",
};
const FILES = "abcdefgh";
function sqName(row, col) { return FILES[col] + (row + 1); }

const boardEl = document.getElementById("board");
const statusEl = document.getElementById("puzzle-status");
const promoPicker = document.getElementById("promo-picker");
const nextBtn = document.getElementById("next-btn");
const solvedCountEl = document.getElementById("solved-count");
const attemptedCountEl = document.getElementById("attempted-count");
const diffButtons = document.querySelectorAll(".diff-btn");

let currentPuzzle = null;
let selected = null;
let pendingPromotion = null;
let locked = false;       // true once the current puzzle has been answered
let loading = false;
let difficulty = "easy";
let solved = 0, attempted = 0;

function setDifficulty(d) {
  difficulty = d;
  diffButtons.forEach(b => b.classList.toggle("diff-active", b.dataset.diff === d));
}

function flipFor(turn) {
  return turn === "b";  // orient the board toward whoever has to move, like most puzzle trainers
}

function displayOrder(flip) {
  const rows = flip ? [0, 1, 2, 3, 4, 5, 6, 7] : [7, 6, 5, 4, 3, 2, 1, 0];
  const cols = flip ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7];
  const order = [];
  for (const r of rows) for (const c of cols) order.push([r, c]);
  return order;
}

function pieceAt(name) {
  const col = FILES.indexOf(name[0]);
  const row = parseInt(name[1], 10) - 1;
  return currentPuzzle.board[row][col];
}

function render() {
  if (!currentPuzzle) return;
  boardEl.innerHTML = "";
  const flip = flipFor(currentPuzzle.turn);
  const legal = currentPuzzle.legal_moves || {};
  const targets = selected && legal[selected] ? legal[selected] : [];
  const targetSquares = targets.map(t => t.slice(0, 2));

  let checkSquare = null;
  if (currentPuzzle.in_check) {
    for (let r = 0; r < 8; r++)
      for (let c = 0; c < 8; c++)
        if (currentPuzzle.board[r][c] === currentPuzzle.turn + "K") checkSquare = sqName(r, c);
  }

  for (const [r, c] of displayOrder(flip)) {
    const name = sqName(r, c);
    const piece = currentPuzzle.board[r][c];
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
    div.addEventListener("click", () => onSquareClick(name));
    boardEl.appendChild(div);
  }
}

function onSquareClick(name) {
  if (!currentPuzzle || locked || loading) return;
  const legal = currentPuzzle.legal_moves || {};
  const piece = pieceAt(name);

  if (selected) {
    const targets = legal[selected] || [];
    const match = targets.find(t => t.slice(0, 2) === name);
    if (match) {
      if (match.length > 2) {
        pendingPromotion = { from: selected, to: name };
        promoPicker.style.display = "flex";
        selected = null;
        render();
        return;
      }
      submitAttempt(selected, name, null);
      selected = null;
      return;
    }
  }
  selected = (piece && legal[name]) ? name : null;
  render();
}

promoPicker.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-p]");
  if (!btn || !pendingPromotion) return;
  submitAttempt(pendingPromotion.from, pendingPromotion.to, btn.dataset.p);
  pendingPromotion = null;
  promoPicker.style.display = "none";
});

async function submitAttempt(from, to, promotion) {
  locked = true;
  const res = await fetch(`/api/puzzle/${currentPuzzle.puzzle_id}/attempt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from, to, promotion }),
  });
  const data = await res.json();
  if (data.error) {
    locked = false;
    statusEl.textContent = "That move isn't legal there -- try again.";
    return;
  }

  attempted += 1;
  attemptedCountEl.textContent = attempted;
  currentPuzzle.board = data.resulting_board;

  if (data.correct) {
    solved += 1;
    solvedCountEl.textContent = solved;
    statusEl.innerHTML = "&#9989; Correct! Nicely spotted.";
    statusEl.classList.add("status-banner-over");
  } else {
    const solutionSquares = data.solution[0] ? `${data.solution[0].slice(0,2)} \u2192 ${data.solution[0].slice(2,4)}` : "";
    statusEl.innerHTML = `&#10060; Not quite. The move was <strong>${solutionSquares}</strong>.`;
    statusEl.classList.remove("status-banner-over");
  }
  currentPuzzle.legal_moves = {};
  render();
}

async function loadPuzzle() {
  loading = true;
  locked = false;
  selected = null;
  statusEl.classList.remove("status-banner-over");
  statusEl.textContent = difficulty === "easy"
    ? "Loading a puzzle..."
    : "Generating a puzzle -- this can take a few seconds for medium/hard...";
  nextBtn.disabled = true;
  diffButtons.forEach(b => b.disabled = true);

  try {
    const res = await fetch(`/api/puzzle/new?difficulty=${difficulty}`);
    currentPuzzle = await res.json();
    render();
    statusEl.textContent = currentPuzzle.turn === "w" ? "White to move." : "Black to move.";
  } catch (err) {
    statusEl.textContent = "Couldn't generate a puzzle -- try again.";
  } finally {
    loading = false;
    nextBtn.disabled = false;
    diffButtons.forEach(b => b.disabled = false);
  }
}

nextBtn.addEventListener("click", loadPuzzle);
diffButtons.forEach(b => b.addEventListener("click", () => { setDifficulty(b.dataset.diff); loadPuzzle(); }));

setDifficulty("easy");
loadPuzzle();
