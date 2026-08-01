"""
db.py
-----
All database access lives here, using Python's built-in sqlite3 module
(no ORM dependency required -- easy to install anywhere, easy to explain).
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "chess.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    elo INTEGER NOT NULL DEFAULT 1200,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    white_id INTEGER NOT NULL,
    black_id INTEGER,
    state_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ongoing',   -- ongoing / white_won / black_won / draw
    result_reason TEXT,                       -- checkmate / resignation / stalemate / timeout / ...
    tournament_match_id INTEGER,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    time_control_seconds INTEGER NOT NULL DEFAULT 0,  -- 0 = untimed
    increment_seconds INTEGER NOT NULL DEFAULT 0,
    white_time_left REAL NOT NULL DEFAULT 0,
    black_time_left REAL NOT NULL DEFAULT 0,
    turn_started_at TEXT,                     -- when the current side to move's clock started running
    FOREIGN KEY(white_id) REFERENCES users(id),
    FOREIGN KEY(black_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'swiss',     -- swiss / round_robin
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / ongoing / completed
    total_rounds INTEGER NOT NULL DEFAULT 4,
    current_round INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    time_control_seconds INTEGER NOT NULL DEFAULT 0,
    increment_seconds INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tournament_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    UNIQUE(tournament_id, user_id),
    FOREIGN KEY(tournament_id) REFERENCES tournaments(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS tournament_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    white_id INTEGER,
    black_id INTEGER,          -- NULL means white_id got a bye
    game_id INTEGER,
    result TEXT,                -- 'white' / 'black' / 'draw' / NULL (pending)
    FOREIGN KEY(tournament_id) REFERENCES tournaments(id)
);
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    conn.close()


def _migrate(conn):
    """Add columns introduced after a database may already have been created.
    SQLite's CREATE TABLE IF NOT EXISTS won't add columns to an existing table,
    so any new column needs an explicit ALTER TABLE here. Each is wrapped so
    re-running this on an already-migrated database is a harmless no-op."""
    migrations = [
        ("games", "time_control_seconds", "INTEGER NOT NULL DEFAULT 0"),
        ("games", "increment_seconds", "INTEGER NOT NULL DEFAULT 0"),
        ("games", "white_time_left", "REAL NOT NULL DEFAULT 0"),
        ("games", "black_time_left", "REAL NOT NULL DEFAULT 0"),
        ("games", "turn_started_at", "TEXT"),
        ("tournaments", "time_control_seconds", "INTEGER NOT NULL DEFAULT 0"),
        ("tournaments", "increment_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for table, column, coltype in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


def now():
    return datetime.utcnow().isoformat()


# ------------------------------------------------------------------ users --

def create_user(username, password_hash):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def leaderboard(limit=100):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM users ORDER BY elo DESC, wins DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def update_user_rating(user_id, new_elo, result):
    """result: 'win' / 'loss' / 'draw'"""
    conn = get_db()
    col = {"win": "wins", "loss": "losses", "draw": "draws"}[result]
    conn.execute(
        f"UPDATE users SET elo = ?, {col} = {col} + 1 WHERE id = ?",
        (new_elo, user_id),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ games --

def create_game(white_id, black_id, state_dict, tournament_match_id=None,
                 time_control_seconds=0, increment_seconds=0):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO games (white_id, black_id, state_json, created_at, tournament_match_id, "
        "time_control_seconds, increment_seconds, white_time_left, black_time_left, turn_started_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (white_id, black_id, json.dumps(state_dict), now(), tournament_match_id,
         time_control_seconds, increment_seconds, time_control_seconds, time_control_seconds, now()),
    )
    conn.commit()
    game_id = cur.lastrowid
    conn.close()
    return game_id


def update_game_clock(game_id, white_time_left, black_time_left, turn_started_at):
    conn = get_db()
    conn.execute(
        "UPDATE games SET white_time_left = ?, black_time_left = ?, turn_started_at = ? WHERE id = ?",
        (white_time_left, black_time_left, turn_started_at, game_id),
    )
    conn.commit()
    conn.close()


def get_game(game_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    conn.close()
    return row


def update_game_state(game_id, state_dict):
    conn = get_db()
    conn.execute(
        "UPDATE games SET state_json = ? WHERE id = ?",
        (json.dumps(state_dict), game_id),
    )
    conn.commit()
    conn.close()


def finish_game(game_id, status, reason):
    conn = get_db()
    conn.execute(
        "UPDATE games SET status = ?, result_reason = ?, finished_at = ? WHERE id = ?",
        (status, reason, now(), game_id),
    )
    conn.commit()
    conn.close()


def active_games_for_user(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM games WHERE (white_id = ? OR black_id = ?) AND status = 'ongoing' "
        "ORDER BY created_at DESC",
        (user_id, user_id),
    ).fetchall()
    conn.close()
    return rows


def recent_games_for_user(user_id, limit=20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM games WHERE white_id = ? OR black_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (user_id, user_id, limit),
    ).fetchall()
    conn.close()
    return rows


def open_challenges():
    """Games waiting for a second player (black_id IS NULL)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM games WHERE black_id IS NULL AND status = 'ongoing' "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------ tournaments --

def create_tournament(name, fmt, total_rounds, time_control_seconds=0, increment_seconds=0):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO tournaments (name, format, total_rounds, created_at, "
        "time_control_seconds, increment_seconds) VALUES (?, ?, ?, ?, ?, ?)",
        (name, fmt, total_rounds, now(), time_control_seconds, increment_seconds),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def get_tournament(tid):
    conn = get_db()
    row = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tid,)).fetchone()
    conn.close()
    return row


def list_tournaments():
    conn = get_db()
    rows = conn.execute("SELECT * FROM tournaments ORDER BY created_at DESC").fetchall()
    conn.close()
    return rows


def join_tournament(tid, user_id):
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO tournament_players (tournament_id, user_id) VALUES (?, ?)",
            (tid, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def tournament_players(tid):
    conn = get_db()
    rows = conn.execute(
        "SELECT tp.*, u.username, u.elo FROM tournament_players tp "
        "JOIN users u ON u.id = tp.user_id WHERE tp.tournament_id = ? "
        "ORDER BY tp.score DESC, u.elo DESC",
        (tid,),
    ).fetchall()
    conn.close()
    return rows


def set_tournament_status(tid, status, current_round=None):
    conn = get_db()
    if current_round is not None:
        conn.execute(
            "UPDATE tournaments SET status = ?, current_round = ? WHERE id = ?",
            (status, current_round, tid),
        )
    else:
        conn.execute("UPDATE tournaments SET status = ? WHERE id = ?", (status, tid))
    conn.commit()
    conn.close()


def add_tournament_match(tid, round_number, white_id, black_id, game_id=None, result=None):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO tournament_matches (tournament_id, round_number, white_id, black_id, game_id, result) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tid, round_number, white_id, black_id, game_id, result),
    )
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return mid


def get_tournament_match(mid):
    conn = get_db()
    row = conn.execute("SELECT * FROM tournament_matches WHERE id = ?", (mid,)).fetchone()
    conn.close()
    return row


def matches_for_round(tid, round_number):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tournament_matches WHERE tournament_id = ? AND round_number = ?",
        (tid, round_number),
    ).fetchall()
    conn.close()
    return rows


def all_matches(tid):
    conn = get_db()
    rows = conn.execute(
        "SELECT tm.*, uw.username as white_name, ub.username as black_name FROM tournament_matches tm "
        "LEFT JOIN users uw ON uw.id = tm.white_id "
        "LEFT JOIN users ub ON ub.id = tm.black_id "
        "WHERE tm.tournament_id = ? ORDER BY tm.round_number, tm.id",
        (tid,),
    ).fetchall()
    conn.close()
    return rows


def set_match_result(mid, result, game_id=None):
    conn = get_db()
    if game_id is not None:
        conn.execute(
            "UPDATE tournament_matches SET result = ?, game_id = ? WHERE id = ?",
            (result, game_id, mid),
        )
    else:
        conn.execute("UPDATE tournament_matches SET result = ? WHERE id = ?", (result, mid))
    conn.commit()
    conn.close()


def bump_player_score(tid, user_id, points):
    conn = get_db()
    conn.execute(
        "UPDATE tournament_players SET score = score + ? WHERE tournament_id = ? AND user_id = ?",
        (points, tid, user_id),
    )
    conn.commit()
    conn.close()


def previous_opponents(tid, user_id):
    """Set of user_ids this player has already faced (for Swiss pairing)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT white_id, black_id FROM tournament_matches "
        "WHERE tournament_id = ? AND (white_id = ? OR black_id = ?)",
        (tid, user_id, user_id),
    ).fetchall()
    conn.close()
    opponents = set()
    for r in rows:
        if r["white_id"] == user_id and r["black_id"]:
            opponents.add(r["black_id"])
        elif r["black_id"] == user_id and r["white_id"]:
            opponents.add(r["white_id"])
    return opponents
