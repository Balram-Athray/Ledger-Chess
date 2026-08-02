"""
elo.py
------
Standard ELO rating calculation (the same core formula FIDE and chess.com use,
simplified to a single fixed K-factor for clarity in a school project).

score: 1.0 = win, 0.5 = draw, 0.0 = loss (from the perspective of `rating_a`)
"""

DEFAULT_K = 32
DEFAULT_RATING = 1200


def expected_score(rating_a, rating_b):
    """Probability that player A beats player B, per the logistic ELO model."""
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_ratings(rating_a, rating_b, score_a, k=DEFAULT_K):
    """
    Given two ratings and the result (score_a: 1/0.5/0 for A),
    return (new_rating_a, new_rating_b), rounded to the nearest integer.
    """
    exp_a = expected_score(rating_a, rating_b)
    exp_b = 1 - exp_a
    score_b = 1 - score_a

    new_a = rating_a + k * (score_a - exp_a)
    new_b = rating_b + k * (score_b - exp_b)
    return round(new_a), round(new_b)


def k_factor_for(games_played, rating):
    """
    A slightly more realistic variable K-factor, in case you want to show
    you understand how real rating systems (like FIDE's) scale K down for
    experienced/high-rated players. Not used by default -- see DEFAULT_K.
    """
    if games_played < 30:
        return 40
    if rating >= 2400:
        return 10
    return 20
