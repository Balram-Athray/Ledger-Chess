# Knight's Ledger &mdash; a chess website with ELO ranking and tournaments

A Grade 12 CS investigatory project: a full web chess platform with a
from-scratch rules engine, user accounts, an ELO rating system, and a
Swiss/round-robin tournament system.

## Why it's built this way (useful for your project report/viva)

- **No `python-chess` or other chess library.** `chess_engine.py` implements
  every rule myself: legal move generation, check/checkmate/stalemate
  detection, castling, en passant, pawn promotion, the 50-move rule, and
  insufficient-material draws. This is the part you should be ready to
  explain in detail &mdash; it's the actual "computer science" of the project.
- **No ORM.** `db.py` uses Python's built-in `sqlite3` module directly with
  plain SQL, so the schema (see the `SCHEMA` string at the top of the file)
  is easy to read and explain.
- **ELO system** (`elo.py`) is the same logistic formula FIDE/chess.com use:
  `expected_score = 1 / (1 + 10^((opponent_rating - your_rating)/400))`,
  with a fixed K-factor of 32.
- **Tournament system** (`tournament.py`) supports:
  - **Swiss system** &mdash; each round, players are sorted by score and paired
    against the nearest-scoring opponent they haven't already played.
  - **Round robin** &mdash; every player plays every other player once, using
    the standard "circle method" scheduling algorithm.
- **Frontend** is plain HTML/CSS/JS (`static/js/board.js`) &mdash; no React or
  chessboard.js dependency. The board is rendered as a CSS grid of Unicode
  chess glyphs (&#9812;&#9813;&#9814;&#9815;&#9816;&#9817;), and moves are sent to the server as JSON;
  the server is the single source of truth for legality, so no rules logic
  is duplicated in JavaScript.

## Project structure

```
chesssite/
  app.py              Flask routes (auth, games, tournaments)
  chess_engine.py      The chess rules engine
  db.py                SQLite schema + all database queries
  elo.py                ELO rating calculation
  tournament.py         Swiss/round-robin pairing logic
  templates/            Jinja2 HTML templates
  static/css/style.css  Styling
  static/js/board.js    Client-side board rendering & move interaction
  requirements.txt
  Procfile              Tells hosting platforms how to run the app
```

## Running it locally

You need Python 3.9+ installed.

```bash
cd chesssite
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Open **http://127.0.0.1:5000** in your browser. The SQLite database file
(`chess.db`) is created automatically on first run in the same folder.

To try it with two players on one machine: open the site in two different
browsers (or one normal + one incognito window), register two accounts,
create a game with one, and join it with the other.

## Hosting it for free (so classmates/examiners can access it online)

The easiest option for a school project is **Render.com** (free tier, no
credit card needed for a basic web service):

1. Create a free account at https://render.com and a free account at
   https://github.com if you don't have one.
2. Push this project to a new GitHub repository:
   ```bash
   cd chesssite
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```
3. In Render, click **New +** &rarr; **Web Service**, and connect your
   GitHub repo.
4. Render should auto-detect Python. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app` (already in the `Procfile`, Render
     reads that automatically too)
5. Add an environment variable `SECRET_KEY` set to any random string (used
   to sign login sessions).
6. Click **Create Web Service**. After the first deploy (a minute or two),
   you'll get a public URL like `https://knights-ledger.onrender.com`.

**One caveat:** Render's free tier uses an ephemeral filesystem, so the
SQLite database resets whenever the service restarts/redeploys (it spins
down after 15 minutes of inactivity on the free tier and loses `chess.db`
on the next deploy). That's fine for a live demo, but if you want data to
survive long-term for your write-up, either:
- take a screenshot/export of the leaderboard and tournament results after
  your demo games, or
- upgrade to Render's paid tier with a persistent disk, or
- host on **PythonAnywhere** instead (free tier, and the filesystem does
  persist between restarts) &mdash; upload the project files via their
  "Files" tab, create a new web app with the Flask framework, point it at
  `app.py`, and install `Flask` from a Bash console there.

Either platform is fine to cite in your project report as your deployment
environment.

## Ideas for extending it (if you want more marks for depth)

- New chess mechanics/variants (you mentioned wanting to add these later):
  the engine is structured so a new piece just needs an entry in
  `DIRECTIONS`/its own branch in `pseudo_legal_moves()`, and a new variant
  rule usually only touches `game_status()` or `_apply()`.
- Game clocks / timed games.
- Move takeback requests or draw offers (currently only resignation ends a
  game early).
- An "opening book" or simple minimax bot opponent for practising alone
  against the computer rather than pass-and-play.
