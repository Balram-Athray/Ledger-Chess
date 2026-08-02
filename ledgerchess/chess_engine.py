"""
chess_engine.py
----------------
A complete, dependency-free chess rules engine.

Board representation:
  - 8x8 grid, board[row][col]
  - row 0 = rank 1 (white's back rank), row 7 = rank 8
  - col 0 = file a, col 7 = file h
  - a square holds either None (empty) or a 2-character string:
        first char = color ('w' or 'b')
        second char = piece type ('P','N','B','R','Q','K')

This file is intentionally self-contained (no pip installs required) so it
can be read, explained, and defended in a viva/project demonstration.
"""

from copy import deepcopy

FILES = "abcdefgh"

PIECE_VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}

DIRECTIONS = {
    "B": [(1, 1), (1, -1), (-1, 1), (-1, -1)],
    "R": [(1, 0), (-1, 0), (0, 1), (0, -1)],
    "Q": [(1, 1), (1, -1), (-1, 1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)],
}

KNIGHT_OFFSETS = [(2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2)]
KING_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def in_bounds(row, col):
    return 0 <= row < 8 and 0 <= col < 8


def sq_name(row, col):
    return f"{FILES[col]}{row + 1}"


def sq_from_name(name):
    col = FILES.index(name[0])
    row = int(name[1:]) - 1
    return row, col


class Move:
    """A single move, with enough metadata to apply / undo / notate it."""

    def __init__(self, frm, to, piece, captured=None, promotion=None,
                 is_castle=None, is_en_passant=False):
        self.frm = frm
        self.to = to
        self.piece = piece            # e.g. 'wP'
        self.captured = captured      # piece captured, if any
        self.promotion = promotion    # 'Q','R','B','N' or None
        self.is_castle = is_castle    # 'K' (kingside) / 'Q' (queenside) / None
        self.is_en_passant = is_en_passant

    def to_uci(self):
        """e.g. 'e2e4' or 'e7e8q' for promotion."""
        s = sq_name(*self.frm) + sq_name(*self.to)
        if self.promotion:
            s += self.promotion.lower()
        return s

    def __repr__(self):
        return f"<Move {self.to_uci()}>"


class Board:
    def __init__(self):
        self.board = [[None] * 8 for _ in range(8)]
        self.turn = "w"
        self.castling = {"wK": True, "wQ": True, "bK": True, "bQ": True}
        self.en_passant = None          # (row, col) square a pawn can capture into
        self.halfmove_clock = 0         # for the 50-move rule
        self.fullmove_number = 1
        self.history = []               # list of Move objects, in order played
        self._setup_start()

    # ---------------------------------------------------------- setup ----

    def _setup_start(self):
        back = ["R", "N", "B", "Q", "K", "B", "N", "R"]
        for col in range(8):
            self.board[0][col] = "w" + back[col]
            self.board[1][col] = "wP"
            self.board[6][col] = "bP"
            self.board[7][col] = "b" + back[col]

    # ------------------------------------------------------- utilities ----

    def piece_at(self, row, col):
        return self.board[row][col]

    def color_at(self, row, col):
        p = self.board[row][col]
        return p[0] if p else None

    def find_king(self, color):
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p == color + "K":
                    return (r, c)
        return None

    def opponent(self, color):
        return "b" if color == "w" else "w"

    # --------------------------------------------------- attack testing ----

    def is_square_attacked(self, row, col, by_color):
        """True if `by_color` attacks (row, col) in the current position."""
        # Pawns
        direction = 1 if by_color == "w" else -1
        for dc in (-1, 1):
            r, c = row - direction, col + dc
            if in_bounds(r, c) and self.board[r][c] == by_color + "P":
                return True
        # Knights
        for dr, dc in KNIGHT_OFFSETS:
            r, c = row + dr, col + dc
            if in_bounds(r, c) and self.board[r][c] == by_color + "N":
                return True
        # King (adjacent)
        for dr, dc in KING_OFFSETS:
            r, c = row + dr, col + dc
            if in_bounds(r, c) and self.board[r][c] == by_color + "K":
                return True
        # Sliding pieces: bishop/queen on diagonals, rook/queen on files/ranks
        for dr, dc in DIRECTIONS["B"]:
            r, c = row + dr, col + dc
            while in_bounds(r, c):
                p = self.board[r][c]
                if p:
                    if p[0] == by_color and p[1] in ("B", "Q"):
                        return True
                    break
                r, c = r + dr, c + dc
        for dr, dc in DIRECTIONS["R"]:
            r, c = row + dr, col + dc
            while in_bounds(r, c):
                p = self.board[r][c]
                if p:
                    if p[0] == by_color and p[1] in ("R", "Q"):
                        return True
                    break
                r, c = r + dr, c + dc
        return False

    def is_in_check(self, color):
        king = self.find_king(color)
        if not king:
            return False
        return self.is_square_attacked(king[0], king[1], self.opponent(color))

    # --------------------------------------------------- move generation ----

    def pseudo_legal_moves(self, row, col):
        """Moves for the piece on (row,col) ignoring whether they leave own king in check."""
        piece = self.board[row][col]
        if not piece:
            return []
        color, kind = piece[0], piece[1]
        moves = []

        if kind == "P":
            direction = 1 if color == "w" else -1
            start_row = 1 if color == "w" else 6
            promo_row = 7 if color == "w" else 0
            # forward
            r1 = row + direction
            if in_bounds(r1, col) and self.board[r1][col] is None:
                self._add_pawn_move(moves, (row, col), (r1, col), promo_row)
                r2 = row + 2 * direction
                if row == start_row and self.board[r2][col] is None:
                    moves.append(Move((row, col), (r2, col), piece))
            # captures
            for dc in (-1, 1):
                r, c = row + direction, col + dc
                if in_bounds(r, c):
                    target = self.board[r][c]
                    if target and target[0] != color:
                        self._add_pawn_move(moves, (row, col), (r, c), promo_row, captured=target)
                    elif self.en_passant == (r, c) and target is None:
                        moves.append(Move((row, col), (r, c), piece,
                                           captured=color and (self.opponent(color) + "P"),
                                           is_en_passant=True))

        elif kind == "N":
            for dr, dc in KNIGHT_OFFSETS:
                r, c = row + dr, col + dc
                if in_bounds(r, c):
                    target = self.board[r][c]
                    if target is None or target[0] != color:
                        moves.append(Move((row, col), (r, c), piece, captured=target))

        elif kind == "K":
            for dr, dc in KING_OFFSETS:
                r, c = row + dr, col + dc
                if in_bounds(r, c):
                    target = self.board[r][c]
                    if target is None or target[0] != color:
                        moves.append(Move((row, col), (r, c), piece, captured=target))
            moves.extend(self._castling_moves(row, col, color))

        else:  # B, R, Q
            for dr, dc in DIRECTIONS[kind]:
                r, c = row + dr, col + dc
                while in_bounds(r, c):
                    target = self.board[r][c]
                    if target is None:
                        moves.append(Move((row, col), (r, c), piece))
                    else:
                        if target[0] != color:
                            moves.append(Move((row, col), (r, c), piece, captured=target))
                        break
                    r, c = r + dr, c + dc

        return moves

    def _add_pawn_move(self, moves, frm, to, promo_row, captured=None):
        piece = self.board[frm[0]][frm[1]]
        if to[0] == promo_row:
            for promo in ("Q", "R", "B", "N"):
                moves.append(Move(frm, to, piece, captured=captured, promotion=promo))
        else:
            moves.append(Move(frm, to, piece, captured=captured))

    def _castling_moves(self, row, col, color):
        moves = []
        if self.is_in_check(color):
            return moves
        opp = self.opponent(color)
        back_row = 0 if color == "w" else 7
        if row != back_row or col != 4:
            return moves

        # kingside
        if self.castling[color + "K"]:
            if self.board[back_row][5] is None and self.board[back_row][6] is None \
               and self.board[back_row][7] == color + "R":
                if not self.is_square_attacked(back_row, 5, opp) and \
                   not self.is_square_attacked(back_row, 6, opp):
                    moves.append(Move((row, col), (back_row, 6), color + "K", is_castle="K"))
        # queenside
        if self.castling[color + "Q"]:
            if self.board[back_row][1] is None and self.board[back_row][2] is None \
               and self.board[back_row][3] is None and self.board[back_row][0] == color + "R":
                if not self.is_square_attacked(back_row, 3, opp) and \
                   not self.is_square_attacked(back_row, 2, opp):
                    moves.append(Move((row, col), (back_row, 2), color + "K", is_castle="Q"))
        return moves

    def legal_moves(self, row, col):
        """Pseudo-legal moves filtered to those that don't leave own king in check."""
        piece = self.board[row][col]
        if not piece:
            return []
        color = piece[0]
        legal = []
        for move in self.pseudo_legal_moves(row, col):
            snapshot = self._snapshot()
            self._apply(move)
            if not self.is_in_check(color):
                legal.append(move)
            self._restore(snapshot)
        return legal

    def all_legal_moves(self, color):
        """dict: 'e2' -> [Move, ...] for every piece of `color`."""
        result = {}
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p and p[0] == color:
                    mvs = self.legal_moves(r, c)
                    if mvs:
                        result[sq_name(r, c)] = mvs
        return result

    def has_any_legal_move(self, color):
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p and p[0] == color and self.legal_moves(r, c):
                    return True
        return False

    # --------------------------------------------------- state snapshot ----

    def _snapshot(self):
        return (deepcopy(self.board), self.turn, dict(self.castling),
                self.en_passant, self.halfmove_clock, self.fullmove_number)

    def _restore(self, snap):
        (self.board, self.turn, self.castling, self.en_passant,
         self.halfmove_clock, self.fullmove_number) = snap

    # ---------------------------------------------------- applying moves ----

    def _apply(self, move):
        """Apply a move to the board WITHOUT legality checking or turn/history bookkeeping."""
        fr, fc = move.frm
        tr, tc = move.to
        piece = self.board[fr][fc]
        color = piece[0]

        if move.is_en_passant:
            self.board[fr][tc] = None  # remove the captured pawn (which sits beside, not on, dest)

        self.board[tr][tc] = piece
        self.board[fr][fc] = None

        if move.promotion:
            self.board[tr][tc] = color + move.promotion

        if move.is_castle:
            back_row = fr
            if move.is_castle == "K":
                self.board[back_row][5] = self.board[back_row][7]
                self.board[back_row][7] = None
            else:
                self.board[back_row][3] = self.board[back_row][0]
                self.board[back_row][0] = None

        # update castling rights
        if piece[1] == "K":
            self.castling[color + "K"] = False
            self.castling[color + "Q"] = False
        if piece[1] == "R":
            if (fr, fc) == (0, 0):
                self.castling["wQ"] = False
            elif (fr, fc) == (0, 7):
                self.castling["wK"] = False
            elif (fr, fc) == (7, 0):
                self.castling["bQ"] = False
            elif (fr, fc) == (7, 7):
                self.castling["bK"] = False
        if move.captured:
            if (tr, tc) == (0, 0):
                self.castling["wQ"] = False
            elif (tr, tc) == (0, 7):
                self.castling["wK"] = False
            elif (tr, tc) == (7, 0):
                self.castling["bQ"] = False
            elif (tr, tc) == (7, 7):
                self.castling["bK"] = False

        # en passant target for the *next* move
        if piece[1] == "P" and abs(tr - fr) == 2:
            self.en_passant = ((fr + tr) // 2, fc)
        else:
            self.en_passant = None

    def make_move(self, frm, to, promotion=None):
        """
        Public entry point: frm/to are square names like 'e2','e4'.
        Returns the Move object if legal & applied, else None.
        """
        fr, fc = sq_from_name(frm) if isinstance(frm, str) else frm
        tr, tc = sq_from_name(to) if isinstance(to, str) else to
        piece = self.board[fr][fc]
        if not piece or piece[0] != self.turn:
            return None

        candidates = self.legal_moves(fr, fc)
        chosen = None
        for m in candidates:
            if m.to == (tr, tc) and (m.promotion == promotion or (m.promotion and promotion is None and m.promotion == "Q")):
                chosen = m
                break
        if chosen is None:
            for m in candidates:
                if m.to == (tr, tc):
                    chosen = m
                    break
        if chosen is None:
            return None

        color = self.turn
        if chosen.piece[1] == "P" or chosen.captured:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1

        self._apply(chosen)
        self.history.append(chosen)
        self.turn = self.opponent(color)
        if color == "b":
            self.fullmove_number += 1
        return chosen

    # ------------------------------------------------------- game state ----

    def game_status(self):
        """
        Returns one of:
          'ongoing', 'checkmate', 'stalemate', 'draw_50move', 'draw_insufficient'
        along with the side to move (useful for deciding the winner).
        """
        color = self.turn
        has_move = self.has_any_legal_move(color)
        in_check = self.is_in_check(color)

        if not has_move and in_check:
            return "checkmate"
        if not has_move and not in_check:
            return "stalemate"
        if self.halfmove_clock >= 100:  # 50 full moves = 100 half-moves
            return "draw_50move"
        if self._insufficient_material():
            return "draw_insufficient"
        return "ongoing"

    def _insufficient_material(self):
        pieces = [p for row in self.board for p in row if p]
        if len(pieces) <= 2:
            return True
        if len(pieces) == 3:
            kinds = sorted(p[1] for p in pieces)
            if kinds == ["B", "K", "K"] or kinds == ["K", "K", "N"]:
                return True
        return False

    # ------------------------------------------------------- (de)serialize ----

    def to_dict(self):
        return {
            "board": deepcopy(self.board),
            "turn": self.turn,
            "castling": self.castling,
            "en_passant": self.en_passant,
            "halfmove_clock": self.halfmove_clock,
            "fullmove_number": self.fullmove_number,
            "history": [m.to_uci() for m in self.history],
            "status": self.game_status(),
            "in_check": self.is_in_check(self.turn),
        }

    @classmethod
    def from_dict(cls, data):
        b = cls.__new__(cls)
        b.board = deepcopy(data["board"])
        b.turn = data["turn"]
        b.castling = data["castling"]
        b.en_passant = tuple(data["en_passant"]) if data["en_passant"] else None
        b.halfmove_clock = data["halfmove_clock"]
        b.fullmove_number = data["fullmove_number"]
        b.history = []  # full Move objects aren't reconstructed; uci log kept separately
        return b

    def legal_moves_dict_for_frontend(self):
        """{'e2': ['e3','e4'], ...} -- simple square-name lists for the JS board."""
        out = {}
        for square, moves in self.all_legal_moves(self.turn).items():
            out[square] = [sq_name(*m.to) + (m.promotion.lower() if m.promotion else "") for m in moves]
        return out
