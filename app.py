import os
import functools
import json
from datetime import datetime, timezone

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash

from copy import deepcopy

import db
from chess_engine import Board, sq_name
import elo
import tournament as tourney
import bot
import puzzle

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-this-in-production")

db.init_db()

# key -> (initial seconds, increment seconds). "untimed" (0, 0) means no clock at all.
TIME_CONTROLS = {
    "untimed":   (0, 0),
    "bullet1":   (60, 0),
    "blitz3":    (180, 0),
    "blitz5":    (300, 0),
    "rapid10":   (600, 0),
    "rapid15+10": (900, 10),
}


def parse_time_control(form):
    key = form.get("time_control", "untimed")
    return TIME_CONTROLS.get(key, (0, 0))


def utcnow():
    return datetime.now(timezone.utc)


def parse_iso(s):
    # SQLite stores our own now() as naive UTC ISO strings (no offset) -- treat as UTC.
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------- helpers ----

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    if "user_id" not in session:
        return None
    return db.get_user_by_id(session["user_id"])


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


def apply_game_result(game_row, status, reason):
    """status: 'white_won' / 'black_won' / 'draw'. Updates ELO, user stats,
    and (if this game belongs to a tournament match) the tournament standings."""
    db.finish_game(game_row["id"], status, reason)

    if game_row["white_id"] == game_row["black_id"] or game_row["is_bot"]:
        # local pass-and-play or a "vs computer" game -- no ELO stakes
        return

    white = db.get_user_by_id(game_row["white_id"])
    black = db.get_user_by_id(game_row["black_id"])

    if status == "white_won":
        score_white = 1.0
    elif status == "black_won":
        score_white = 0.0
    else:
        score_white = 0.5

    new_white, new_black = elo.update_ratings(white["elo"], black["elo"], score_white)

    w_result = "win" if score_white == 1.0 else ("loss" if score_white == 0.0 else "draw")
    b_result = "loss" if score_white == 1.0 else ("win" if score_white == 0.0 else "draw")
    db.update_user_rating(white["id"], new_white, w_result)
    db.update_user_rating(black["id"], new_black, b_result)

    if game_row["tournament_match_id"]:
        match = db.get_tournament_match(game_row["tournament_match_id"])
        tid = match["tournament_id"]
        if status == "white_won":
            result_label, w_pts, b_pts = "white", 1.0, 0.0
        elif status == "black_won":
            result_label, w_pts, b_pts = "black", 0.0, 1.0
        else:
            result_label, w_pts, b_pts = "draw", 0.5, 0.5
        db.set_match_result(match["id"], result_label, game_id=game_row["id"])
        db.bump_player_score(tid, match["white_id"], w_pts)
        if match["black_id"]:
            db.bump_player_score(tid, match["black_id"], b_pts)

        t = db.get_tournament(tid)
        if t["format"] == "swiss" and tourney.round_is_complete(tid, t["current_round"]):
            tourney.advance_swiss_round(tid)


def check_and_apply_timeout(game_row):
    """If this is a timed game and the side to move has run out of time,
    end the game as a timeout loss for them and return True. Otherwise False.
    Safe to call liberally -- it's a no-op for untimed or already-finished games."""
    if game_row["status"] != "ongoing":
        return False
    if not game_row["time_control_seconds"]:
        return False
    if not game_row["turn_started_at"]:
        return False

    state = json.loads(game_row["state_json"])
    turn = state["turn"]
    elapsed = (utcnow() - parse_iso(game_row["turn_started_at"])).total_seconds()
    banked = game_row["white_time_left"] if turn == "w" else game_row["black_time_left"]

    if banked - elapsed <= 0:
        winner_status = "black_won" if turn == "w" else "white_won"
        apply_game_result(game_row, winner_status, "timeout")
        return True
    return False


def settle_clock_after_move(game_row, mover_color):
    """Called right after a move is successfully made in a timed game: charges
    the elapsed thinking time (plus increment) to the mover, and starts the
    opponent's clock running from now."""
    if not game_row["time_control_seconds"]:
        return
    elapsed = (utcnow() - parse_iso(game_row["turn_started_at"])).total_seconds()
    increment = game_row["increment_seconds"] or 0
    white_left, black_left = game_row["white_time_left"], game_row["black_time_left"]
    if mover_color == "w":
        white_left = max(0, white_left - elapsed) + increment
    else:
        black_left = max(0, black_left - elapsed) + increment
    db.update_game_clock(game_row["id"], white_left, black_left, db.now())


# ------------------------------------------------------------------ auth ----

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if not username or not password:
            flash("Username and password are required.")
            return render_template("register.html")
        if db.get_user_by_username(username):
            flash("That username is already taken.")
            return render_template("register.html")
        user_id = db.create_user(username, generate_password_hash(password))
        session["user_id"] = user_id
        return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = db.get_user_by_username(username)
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.")
            return render_template("login.html")
        session["user_id"] = user["id"]
        return redirect(request.args.get("next") or url_for("index"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ------------------------------------------------------------------ pages ----

@app.route("/")
def index():
    top = db.leaderboard(5)
    tournaments = db.list_tournaments()[:5]
    active = active_open = []
    if current_user():
        active = db.active_games_for_user(current_user()["id"])
    open_games = db.open_challenges()
    return render_template("index.html", top=top, tournaments=tournaments,
                            active=active, open_games=open_games)


@app.route("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html", players=db.leaderboard(200))


@app.route("/local")
def local_play():
    """Pass-and-play on one screen -- no ELO stakes, good for a quick demo."""
    return render_template("local.html")


@app.route("/play/vs-bot", methods=["POST"])
@login_required
def play_vs_bot():
    user = current_user()
    level = int(request.form.get("level", 3))
    level = max(1, min(8, level))
    seconds, increment = parse_time_control(request.form)
    board = Board()
    game_id = db.create_game(user["id"], None, board.to_dict(),
                              time_control_seconds=seconds, increment_seconds=increment,
                              is_bot=1, bot_level=level)
    return redirect(url_for("game_view", game_id=game_id))


@app.route("/local/start", methods=["POST"])
@login_required
def local_start():
    user = current_user()
    board = Board()
    seconds, increment = parse_time_control(request.form)
    game_id = db.create_game(user["id"], user["id"], board.to_dict(),
                              time_control_seconds=seconds, increment_seconds=increment)
    return redirect(url_for("game_view", game_id=game_id))


# ---------------------------------------------------------------- lobby ----

@app.route("/play/create", methods=["POST"])
@login_required
def create_game():
    user = current_user()
    board = Board()
    seconds, increment = parse_time_control(request.form)
    game_id = db.create_game(user["id"], None, board.to_dict(),
                              time_control_seconds=seconds, increment_seconds=increment)
    return redirect(url_for("game_view", game_id=game_id))


@app.route("/play/join/<int:game_id>", methods=["POST"])
@login_required
def join_game(game_id):
    user = current_user()
    game = db.get_game(game_id)
    if game is None or game["black_id"] is not None:
        flash("That game is no longer available.")
        return redirect(url_for("index"))
    if game["white_id"] == user["id"]:
        flash("You can't play yourself.")
        return redirect(url_for("index"))
    conn = db.get_db()
    conn.execute("UPDATE games SET black_id = ? WHERE id = ?", (user["id"], game_id))
    conn.commit()
    conn.close()
    return redirect(url_for("game_view", game_id=game_id))


# ----------------------------------------------------------------- game ----

@app.route("/game/<int:game_id>")
@login_required
def game_view(game_id):
    game = db.get_game(game_id)
    if game is None:
        flash("Game not found.")
        return redirect(url_for("index"))
    white = db.get_user_by_id(game["white_id"])
    black = db.get_user_by_id(game["black_id"]) if game["black_id"] else None
    return render_template("game.html", game=game, white=white, black=black,
                            user=current_user())


@app.route("/api/game/<int:game_id>/state")
@login_required
def game_state(game_id):
    game = db.get_game(game_id)
    if game is None:
        return jsonify({"error": "not found"}), 404

    if check_and_apply_timeout(game):
        game = db.get_game(game_id)  # reload -- status/result_reason just changed

    state = json.loads(game["state_json"])
    board = Board.from_dict(state)

    # Important: compute anything that internally simulates-and-restores moves
    # (legal move generation, check detection) BEFORE reading board.board below.
    # Those simulations mutate-then-restore the array in place; grabbing a
    # reference to board.board before they finish would capture a mid-simulation
    # state instead of the final, correct one.
    in_check = board.is_in_check(board.turn)
    legal_moves = board.legal_moves_dict_for_frontend() if game["status"] == "ongoing" else {}

    return jsonify({
        "board": deepcopy(board.board),
        "turn": state["turn"],
        "history": state["history"],
        "status": game["status"],
        "in_check": in_check,
        "legal_moves": legal_moves,
        "white_id": game["white_id"],
        "black_id": game["black_id"],
        "result_reason": game["result_reason"],
        "time_control_seconds": game["time_control_seconds"],
        "increment_seconds": game["increment_seconds"],
        "white_time_left": game["white_time_left"],
        "black_time_left": game["black_time_left"],
        "turn_started_at": game["turn_started_at"],
    })


@app.route("/api/game/<int:game_id>/move", methods=["POST"])
@login_required
def make_move(game_id):
    user = current_user()
    game = db.get_game(game_id)
    if game is None:
        return jsonify({"error": "not found"}), 404

    if check_and_apply_timeout(game):
        return jsonify({"error": "time is up", "status": "timeout"}), 400

    if game["status"] != "ongoing":
        return jsonify({"error": "game is over"}), 400
    if game["black_id"] is None and not game["is_bot"]:
        return jsonify({"error": "waiting for an opponent"}), 400

    state = json.loads(game["state_json"])
    board = Board.from_dict(state)

    is_white_turn = board.turn == "w"
    expected_player = game["white_id"] if is_white_turn else game["black_id"]
    if user["id"] != expected_player:
        return jsonify({"error": "not your turn"}), 403

    data = request.get_json(force=True)
    frm, to, promotion = data.get("from"), data.get("to"), data.get("promotion")

    moved_color = board.turn
    move = board.make_move(frm, to, promotion=promotion.upper() if promotion else None)
    if move is None:
        return jsonify({"error": "illegal move"}), 400

    new_state = board.to_dict()
    new_state["history"] = state.get("history", []) + [move.to_uci()]
    db.update_game_state(game_id, new_state)
    settle_clock_after_move(game, moved_color)

    status = board.game_status()
    if status == "checkmate":
        winner = "white_won" if moved_color == "w" else "black_won"
        apply_game_result(game, winner, "checkmate")
    elif status in ("stalemate", "draw_50move", "draw_insufficient"):
        apply_game_result(game, "draw", status)

    # In a bot game, the bot (always Black) replies immediately, synchronously,
    # within this same request -- the frontend just sees the updated position
    # (including the bot's reply) on its next state fetch, no separate polling
    # or endpoint needed for the bot's turn.
    if game["is_bot"] and status == "ongoing" and board.turn == "b":
        game = db.get_game(game_id)  # reload -- clock settlement above just changed it
        if not check_and_apply_timeout(game):
            bot_move = bot.choose_move(board, "b", game["bot_level"])
            if bot_move is not None:
                bot_move_applied = board.make_move(sq_name(*bot_move.frm), sq_name(*bot_move.to),
                                                    promotion=bot_move.promotion)
                bot_state = board.to_dict()
                bot_state["history"] = new_state["history"] + [bot_move_applied.to_uci()]
                db.update_game_state(game_id, bot_state)
                settle_clock_after_move(game, "b")

                status = board.game_status()
                if status == "checkmate":
                    apply_game_result(game, "black_won", "checkmate")
                elif status in ("stalemate", "draw_50move", "draw_insufficient"):
                    apply_game_result(game, "draw", status)

    return jsonify({"ok": True, "status": status})


@app.route("/api/game/<int:game_id>/resign", methods=["POST"])
@login_required
def resign_game(game_id):
    user = current_user()
    game = db.get_game(game_id)
    if game is None or game["status"] != "ongoing":
        return jsonify({"error": "not available"}), 400
    if user["id"] not in (game["white_id"], game["black_id"]):
        return jsonify({"error": "not a player in this game"}), 403

    if check_and_apply_timeout(game):
        return jsonify({"ok": True})

    winner_status = "black_won" if user["id"] == game["white_id"] else "white_won"
    apply_game_result(game, winner_status, "resignation")
    return jsonify({"ok": True})


# ------------------------------------------------------------ tournaments --

@app.route("/tournaments")
def tournaments_list():
    return render_template("tournaments.html", tournaments=db.list_tournaments())


@app.route("/tournaments/create", methods=["POST"])
@login_required
def tournaments_create():
    name = request.form["name"].strip()
    fmt = request.form.get("format", "swiss")
    rounds = int(request.form.get("rounds", 4) or 4)
    seconds, increment = parse_time_control(request.form)
    tid = db.create_tournament(name or "Untitled Tournament", fmt, rounds,
                                time_control_seconds=seconds, increment_seconds=increment)
    db.join_tournament(tid, current_user()["id"])
    return redirect(url_for("tournament_detail", tid=tid))


@app.route("/tournaments/<int:tid>")
def tournament_detail(tid):
    t = db.get_tournament(tid)
    if t is None:
        flash("Tournament not found.")
        return redirect(url_for("tournaments_list"))
    players = db.tournament_players(tid)
    matches = db.all_matches(tid)
    by_round = {}
    for m in matches:
        by_round.setdefault(m["round_number"], []).append(m)
    return render_template("tournament_detail.html", t=t, players=players,
                            by_round=by_round, user=current_user())


@app.route("/tournaments/<int:tid>/join", methods=["POST"])
@login_required
def tournament_join(tid):
    t = db.get_tournament(tid)
    if t is None or t["status"] != "pending":
        flash("You can only join a tournament before it starts.")
        return redirect(url_for("tournament_detail", tid=tid))
    db.join_tournament(tid, current_user()["id"])
    return redirect(url_for("tournament_detail", tid=tid))


@app.route("/tournaments/<int:tid>/start", methods=["POST"])
@login_required
def tournament_start(tid):
    t = db.get_tournament(tid)
    players = db.tournament_players(tid)
    if t is None or t["status"] != "pending":
        flash("Tournament already started.")
        return redirect(url_for("tournament_detail", tid=tid))
    if len(players) < 2:
        flash("Need at least 2 players to start.")
        return redirect(url_for("tournament_detail", tid=tid))
    if t["format"] == "round_robin":
        conn = db.get_db()
        conn.execute("UPDATE tournaments SET total_rounds = ? WHERE id = ?",
                     (tourney.round_robin_total_rounds(len(players)), tid))
        conn.commit()
        conn.close()
    tourney.start_tournament(tid)
    return redirect(url_for("tournament_detail", tid=tid))


@app.route("/tournaments/match/<int:mid>/play", methods=["POST"])
@login_required
def tournament_match_play(mid):
    match = db.get_tournament_match(mid)
    user = current_user()
    if match is None:
        flash("Match not found.")
        return redirect(url_for("tournaments_list"))
    if match["game_id"]:
        return redirect(url_for("game_view", game_id=match["game_id"]))
    if user["id"] not in (match["white_id"], match["black_id"]):
        flash("You're not a player in this match.")
        return redirect(url_for("tournament_detail", tid=match["tournament_id"]))
    board = Board()
    t = db.get_tournament(match["tournament_id"])
    game_id = db.create_game(match["white_id"], match["black_id"], board.to_dict(),
                              tournament_match_id=mid,
                              time_control_seconds=t["time_control_seconds"],
                              increment_seconds=t["increment_seconds"])
    db.set_match_result(mid, None, game_id=game_id)
    return redirect(url_for("game_view", game_id=game_id))


# ---------------------------------------------------------------- puzzles --

@app.route("/puzzles")
@login_required
def puzzles_page():
    return render_template("puzzles.html")


@app.route("/api/puzzle/new")
@login_required
def puzzle_new():
    difficulty = request.args.get("difficulty", "easy")
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "easy"

    generated = puzzle.generate_puzzle(difficulty)
    puzzle_id = db.create_puzzle(generated["difficulty"], generated["board"], generated["turn"],
                                  generated["solution"], generated.get("title"))

    board = Board.from_dict({
        "board": generated["board"], "turn": generated["turn"],
        "castling": {"wK": False, "wQ": False, "bK": False, "bQ": False},
        "en_passant": None, "halfmove_clock": 0, "fullmove_number": 1,
    })
    return jsonify({
        "puzzle_id": puzzle_id,
        "board": board.board,
        "turn": generated["turn"],
        "difficulty": generated["difficulty"],
        "title": generated.get("title"),
        "legal_moves": board.legal_moves_dict_for_frontend(),
        "in_check": board.is_in_check(board.turn),
    })


@app.route("/api/puzzle/<int:puzzle_id>/attempt", methods=["POST"])
@login_required
def puzzle_attempt(puzzle_id):
    row = db.get_puzzle(puzzle_id)
    if row is None:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True)
    frm, to, promotion = data.get("from"), data.get("to"), data.get("promotion")

    board = Board.from_dict({
        "board": json.loads(row["board_json"]), "turn": row["turn"],
        "castling": {"wK": False, "wQ": False, "bK": False, "bQ": False},
        "en_passant": None, "halfmove_clock": 0, "fullmove_number": 1,
    })
    move = board.make_move(frm, to, promotion=promotion.upper() if promotion else None)
    if move is None:
        return jsonify({"error": "illegal move"}), 400

    solution = json.loads(row["solution_json"])
    submitted_uci = move.to_uci()
    matches_solution = any(submitted_uci[:4] == s[:4] for s in solution)
    also_delivers_mate = row["difficulty"] == "easy" and board.game_status() == "checkmate"
    correct = matches_solution or also_delivers_mate

    return jsonify({
        "correct": correct,
        "solution": solution,
        "resulting_board": board.board,
        "resulting_status": board.game_status(),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
