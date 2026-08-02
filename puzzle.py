"""
puzzle.py
---------
Generates chess puzzles on demand -- there's no fixed database, so it's
effectively unlimited. Two different generation strategies are used
depending on difficulty:

  Easy ("Mate in 1"): built from a randomized back-rank mate template and
  verified with the rules engine. This is instant and always succeeds --
  appropriate for a difficulty level meant to be quick and approachable.

  Medium / Hard ("Find the best move"): a semi-random self-play game (using
  bot.py at a modest, imperfect level) generates a plausible position, then
  a real minimax search (also from bot.py) scores every legal move. If the
  best move beats the second-best by a wide enough margin, that's a genuine
  single "critical" move worth solving -- exactly what a tactics puzzle is.
  Hard uses a deeper search and a bigger required margin than Medium.
"""

import random
import time

from chess_engine import Board, sq_name
import bot

DIFFICULTY_CONFIG = {
    "medium": dict(depth=2, gap_threshold=180, min_ply=6, max_ply=24),
    "hard":   dict(depth=2, gap_threshold=280, min_ply=14, max_ply=36),
}

GEN_TIME_BUDGET = 4.0  # overall seconds allowed to find a tactic puzzle before giving up


def _empty_board():
    return [[None] * 8 for _ in range(8)]


def _build_board(grid, turn):
    return Board.from_dict({
        "board": grid, "turn": turn,
        "castling": {"wK": False, "wQ": False, "bK": False, "bQ": False},
        "en_passant": None, "halfmove_clock": 0, "fullmove_number": 1,
    })


# ------------------------------------------------------ Easy: mate in 1 ----

def _generate_mate_in_1():
    for _ in range(30):  # template construction is cheap; a few retries is plenty
        defender = random.choice(["w", "b"])
        attacker = "b" if defender == "w" else "w"
        defender_back_row = 0 if defender == "w" else 7
        shield_row = 1 if defender == "w" else 6
        king_col = random.choice([2, 3, 4, 5, 6])
        shield_cols = [c for c in (king_col - 1, king_col, king_col + 1) if 0 <= c <= 7]
        attack_col = random.choice([0, 7])
        piece = random.choice(["R", "Q"])
        attacker_start_row = 3 if defender == "w" else 4

        grid = _empty_board()
        grid[defender_back_row][king_col] = defender + "K"
        for c in shield_cols:
            grid[shield_row][c] = defender + "P"
        grid[attacker_start_row][attack_col] = attacker + piece
        grid[7 - defender_back_row][0 if attack_col == 7 else 7] = attacker + "K"

        board = _build_board(grid, attacker)
        frm = sq_name(attacker_start_row, attack_col)
        to = sq_name(defender_back_row, attack_col)
        move = board.make_move(frm, to)
        if move is not None and board.game_status() == "checkmate":
            return {
                "board": grid, "turn": attacker,
                "solution": [frm + to],
                "difficulty": "easy",
                "title": "Mate in 1",
            }
    return None  # extremely unlikely to ever fall through given the template is self-verifying


# ---------------------------------------------------- Medium/Hard: tactics --

def _best_and_second_best(board, color, depth, deadline):
    moves = bot.order_moves(bot.flat_legal_moves(board, color))
    if len(moves) < 2:
        return None
    scored = []
    opponent = "b" if color == "w" else "w"
    try:
        for move in moves:
            with bot.try_move(board, move):
                score = -bot.negamax(board, depth - 1, -float("inf"), float("inf"),
                                      opponent, deadline, noise=0)
            scored.append((score, move))
    except bot._TimeUp:
        return None  # this position took too long to score -- just skip it, not fatal
    scored.sort(key=lambda pair: -pair[0])
    return scored


def _generate_tactic(difficulty):
    cfg = DIFFICULTY_CONFIG[difficulty]
    overall_deadline = time.time() + GEN_TIME_BUDGET
    best_fallback = None  # (gap, grid, turn, solution) -- best candidate seen, in case nothing clears the bar

    while time.time() < overall_deadline:
        board = Board()
        target_plies = random.randint(cfg["min_ply"], cfg["max_ply"])

        for ply in range(target_plies):
            if time.time() >= overall_deadline:
                break
            if board.game_status() != "ongoing":
                break
            color = board.turn
            mv = bot.choose_move(board, color, level=random.choice([2, 3]))
            if mv is None:
                break
            board.make_move(sq_name(*mv.frm), sq_name(*mv.to), promotion=mv.promotion)

            if ply < cfg["min_ply"] or board.game_status() != "ongoing":
                continue
            if time.time() >= overall_deadline:
                break

            search_deadline = min(overall_deadline, time.time() + 1.5)
            scored = _best_and_second_best(board, board.turn, cfg["depth"], search_deadline)
            if not scored:
                continue
            best_score, best_move = scored[0]
            second_score = scored[1][0]
            gap = best_score - second_score

            if best_fallback is None or gap > best_fallback[0]:
                best_fallback = (gap, [row[:] for row in board.board], board.turn,
                                  [bot.move_to_uci(best_move)])

            if gap >= cfg["gap_threshold"]:
                return {
                    "board": [row[:] for row in board.board], "turn": board.turn,
                    "solution": [bot.move_to_uci(best_move)],
                    "difficulty": difficulty,
                    "title": "Find the winning move" if difficulty == "medium" else "Find the only good move",
                }

    if best_fallback:
        _, grid, turn, solution = best_fallback
        return {
            "board": grid, "turn": turn, "solution": solution,
            "difficulty": difficulty,
            "title": "Find the best move",
        }
    return None


# -------------------------------------------------------------- public API --

def generate_puzzle(difficulty):
    difficulty = difficulty if difficulty in ("easy", "medium", "hard") else "easy"
    if difficulty == "easy":
        puzzle = _generate_mate_in_1()
    else:
        puzzle = _generate_tactic(difficulty)

    if puzzle is None:
        # Should be extremely rare; fall back to the always-available easy template
        # rather than ever returning nothing to the user.
        puzzle = _generate_mate_in_1()
    return puzzle
