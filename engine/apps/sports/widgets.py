"""Pre-rendered, measured graphic elements for sports cards.

Every widget returns a PIL image of exactly the size it needs, so the card
layouts can measure before placing. Widgets that contain text take a max
width and degrade internally (drop pieces, shrink, finally dot-truncate) —
they never return an image wider than asked for.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from libraries.layout.library import TextSpec, first_fitting, text_img
from libraries.text_renderer.library import _resolve_font, arrow_img, render_text

from .colors import RGB
from .model import GameView

GRAY: RGB = (140, 140, 140)
YELLOW: RGB = (255, 210, 0)

_DIAMOND_FILL: RGB = (220, 180, 0)
_DIAMOND_EMPTY: RGB = (70, 70, 70)


# ── Composition helpers ────────────────────────────────────────────────────────


def hstack(pieces: list[Image.Image], gap: int = 2, align: str = "m") -> Image.Image:
    """Concatenate images horizontally on a black background."""
    pieces = [p for p in pieces if p.width > 0]
    if not pieces:
        return Image.new("RGB", (1, 1))
    width = sum(p.width for p in pieces) + gap * (len(pieces) - 1)
    height = max(p.height for p in pieces)
    out = Image.new("RGB", (width, height), (0, 0, 0))
    x = 0
    for piece in pieces:
        y = {"t": 0, "m": (height - piece.height) // 2, "b": height - piece.height}[align]
        if piece.mode == "RGBA":
            out.paste(piece.convert("RGB"), (x, y), piece.split()[3])
        else:
            out.paste(piece, (x, y))
        x += piece.width + gap
    return out


def _baseline_hstack(
    parts: list[tuple[str, RGB]], font_size: int
) -> Image.Image:
    """Concatenate same-size text pieces with true baseline alignment.

    Needed when pieces mix heights (e.g. "67'" + "Group" with a descender);
    plain bottom/middle alignment would visibly shift the shorter piece.
    """
    font = _resolve_font(font_size)
    dummy = ImageDraw.Draw(Image.new("L", (1, 1)))
    imgs = [render_text(text, color, font_size) for text, color in parts]
    bboxes = [dummy.textbbox((0, 0), text, font=font) for text, _ in parts]
    min_top = min(b[1] for b in bboxes)
    bar_h = max(max(b[3] for b in bboxes) - min_top, 1)
    out = Image.new("RGB", (sum(i.width for i in imgs), bar_h), (0, 0, 0))
    x = 0
    for img, bbox in zip(imgs, bboxes):
        out.paste(img, (x, bbox[1] - min_top))
        x += img.width
    return out


def truncate_to_fit(text: str, color: RGB, size: int, max_w: int) -> Image.Image:
    """Guaranteed-fit fallback: drop trailing characters until the text fits."""
    while text:
        img = render_text(text, color, size)
        if img.width <= max_w:
            return img
        text = text[:-1].rstrip()
    return Image.new("RGB", (1, 1))


# ── Baseball diamond ───────────────────────────────────────────────────────────


def diamond_img(
    on_first: bool, on_second: bool, on_third: bool, size: int
) -> Image.Image:
    """Pixel-exact baseball diamond showing base occupancy.

    The size snaps down to odd so every base has an integer centre, and bases
    are rasterized as mirrored row spans — guaranteed left/right symmetric at
    any size (ImageDraw.polygon was not).
    """
    size = max(7, size if size % 2 else size - 1)
    r = max(2, size // 5)
    inset = max(r, size // 4)
    c = size // 2

    img = Image.new("RGB", (size, size), (0, 0, 0))
    px = img.load()
    bases = [
        ((c, inset), on_second),             # 2B top
        ((size - 1 - inset, c), on_first),   # 1B right
        ((inset, c), on_third),              # 3B left
    ]
    for (cx, cy), occupied in bases:
        color = _DIAMOND_FILL if occupied else _DIAMOND_EMPTY
        for dy in range(-r, r + 1):
            span = r - abs(dy)
            if occupied:
                for dx in range(-span, span + 1):
                    px[cx + dx, cy + dy] = color
            elif span == 0:
                px[cx, cy + dy] = color
            else:
                px[cx - span, cy + dy] = color
                px[cx + span, cy + dy] = color
    # Tight symmetric crop (no home plate is drawn, so the bottom quarter and
    # outer margins are empty) — lets callers centre the visible pixels.
    return img.crop((inset - r, inset - r, size - inset + r, c + r + 1))


def _inning_img(status: str, font: int) -> Image.Image:
    """Inning text with a half-inning arrow (▲ top / ▼ bottom) when parseable."""
    low = status.lower()
    if low.startswith("top "):
        half_up, inning = True, status[4:]
    elif low.startswith("bottom "):
        half_up, inning = False, status[7:]
    elif low.startswith("bot "):
        half_up, inning = False, status[4:]
    else:
        return render_text(status, GRAY, font)
    txt = render_text(inning, GRAY, font)
    arr = arrow_img(half_up, max(3, txt.height * 2 // 3), GRAY)
    return hstack([arr, txt], gap=2)


def baseball_status_img(
    view: GameView,
    font: int,
    max_w: int,
    *,
    with_diamond: bool,
    with_outs: bool = True,
) -> Image.Image:
    """Footer centre for live baseball: [▲ inning] [diamond] [N outs], degrading
    by dropping outs, then the diamond, then truncating the inning text."""
    situation = view.situation
    inning = _inning_img(view.status, font)
    outs_n = int(situation.get("outs") or 0)
    outs = render_text("1 out" if outs_n == 1 else f"{outs_n} outs", GRAY, font)
    diamond = diamond_img(
        bool(situation.get("onFirst")),
        bool(situation.get("onSecond")),
        bool(situation.get("onThird")),
        inning.height + 2,
    ) if with_diamond else None

    candidates: list[list[Image.Image]] = []
    if diamond is not None and with_outs:
        candidates.append([inning, diamond, outs])
    if diamond is not None:
        candidates.append([inning, diamond])
    if with_outs:
        candidates.append([inning, outs])
    candidates.append([inning])

    for pieces in candidates:
        img = hstack(pieces, gap=3)
        if img.width <= max_w:
            return img
    return truncate_to_fit(view.status, GRAY, font, max_w)


# ── Soccer ─────────────────────────────────────────────────────────────────────


def _abbreviate_note(note: str) -> str:
    return (
        note.replace("Quarter-Final", "Qtr-Fnl")
        .replace("Semi-Final", "Sem-Fnl")
        .replace("Group ", "Grp ")
    )


def soccer_status_img(view: GameView, font: int, max_w: int) -> Image.Image:
    """Footer centre for soccer: yellow minute + gray match note, degrading to
    an abbreviated note and finally the minute alone."""
    minute = view.status
    if view.state == "post":
        minute = "Final"
    elif minute.upper() == "HT":
        minute = "Half"

    for note in (view.match_note, _abbreviate_note(view.match_note)):
        if not note:
            break
        img = _baseline_hstack([(minute, YELLOW), (" | ", GRAY), (note, GRAY)], font)
        if img.width <= max_w:
            return img

    img = render_text(minute, YELLOW, font)
    if img.width <= max_w:
        return img
    return truncate_to_fit(minute, YELLOW, font, max_w)


_GOAL_GAP = 1


def _goal_sort_key(t: str) -> tuple[int, int]:
    s = t.rstrip("'").replace("(og)", "").strip()
    if "+" in s:
        a, b = s.split("+", 1)
        try:
            return (int(a), int(b))
        except ValueError:
            pass
    try:
        return (int(s), 0)
    except ValueError:
        return (999, 0)


def goal_list_img(
    view: GameView, max_h: int, max_w: int, *, font: int = 9
) -> Image.Image | None:
    """Soccer goal times as one measured image, attributed by team.

    Two columns whenever they fit — away goals right-aligned in the left
    column, home left-aligned in the right, one row per goal in global time
    order — so each minute reads on its team's side of the card. Falls back
    to a single chronological column (still team-colored) when narrow. When
    rows don't fit, the *earliest* are dropped behind a gray "+N" marker —
    never silently clipped.
    """
    rows = sorted(
        [("away", t) for t in view.away_goals] + [("home", t) for t in view.home_goals],
        key=lambda e: _goal_sort_key(e[1]),
    )
    if not rows:
        return None

    row_h = render_text("0'", (255, 255, 255), font).height
    capacity = max(1, (max_h + _GOAL_GAP) // (row_h + _GOAL_GAP))
    hidden = 0
    if len(rows) > capacity:
        hidden = len(rows) - (capacity - 1)
        rows = rows[hidden:]

    colors = {"away": view.away.color, "home": view.home.color}
    imgs = [render_text(t, colors[side], font) for side, t in rows]
    marker = render_text(f"+{hidden}", GRAY, font) if hidden else None

    n_rows = len(rows) + (1 if marker else 0)
    total_h = n_rows * row_h + (n_rows - 1) * _GOAL_GAP
    col_w = max(img.width for img in imgs + ([marker] if marker else []))

    sep = 2
    if col_w * 2 + sep * 2 <= max_w:
        width = col_w * 2 + sep * 2
        out = Image.new("RGB", (width, total_h), (0, 0, 0))
        y = 0
        if marker:
            out.paste(marker, ((width - marker.width) // 2, y))
            y += row_h + _GOAL_GAP
        for (side, _t), img in zip(rows, imgs):
            x = col_w - img.width if side == "away" else col_w + 2 * sep
            out.paste(img, (x, y))
            y += row_h + _GOAL_GAP
        return out

    if col_w > max_w:
        return None  # no room for goals at all — drop the widget entirely
    out = Image.new("RGB", (col_w, total_h), (0, 0, 0))
    y = 0
    if marker:
        out.paste(marker, ((col_w - marker.width) // 2, y))
        y += row_h + _GOAL_GAP
    for img in imgs:
        out.paste(img, ((col_w - img.width) // 2, y))
        y += row_h + _GOAL_GAP
    return out


# ── Generic footer status ──────────────────────────────────────────────────────


def plain_status_img(text: str, font: int, max_w: int, color: RGB = GRAY) -> Image.Image:
    spec = first_fitting(max_w, [TextSpec(text, font), TextSpec(text, 7)])
    if spec is not None:
        return text_img(spec, color)
    return truncate_to_fit(text, color, 7, max_w)


def status_img(
    view: GameView, font: int, max_w: int, *, diamond_in_footer: bool = False
) -> Image.Image:
    """The footer centre element for any sport/state, fitted to max_w."""
    if view.is_baseball_live:
        return baseball_status_img(view, font, max_w, with_diamond=diamond_in_footer)
    if view.is_soccer and view.state in ("in", "post"):
        return soccer_status_img(view, font, max_w)
    if view.is_soccer and view.match_note:
        for note in (view.match_note, _abbreviate_note(view.match_note)):
            img = render_text(f"{view.status} | {note}", GRAY, font)
            if img.width <= max_w:
                return img
    return plain_status_img(view.status, font, max_w)
