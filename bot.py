"""
bot.py
------
A "Play vs Computer" opponent: minimax search with alpha-beta pruning and
iterative deepening, tuned across 8 difficulty levels.

How the difficulty actually changes with level (not just a label):
  - `time_budget`: how long (seconds) the search is allowed to think. Lower
    levels barely think at all; higher levels get a real search budget.
  - `random_chance`: probability the bot ignores its search entirely and
    plays a uniformly random legal move -- this is what makes level 1 blunder
    pieces for no reason, the way a true beginner does.
  - `eval_noise`: random jitter added to the evaluation at each leaf node.
    Low levels "misjudge" positions (noisy eval); level 8 sees clearly.

The search itself (evaluate/_negamax/_order_moves) is shared with
puzzle.py, which reuses it to detect when a generated position has a single
clearly-best "tactical" move worth turning into a puzzle.
"""

import random
import time
from contextlib import contextmanager

from chess_engine import sq_name

EVAL_VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}

# Tiny piece-square tables (White's perspective; row 0 = rank 1) -- just
# enough to make the bot prefer sensible central play over random shuffling.
PAWN_PST = [
    [0, 0, 0, 0, 0, 0, 0, 0],
    [5, 10, 10, -10, -10, 10, 10, 5],
    [5, -5, -10, 0, 0, -10, -5, 5],
    [0, 0, 0, 20, 20, 0, 0, 0],
    [5, 5, 10, 25, 25, 10, 5, 5],
    [10, 10, 20, 30, 30, 20, 10, 10],
    [50, 50, 50, 50, 50, 50, 50, 50],
    [0, 0, 0, 0, 0, 0, 0, 0],
]
KNIGHT_PST = [
    [-50, -40, -30, -30, -30, -30, -40, -50],
    [-40, -20, 0, 5, 5, 0, -20, -40],
    [-30, 5, 10, 15, 15, 10, 5, -30],
    [-30, 0, 15, 20, 20, 15, 0, -30],
    [-30, 5, 15, 20, 20, 15, 5, -30],
    [-30, 0, 10, 15, 15, 10, 0, -30],
    [-40, -20, 0, 0, 0, 0, -20, -40],
    [-50, -40, -30, -30, -30, -30, -40, -50],
]
CENTER_BONUS = [
    [0, 0, 0, 0, 0, 0, 0, 0],
    [0, 5, 5, 5, 5, 5, 5, 0],
    [0, 5, 10, 10, 10, 10, 5, 0],
    [0, 5, 10, 15, 15, 10, 5, 0],
    [0, 5, 10, 15, 15, 10, 5, 0],
    [0, 5, 10, 10, 10, 10, 5, 0],
    [0, 5, 5, 5, 5, 5, 5, 0],
    [0, 0, 0, 0, 0, 0, 0, 0],
]

# level -> (thinking time budget, chance of a random/blundering move, eval noise)
LEVELS = {
    1: dict(time_budget=0.05, random_chance=0.75, eval_noise=90),
    2: dict(time_budget=0.05, random_chance=0.45, eval_noise=60),
    3: dict(time_budget=0.20, random_chance=0.25, eval_noise=40),
    4: dict(time_budget=0.40, random_chance=0.12, eval_noise=25),
    5: dict(time_budget=0.80, random_chance=0.05, eval_noise=15),
    6: dict(time_budget=1.20, random_chance=0.00, eval_noise=8),
    7: dict(time_budget=1.80, random_chance=0.00, eval_noise=2),
    8: dict(time_budget=2.50, random_chance=0.00, eval_noise=0),
}

LEVEL_NAMES = {
    1: "Level 1 \u2014 Beginner", 2: "Level 2 \u2014 Novice",
    3: "Level 3 \u2014 Casual", 4: "Level 4 \u2014 Club player",
    5: "Level 5 \u2014 Solid", 6: "Level 6 \u2014 Strong",
    7: "Level 7 \u2014 Expert", 8: "Level 8 \u2014 Ruthless",
}


class _TimeUp(Exception):
    pass


@contextmanager
def try_move(board, move):
    """Temporarily apply a move for search purposes, guaranteed to be undone
    (even if an exception -- e.g. a search timeout -- happens mid-branch).

    Note: board._apply() (the low-level primitive, used here instead of
    make_move() for search speed) moves pieces but does NOT flip board.turn --
    that's normally make_move()'s job. game_status()/is_in_check() rely on
    board.turn, so it has to be flipped by hand here or checkmate detection
    during search silently checks the wrong side."""
    snapshot = board._snapshot()
    board._apply(move)
    board.turn = "b" if board.turn == "w" else "w"
    try:
        yield
    finally:
        board._restore(snapshot)


def flat_legal_moves(board, color):
    moves = []
    for square_moves in board.all_legal_moves(color).values():
        moves.extend(square_moves)
    return moves


def evaluate(board, noise=0):
    """Material + light positional score, from White's perspective."""
    score = 0
    for r in range(8):
        for c in range(8):
            piece = board.board[r][c]
            if not piece:
                continue
            color, kind = piece[0], piece[1]
            value = EVAL_VALUES[kind]
            if kind == "P":
                pst = PAWN_PST[r][c] if color == "w" else PAWN_PST[7 - r][c]
            elif kind == "N":
                pst = KNIGHT_PST[r][c] if color == "w" else KNIGHT_PST[7 - r][c]
            else:
                pst = CENTER_BONUS[r][c] if color == "w" else CENTER_BONUS[7 - r][c]
            total = value + pst
            score += total if color == "w" else -total
    if noise:
        score += random.uniform(-noise, noise)
    return score


def order_moves(moves):
    """Try captures (biggest gain first) and promotions before quiet moves,
    so alpha-beta gets to prune far more of the tree."""
    def key(m):
        cap_value = EVAL_VALUES.get(m.captured[1], 0) if m.captured else 0
        promo_bonus = 800 if m.promotion else 0
        return -(cap_value * 10 + promo_bonus)
    return sorted(moves, key=key)


def negamax(board, depth, alpha, beta, color, deadline, noise):
    if time.time() > deadline:
        raise _TimeUp()

    status = board.game_status()
    if status == "checkmate":
        return -100000 - depth  # prefer the fastest mate, avoid the slowest loss
    if status in ("stalemate", "draw_50move", "draw_insufficient"):
        return 0

    if depth == 0:
        sign = 1 if color == "w" else -1
        return sign * evaluate(board, noise)

    best = -float("inf")
    moves = order_moves(flat_legal_moves(board, color))
    if not moves:
        return 0

    opponent = "b" if color == "w" else "w"
    for move in moves:
        with try_move(board, move):
            score = -negamax(board, depth - 1, -beta, -alpha, opponent, deadline, noise)
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def choose_move(board, color, level):
    """Pick a move for `color` at the given difficulty (1-8). Returns a Move
    object from chess_engine, or None if there are no legal moves."""
    config = LEVELS.get(level, LEVELS[4])
    legal = flat_legal_moves(board, color)
    if not legal:
        return None

    if random.random() < config["random_chance"]:
        return random.choice(legal)

    deadline = time.time() + config["time_budget"]
    ordered = order_moves(legal)
    best_move = random.choice(legal)  # safe fallback if depth 1 doesn't even finish
    depth = 1
    opponent = "b" if color == "w" else "w"
    try:
        while depth <= 6:  # ceiling -- pure-Python search speed makes deeper unrealistic anyway
            alpha, beta = -float("inf"), float("inf")
            current_best, current_best_score = None, -float("inf")
            for move in ordered:
                with try_move(board, move):
                    score = -negamax(board, depth - 1, -beta, -alpha, opponent,
                                      deadline, config["eval_noise"])
                if score > current_best_score:
                    current_best_score, current_best = score, move
                if current_best_score > alpha:
                    alpha = current_best_score
            best_move = current_best or best_move
            depth += 1
    except _TimeUp:
        pass

    return best_move


def move_to_uci(move):
    s = sq_name(*move.frm) + sq_name(*move.to)
    if move.promotion:
        s += move.promotion.lower()
    return s
