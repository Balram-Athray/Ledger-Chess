"""
tournament.py
-------------
Pairing logic for the tournament system.

Swiss system: each round, players are sorted by score (then rating) and
paired against the nearest-scoring opponent they haven't already played.
A leftover player (odd count) gets a "bye" -- a free point.

Round robin: every player plays every other player exactly once, using the
standard "circle method" so byes/pairings never repeat.
"""

import db


def start_tournament(tid):
    t = db.get_tournament(tid)
    db.set_tournament_status(tid, "ongoing", current_round=1)
    if t["format"] == "round_robin":
        _generate_round_robin_schedule(tid)
        _open_round(tid, 1)
    else:
        _pair_swiss_round(tid, 1)


def _open_round(tid, round_number):
    """For round-robin, matches for every round already exist; nothing else to do."""
    pass


# --------------------------------------------------------------- swiss ----

def _pair_swiss_round(tid, round_number):
    players = db.tournament_players(tid)  # sorted by score desc, elo desc
    pool = list(players)
    paired_ids = set()
    pairings = []

    while pool:
        p1 = pool.pop(0)
        if p1["user_id"] in paired_ids:
            continue
        opponents_faced = db.previous_opponents(tid, p1["user_id"])
        chosen_idx = None
        for i, p2 in enumerate(pool):
            if p2["user_id"] in paired_ids:
                continue
            if p2["user_id"] not in opponents_faced:
                chosen_idx = i
                break
        if chosen_idx is None and pool:
            # everyone remaining has already been played -- pair with the next best anyway
            for i, p2 in enumerate(pool):
                if p2["user_id"] not in paired_ids:
                    chosen_idx = i
                    break

        if chosen_idx is None:
            # p1 has no opponent left this round -> bye
            pairings.append((p1["user_id"], None))
            paired_ids.add(p1["user_id"])
        else:
            p2 = pool.pop(chosen_idx)
            pairings.append((p1["user_id"], p2["user_id"]))
            paired_ids.add(p1["user_id"])
            paired_ids.add(p2["user_id"])

    for white_id, black_id in pairings:
        mid = db.add_tournament_match(tid, round_number, white_id, black_id)
        if black_id is None:
            # bye: automatic full point, no game to play
            db.bump_player_score(tid, white_id, 1.0)
            db.set_match_result(mid, "bye")


def advance_swiss_round(tid):
    """Call after every match in the current round has a result. Starts the next round,
    or marks the tournament completed if it was the final round."""
    t = db.get_tournament(tid)
    next_round = t["current_round"] + 1
    if next_round > t["total_rounds"]:
        db.set_tournament_status(tid, "completed")
        return False
    db.set_tournament_status(tid, "ongoing", current_round=next_round)
    _pair_swiss_round(tid, next_round)
    return True


def round_is_complete(tid, round_number):
    matches = db.matches_for_round(tid, round_number)
    if not matches:
        return False
    return all(m["result"] is not None for m in matches)


# --------------------------------------------------------- round robin ----

def _generate_round_robin_schedule(tid):
    players = db.tournament_players(tid)
    ids = [p["user_id"] for p in players]
    if len(ids) % 2 == 1:
        ids.append(None)  # None = bye slot

    n = len(ids)
    rounds = n - 1
    schedule = []
    fixed = ids[0]
    rotating = ids[1:]

    for r in range(rounds):
        round_pairs = [(fixed, rotating[0])] if rotating else []
        for i in range(1, n // 2):
            round_pairs.append((rotating[i], rotating[-i]))
        schedule.append(round_pairs)
        rotating = [rotating[-1]] + rotating[:-1]

    db.get_db()  # ensure db reachable
    for round_number, pairs in enumerate(schedule, start=1):
        for a, b in pairs:
            if a is None or b is None:
                real = a if b is None else b
                mid = db.add_tournament_match(tid, round_number, real, None)
                db.bump_player_score(tid, real, 1.0)
                db.set_match_result(mid, "bye")
            else:
                db.add_tournament_match(tid, round_number, a, b)


def round_robin_total_rounds(num_players):
    return num_players - 1 if num_players % 2 == 0 else num_players
