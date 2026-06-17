"""Pre-rendered, measured graphic elements for sports cards.

Every widget returns a PIL image of exactly the size it needs, so the card
layouts can measure before placing. Widgets that contain text take a max
width and degrade internally (drop pieces, shrink, finally dot-truncate) —
they never return an image wider than asked for.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from libraries.layout.library import TextSpec, first_fitting, fit_font_size, text_img
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
    s = t.rstrip("'").replace("(OG)", "").replace("(PK)", "").strip()
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


# ── Celebrations ───────────────────────────────────────────────────────────────

_CELEBRATION_TEXT: dict[str, tuple[str, str]] = {
    "goal": ("GOAL!", "GOAL"),
    "touchdown": ("TOUCHDOWN!", "TD!"),
    "field_goal": ("FIELD GOAL!", "FG!"),
    "interception": ("INTERCEPTION!", "INT!"),
    "home_run": ("HOME RUN!", "HR!"),
}

CELEBRATION_ANIM_FRAMES = 8

_BALL_WHITE: RGB = (235, 235, 235)
_BALL_DARK: RGB = (30, 30, 30)
_FOOTBALL_BROWN: RGB = (150, 75, 30)
_STITCH_RED: RGB = (220, 40, 40)

# Vertical bounce offsets (fraction of available headroom, eighths).
_BOUNCE_8THS = [0, 1, 3, 5, 6, 5, 3, 1]


def celebration_color(view: GameView) -> RGB:
    """The scoring team's color, or the highlight yellow when side is unknown."""
    celeb = view.celebration
    if celeb is not None and celeb.side in ("away", "home"):
        return getattr(view, celeb.side).color
    return YELLOW


def celebration_text_img(kind: str, color: RGB, max_h: int, max_w: int) -> Image.Image:
    """Biggest fitting form of the celebration text: full, abbreviated, truncated."""
    full, abbr = _CELEBRATION_TEXT.get(kind, (kind.upper(), kind.upper()))
    for text in (full, abbr):
        font = fit_font_size(text, max_h, max_w, bold=True)
        if font is not None:
            return text_img(TextSpec(text, font, bold=True), color)
    return truncate_to_fit(abbr, color, 7, max_w)


def _soccer_ball(frame: int, size: int) -> Image.Image:
    """White ball with a dark patch orbiting the centre (spin), bouncing."""
    d = max(7, min(size, 13))
    d = d if d % 2 else d - 1
    img = Image.new("RGB", (d, size), (0, 0, 0))
    headroom = size - d
    y0 = round(_BOUNCE_8THS[frame % 8] / 6 * headroom) if headroom > 0 else 0
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, y0, d - 1, y0 + d - 1], fill=_BALL_WHITE, outline=(120, 120, 120))
    c = d // 2
    # Three small pentagon patches orbiting the centre read as a spinning ball.
    r_orbit = max(1, d * 3 // 10)
    r_patch = max(1, d // 8)
    for k in range(3):
        angle = (frame % 8 / 8 + k / 3) * 2 * math.pi
        px_x = c + round(r_orbit * math.cos(angle))
        px_y = y0 + c + round(r_orbit * math.sin(angle))
        draw.ellipse(
            [px_x - r_patch, px_y - r_patch, px_x + r_patch, px_y + r_patch],
            fill=_BALL_DARK,
        )
    return img


def _football_ball(frame: int, size: int) -> Image.Image:
    """Brown ellipse with white laces, tumbling end over end."""
    s = max(9, size)
    s = s if s % 2 else s - 1
    ball = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ball)
    c = s // 2
    ry = max(2, s * 5 // 16)
    draw.ellipse([0, c - ry, s - 1, c + ry], fill=(*_FOOTBALL_BROWN, 255))
    lace_w = max(2, s // 4)
    draw.line([c - lace_w // 2, c, c + lace_w // 2, c], fill=(255, 255, 255, 255))
    for dx in range(-lace_w // 2, lace_w // 2 + 1, 2):
        draw.line([c + dx, c - 1, c + dx, c + 1], fill=(255, 255, 255, 255))
    rotated = ball.rotate(frame % 8 * 45, resample=Image.NEAREST)
    out = Image.new("RGB", (s, s), (0, 0, 0))
    out.paste(rotated.convert("RGB"), (0, 0), rotated.split()[3])
    return out


def _baseball_ball(frame: int, size: int) -> Image.Image:
    """White ball with red stitch arcs, rising out of the frame and looping."""
    d = max(7, min(size, 11))
    d = d if d % 2 else d - 1
    img = Image.new("RGB", (d, size), (0, 0, 0))
    headroom = size - d
    y0 = round((1 - frame % 8 / 7) * headroom) if headroom > 0 else 0
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, y0, d - 1, y0 + d - 1], fill=_BALL_WHITE, outline=(120, 120, 120))
    inset = max(1, d // 4)
    draw.arc([-inset, y0, inset * 2, y0 + d - 1], 300, 60, fill=_STITCH_RED)
    draw.arc([d - 1 - inset * 2, y0, d - 1 + inset, y0 + d - 1], 120, 240, fill=_STITCH_RED)
    return img


_SPRITES = {
    "soccer": _soccer_ball,
    "football": _football_ball,
    "baseball": _baseball_ball,
}


def celebration_sprite(sport: str, frame: int, size: int) -> Image.Image | None:
    """One animation frame of the sport's ball, sized to fit a size×size box."""
    draw_fn = _SPRITES.get(sport)
    if draw_fn is None or size < 7:
        return None
    return draw_fn(frame % CELEBRATION_ANIM_FRAMES, size)


_CELEB_GAP = 1
_MIN_SPRITE = 8


def celebration_img(view: GameView, max_h: int, max_w: int) -> Image.Image:
    """Centre-column celebration: animated sprite above the pulsing big text.

    The text's space is always reserved (blanked during the off pulse phase)
    so the layout never shifts; the sprite keeps animating through both
    phases so the card stays visibly alive. The sprite degrades first, then
    drops entirely, before the text gives up any size.
    """
    celeb = view.celebration
    assert celeb is not None
    color = celebration_color(view)
    text = celebration_text_img(celeb.kind, color, min(max_h, 15), max_w)

    sprite = None
    sprite_space = max_h - text.height - _CELEB_GAP
    if sprite_space >= _MIN_SPRITE:
        sprite = celebration_sprite(view.sport, celeb.anim_frame, min(sprite_space, 17))

    width = max(text.width, sprite.width if sprite is not None else 0, 1)
    height = text.height + (sprite.height + _CELEB_GAP if sprite is not None else 0)
    out = Image.new("RGB", (width, height), (0, 0, 0))
    y = 0
    if sprite is not None:
        out.paste(sprite, ((width - sprite.width) // 2, y))
        y += sprite.height + _CELEB_GAP
    if celeb.pulse_on:
        out.paste(text, ((width - text.width) // 2, y))
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
