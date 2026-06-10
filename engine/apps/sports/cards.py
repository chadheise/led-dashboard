"""Tiered card layouts for rendering one game at any slot size.

Every tier follows the same skeleton — *budget* regions, *build* measured
candidate elements, *degrade* explicitly when space runs out, then *place*
through ``Frame.place`` (which refuses to overflow). The returned boxes are
the audit trail the layout tests assert on: nothing overlaps, nothing is
clipped, and the score is always the most prominent element.

Tier map (w x h):

    w < 48          MINIMAL   two big scores (or abbrs pre-game), nothing else
    h < 48, w < 128 COMPACT   two `NAME score` rows + 9px footer
    h < 48, w >= 128 INLINE   [logo NAME SCORE] .. widget .. [SCORE NAME logo]
    h >= 48, w < 128 STACKED  two rows: [logo] name-block score + 12px footer
    h >= 48, w >= 128 WIDE    edge logos, city/name/SCORE blocks, centre widget
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from PIL import Image

from libraries.layout.library import (
    Frame,
    PlacedBox,
    Region,
    TextSpec,
    fit_font_size,
    measure,
    text_img,
)

from . import widgets
from .model import GameView, TeamView

_GAP = 2
_MARGIN = 1


class Tier(Enum):
    MINIMAL = auto()
    COMPACT = auto()
    INLINE = auto()
    STACKED = auto()
    WIDE = auto()


@dataclass(frozen=True)
class CardRender:
    image: Image.Image
    boxes: list[PlacedBox]


def select_tier(w: int, h: int) -> Tier:
    if w < 48:
        return Tier.MINIMAL
    if h < 48:
        return Tier.COMPACT if w < 128 else Tier.INLINE
    return Tier.STACKED if w < 128 else Tier.WIDE


def render_card(view: GameView, w: int, h: int) -> CardRender:
    frame = Frame(w, h)
    renderer = {
        Tier.MINIMAL: _render_minimal,
        Tier.COMPACT: _render_compact,
        Tier.INLINE: _render_inline,
        Tier.STACKED: _render_stacked,
        Tier.WIDE: _render_wide,
    }[select_tier(w, h)]
    renderer(frame, view)
    return CardRender(frame.image, frame.boxes)


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _scaled_logo(team: TeamView, max_h: int, max_w: int) -> Image.Image | None:
    """Team logo scaled to fit the budget, preserving aspect; never upscaled."""
    logo = team.logo
    if logo is None or max_h < 6 or max_w < 6:
        return None
    iw, ih = logo.size
    if iw <= max_w and ih <= max_h:
        return logo
    scale = min(max_w / iw, max_h / ih)
    return logo.resize(
        (max(1, round(iw * scale)), max(1, round(ih * scale))), Image.LANCZOS
    )


def _possessed(text: str, team: TeamView, side: str) -> str:
    """Append the football possession marker to a team's primary name line."""
    if not team.has_possession:
        return text
    return f"{text} <" if side == "away" else f"> {text}"


def _ranked_nickname(team: TeamView, side: str) -> str:
    if not team.nickname:
        return ""
    if team.rank is None:
        return team.nickname
    return (
        f"#{team.rank} {team.nickname}" if side == "away" else f"{team.nickname} #{team.rank}"
    )


def _shared_choice(
    away_candidates: list[TextSpec],
    home_candidates: list[TextSpec],
    away_max_w: int,
    home_max_w: int,
) -> tuple[TextSpec, TextSpec]:
    """Pick the first candidate index that fits *both* teams, so the two sides
    of a card always use the same form (mixed abbr/nickname looks broken)."""
    for away_spec, home_spec in zip(away_candidates, home_candidates):
        if not away_spec.text or not home_spec.text:
            continue
        if measure(away_spec)[0] <= away_max_w and measure(home_spec)[0] <= home_max_w:
            return away_spec, home_spec
    return away_candidates[-1], home_candidates[-1]


def _name_img(spec: TextSpec, color, max_w: int) -> Image.Image:
    img = text_img(spec, color)
    if img.width > max_w:
        img = widgets.truncate_to_fit(spec.text, color, spec.size, max_w)
    return img


def _min_name_w(team: TeamView) -> int:
    """Width the smallest acceptable name form needs — reserved before the
    score is fitted, so a wide score can never starve the team name out."""
    return measure(TextSpec(team.plain_abbr, 7))[0]


_MIN_LOGO_W = 10


_SCORE_MARGIN = 2  # breathing room above/below the big score digits


def _fit_score_and_logo(
    team: TeamView, row_w: int, row_h: int, logo_cap: int
) -> tuple[Image.Image | None, Image.Image | None]:
    """Budget one team row: score at its ideal size first, logo from what's left.

    The degradation order is explicit — the logo shrinks (and finally drops)
    before the score gives up any size, and the smallest name form is always
    reserved. Returns (logo, score_img), either of which may be None.
    """
    min_name = _min_name_w(team)
    if not team.score:
        return _scaled_logo(team, row_h, logo_cap), None

    score_h = max(5, row_h - _SCORE_MARGIN)
    ideal_font = fit_font_size(
        team.score, score_h, max(1, row_w - min_name - 2 * _GAP), bold=True, allow_large=True
    )
    ideal_w = measure(TextSpec(team.score, ideal_font, bold=True))[0] if ideal_font else 0

    logo_budget = row_w - ideal_w - min_name - 3 * _GAP
    logo = None
    if logo_budget >= _MIN_LOGO_W:
        logo = _scaled_logo(team, row_h, min(logo_budget, logo_cap))

    score_max_w = row_w - (logo.width + _GAP if logo is not None else 0) - min_name - 2 * _GAP
    return logo, _score_img_large(team, score_h, max(1, score_max_w))


def _score_img_large(team: TeamView, max_h: int, max_w: int) -> Image.Image:
    font = fit_font_size(team.score, max_h, max_w, bold=True, allow_large=True)
    if font is None:
        return widgets.truncate_to_fit(team.score, team.color, 7, max(1, max_w))
    return text_img(TextSpec(team.score, font, bold=True), team.color)


def _score_img(team: TeamView, max_h: int, max_w: int) -> Image.Image:
    """Largest score render that fits the budget (guaranteed, never clipped)."""
    font = fit_font_size(team.score, max_h, max_w, bold=True)
    if font is None:
        return widgets.truncate_to_fit(team.score, team.color, 7, max(1, max_w))
    return text_img(TextSpec(team.score, font, bold=True), team.color)


def _diamond_widget(view: GameView, size: int) -> Image.Image:
    situation = view.situation
    return widgets.diamond_img(
        bool(situation.get("onFirst")),
        bool(situation.get("onSecond")),
        bool(situation.get("onThird")),
        size,
    )


def _render_footer(
    frame: Frame,
    view: GameView,
    footer: Region,
    *,
    show_records: bool,
    diamond_in_footer: bool,
) -> None:
    font = 9 if footer.h >= 12 else 7
    region = footer.inset(2, 0)
    left_edge, right_edge = region.x, region.right

    if show_records:
        if view.away.record:
            rec = widgets.plain_status_img(view.away.record, 7, region.w // 4)
            box = frame.place("away.record", rec, region, anchor="lm", priority=3)
            left_edge = box.right + _GAP
        if view.home.record:
            rec = widgets.plain_status_img(view.home.record, 7, region.w // 4)
            box = frame.place("home.record", rec, region, anchor="rm", priority=3)
            right_edge = box.x - _GAP

    center = Region(left_edge, region.y, max(1, right_edge - left_edge), region.h)
    status = widgets.status_img(view, font, center.w, diamond_in_footer=diamond_in_footer)
    if status.height <= center.h and status.width <= center.w:
        frame.place("footer.status", status, center, anchor="mm", priority=2)


# ── MINIMAL: scores only ───────────────────────────────────────────────────────


def _render_minimal(frame: Frame, view: GameView) -> None:
    rows = frame.region.split_rows(2)
    for side, team, row in (("away", view.away, rows[0]), ("home", view.home, rows[1])):
        text = team.score or team.plain_abbr
        if not text:
            continue
        box_name = f"{side}.score" if team.score else f"{side}.abbr"
        size = fit_font_size(text, max(5, row.h - _SCORE_MARGIN), row.w - 2, bold=True)
        if size is None:
            img = widgets.truncate_to_fit(text, team.color, 7, row.w - 2)
        else:
            img = text_img(TextSpec(text, size, bold=True), team.color)
        frame.place(box_name, img, row, anchor="mm", priority=0)


# ── COMPACT: two rows + footer (short, narrow) ─────────────────────────────────


def _render_compact(frame: Frame, view: GameView) -> None:
    footer, content = frame.region.take_bottom(9)
    rows = [r.inset(2, 0) for r in content.split_rows(2)]

    # Scores first (priority 0): one shared font, right-aligned column.
    score_imgs: dict[str, Image.Image] = {}
    score_col = 0
    if view.state != "pre":
        longest = max((view.away.score, view.home.score), key=len)
        score_max_w = rows[0].w - max(_min_name_w(view.away), _min_name_w(view.home)) - _GAP
        score_font = fit_font_size(longest, rows[0].h, max(1, score_max_w), bold=True) or 7
        for side, team in (("away", view.away), ("home", view.home)):
            img = text_img(TextSpec(team.score, score_font, bold=True), team.color)
            score_imgs[side] = img
            score_col = max(score_col, img.width)

    name_w = [row.w - score_col - (_GAP if score_col else 0) for row in rows]
    name_max_h = min(
        score_imgs["away"].height if score_imgs else rows[0].h, rows[0].h
    )
    name_font = fit_font_size("Ag", name_max_h) or 7
    away_spec, home_spec = _shared_choice(
        [
            TextSpec(_possessed(view.away.nickname, view.away, "away"), name_font),
            TextSpec(_possessed(view.away.abbr, view.away, "away"), name_font),
            TextSpec(_possessed(view.away.plain_abbr, view.away, "away"), 7),
        ],
        [
            TextSpec(_possessed(view.home.nickname, view.home, "home"), name_font),
            TextSpec(_possessed(view.home.abbr, view.home, "home"), name_font),
            TextSpec(_possessed(view.home.plain_abbr, view.home, "home"), 7),
        ],
        name_w[0],
        name_w[1],
    )

    for i, (side, team, spec) in enumerate(
        (("away", view.away, away_spec), ("home", view.home, home_spec))
    ):
        row = rows[i]
        name_region, _ = row.take_left(name_w[i])
        frame.place(
            f"{side}.name",
            _name_img(spec, team.color, name_region.w),
            name_region,
            anchor="lm",
            priority=1,
        )
        if side in score_imgs:
            score_region, _ = row.take_right(score_col)
            frame.place(f"{side}.score", score_imgs[side], score_region, anchor="rm", priority=0)

    _render_footer(frame, view, footer, show_records=False, diamond_in_footer=True)


# ── INLINE: one row per game (short, wide) ─────────────────────────────────────


def _render_inline(frame: Frame, view: GameView) -> None:
    w = frame.image.width
    footer, content = frame.region.take_bottom(9)

    widget = None
    if view.is_baseball_live:
        widget = _diamond_widget(view, min(content.h - 2, 15))
    # Without a widget, keep a clear gutter so the two scores don't read as one.
    center_w = widget.width + 2 * (_GAP + 1) if widget is not None else _GAP * 4
    half_w = (w - center_w) // 2
    halves = {
        "away": Region(0, content.y, half_w, content.h).inset(1, 0),
        "home": Region(w - half_w, content.y, half_w, content.h).inset(1, 0),
    }

    if widget is not None:
        frame.place("widget.diamond", widget, content, anchor="mm", priority=2)

    # Score at ideal size first, logo from the remainder, name budget last.
    logos: dict[str, Image.Image | None] = {}
    score_imgs: dict[str, Image.Image] = {}
    for side, team in (("away", view.away), ("home", view.home)):
        logo, score_img = _fit_score_and_logo(
            team, halves[side].w, content.h, content.h * 3 // 2
        )
        logos[side] = logo
        if score_img is not None:
            score_imgs[side] = score_img

    def _name_budget(side: str) -> int:
        used = halves[side].w
        if logos[side] is not None:
            used -= logos[side].width + _GAP
        if side in score_imgs:
            used -= score_imgs[side].width + _GAP
        return max(1, used)

    # Two-row name block (abbr over nickname) when both sides fit one.
    sub_font = fit_font_size("Ag", content.h // 2) or 7
    two_rows = all(
        team.nickname
        and measure(TextSpec(team.nickname, sub_font))[0] <= _name_budget(side)
        and measure(TextSpec(team.abbr, sub_font))[0] <= _name_budget(side)
        for side, team in (("away", view.away), ("home", view.home))
    )

    name_font = fit_font_size("Ag", min(content.h, 12)) or 9
    away_spec, home_spec = _shared_choice(
        [
            TextSpec(_possessed(view.away.nickname, view.away, "away"), name_font),
            TextSpec(_possessed(view.away.abbr, view.away, "away"), name_font),
            TextSpec(_possessed(view.away.plain_abbr, view.away, "away"), 7),
        ],
        [
            TextSpec(_possessed(view.home.nickname, view.home, "home"), name_font),
            TextSpec(_possessed(view.home.abbr, view.home, "home"), name_font),
            TextSpec(_possessed(view.home.plain_abbr, view.home, "home"), 7),
        ],
        _name_budget("away"),
        _name_budget("home"),
    )
    single_specs = {"away": away_spec, "home": home_spec}

    for side, team in (("away", view.away), ("home", view.home)):
        region = halves[side]
        outer = "lm" if side == "away" else "rm"
        logo = logos[side]
        if logo is not None:
            box = frame.place(f"{side}.logo", logo, region, anchor=outer, priority=2)
            if side == "away":
                region = Region(box.right + _GAP, region.y, region.right - box.right - _GAP, region.h)
            else:
                region = Region(region.x, region.y, box.x - _GAP - region.x, region.h)

        # Score first (priority 0), anchored at the half's inner edge so the
        # two scores flank the centre; the name gets the exact remainder.
        if side in score_imgs:
            score_img = score_imgs[side]
            if score_img.width > region.w:  # degraded space — refit the score
                score_img = _score_img(team, region.h, region.w)
            if side == "away":
                score_region, region = region.take_right(score_img.width)
            else:
                score_region, region = region.take_left(score_img.width)
            frame.place(f"{side}.score", score_img, score_region, anchor="mm", priority=0)
            if side == "away":
                region, _ = region.take_left(max(0, region.w - _GAP))
            else:
                _, region = region.take_left(_GAP)

        if two_rows:
            top, bottom = region.take_top(region.h // 2)
            abbr_img = _name_img(TextSpec(team.abbr, sub_font), team.accent, region.w)
            nick_img = _name_img(
                TextSpec(_possessed(team.nickname, team, side), sub_font), team.color, region.w
            )
            frame.place(f"{side}.abbr", abbr_img, top, anchor=outer, priority=1)
            frame.place(f"{side}.name", nick_img, bottom, anchor=outer, priority=1)
        else:
            name_img = _name_img(single_specs[side], team.color, region.w)
            frame.place(f"{side}.name", name_img, region, anchor=outer, priority=1)

    _render_footer(frame, view, footer, show_records=w >= 128, diamond_in_footer=False)


# ── STACKED: two team rows + footer (tall, narrow) ─────────────────────────────


def _render_stacked(frame: Frame, view: GameView) -> None:
    w = frame.image.width
    footer, content = frame.region.take_bottom(12)
    rows = [r.inset(2, 1) for r in content.split_rows(2)]
    show_logo = w >= 64

    logos: dict[str, Image.Image | None] = {"away": None, "home": None}
    score_imgs: dict[str, Image.Image] = {}
    score_col = 0
    for i, (side, team) in enumerate((("away", view.away), ("home", view.home))):
        # Cap the logo at a third of the row so wide logos (flags) can't
        # squeeze the name and score out of a narrow card.
        logo_cap = min(rows[i].h * 3 // 2, rows[i].w // 3) if show_logo else 0
        logo, score_img = _fit_score_and_logo(team, rows[i].w, rows[i].h, logo_cap)
        logos[side] = logo if show_logo else None
        if score_img is not None:
            score_imgs[side] = score_img
            score_col = max(score_col, score_img.width)

    def _name_budget(i: int, side: str) -> int:
        used = rows[i].w - score_col - (_GAP if score_col else 0)
        if logos[side] is not None:
            used -= logos[side].width + _GAP
        return max(1, used)

    sub_font = fit_font_size("Ag", rows[0].h // 2) or 7
    two_rows = all(
        team.nickname
        and measure(TextSpec(team.nickname, sub_font))[0] <= _name_budget(i, side)
        and measure(TextSpec(team.abbr, sub_font))[0] <= _name_budget(i, side)
        for i, (side, team) in enumerate((("away", view.away), ("home", view.home)))
    )
    name_font = fit_font_size("Ag", min(rows[0].h, 15)) or 9
    away_spec, home_spec = _shared_choice(
        [
            TextSpec(_possessed(view.away.nickname, view.away, "away"), name_font),
            TextSpec(_possessed(view.away.abbr, view.away, "away"), name_font),
            TextSpec(_possessed(view.away.plain_abbr, view.away, "away"), 7),
        ],
        [
            TextSpec(_possessed(view.home.nickname, view.home, "home"), name_font),
            TextSpec(_possessed(view.home.abbr, view.home, "home"), name_font),
            TextSpec(_possessed(view.home.plain_abbr, view.home, "home"), 7),
        ],
        _name_budget(0, "away"),
        _name_budget(1, "home"),
    )
    single_specs = {"away": away_spec, "home": home_spec}

    for i, (side, team) in enumerate((("away", view.away), ("home", view.home))):
        region = rows[i]
        logo = logos[side]
        if logo is not None:
            box = frame.place(f"{side}.logo", logo, region, anchor="lm", priority=2)
            region = Region(box.right + _GAP, region.y, region.right - box.right - _GAP, region.h)

        if side in score_imgs:
            score_img = score_imgs[side]
            col = min(score_col, region.w)
            if score_img.width > col:  # degraded space — refit the score
                score_img = _score_img(team, region.h, col)
            score_region, region = region.take_right(col)
            frame.place(f"{side}.score", score_img, score_region, anchor="rm", priority=0)
            region, _ = region.take_left(max(0, region.w - _GAP))

        if two_rows:
            top, bottom = region.take_top(region.h // 2)
            frame.place(
                f"{side}.abbr",
                _name_img(TextSpec(team.abbr, sub_font), team.accent, region.w),
                top, anchor="lm", priority=1,
            )
            frame.place(
                f"{side}.name",
                _name_img(TextSpec(_possessed(team.nickname, team, side), sub_font), team.color, region.w),
                bottom, anchor="lm", priority=1,
            )
        else:
            frame.place(
                f"{side}.name",
                _name_img(single_specs[side], team.color, region.w),
                region, anchor="lm", priority=1,
            )

    _render_footer(frame, view, footer, show_records=False, diamond_in_footer=True)


# ── WIDE: full layout (tall, wide) ─────────────────────────────────────────────


def _render_wide(frame: Frame, view: GameView) -> None:
    w = frame.image.width
    footer, content = frame.region.take_bottom(12)
    content = content.inset(0, 1)

    # Centre widget reserves its column before the halves are budgeted.
    widget: Image.Image | None = None
    widget_name = ""
    if view.is_baseball_live:
        widget = _diamond_widget(view, min(content.h - 4, 31))
        widget_name = "widget.diamond"
    elif view.is_soccer and view.state in ("in", "post"):
        widget = widgets.goal_list_img(view, content.h, w // 3)
        widget_name = "widget.goals"
    center_w = widget.width + 2 * (_GAP + 2) if widget is not None else _GAP * 3
    half_w = (w - center_w) // 2

    if widget is not None:
        anchor = "mm" if view.is_baseball_live else "mb"
        frame.place(widget_name, widget, content, anchor=anchor, priority=2)

    halves = {
        "away": Region(0, content.y, half_w, content.h),
        "home": Region(w - half_w, content.y, half_w, content.h),
    }

    # Logos at the outer edges; text budget is the remainder of each half.
    logos: dict[str, Image.Image | None] = {}
    text_regions: dict[str, Region] = {}
    for side, team in (("away", view.away), ("home", view.home)):
        region = halves[side].inset(1, 0)
        logo = _scaled_logo(team, region.h, max(12, region.w // 2))
        logos[side] = logo
        if logo is not None:
            outer = "lm" if side == "away" else "rm"
            box = frame.place(f"{side}.logo", logo, region, anchor=outer, priority=2)
            if side == "away":
                region = Region(box.right + _GAP, region.y, region.right - box.right - _GAP, region.h)
            else:
                region = Region(region.x, region.y, box.x - _GAP - region.x, region.h)
        text_regions[side] = region

    name_font = 12
    line_h = measure(TextSpec("Ag", name_font))[1]

    def _city_text(team: TeamView) -> str:
        # National teams repeat the country as both location and nickname;
        # show the abbreviation on the top line instead.
        if team.location and team.location.lower() == team.nickname.lower():
            return team.abbr
        return team.location

    have_scores = view.state != "pre"
    score_min_h = 14
    three_lines = all(
        _city_text(team)
        and team.nickname
        and measure(TextSpec(_city_text(team), name_font))[0] <= text_regions[side].w
        and measure(TextSpec(_ranked_nickname(team, side) or team.nickname, name_font))[0]
        <= text_regions[side].w
        for side, team in (("away", view.away), ("home", view.home))
    ) and content.h - 2 * line_h - 2 * _GAP >= (score_min_h if have_scores else 0)

    if not three_lines:
        away_spec, home_spec = _shared_choice(
            [
                TextSpec(_possessed(_ranked_nickname(view.away, "away"), view.away, "away"), name_font),
                TextSpec(_possessed(view.away.abbr, view.away, "away"), name_font),
                TextSpec(_possessed(view.away.plain_abbr, view.away, "away"), name_font),
                TextSpec(_possessed(view.away.plain_abbr, view.away, "away"), 9),
            ],
            [
                TextSpec(_possessed(_ranked_nickname(view.home, "home"), view.home, "home"), name_font),
                TextSpec(_possessed(view.home.abbr, view.home, "home"), name_font),
                TextSpec(_possessed(view.home.plain_abbr, view.home, "home"), name_font),
                TextSpec(_possessed(view.home.plain_abbr, view.home, "home"), 9),
            ],
            text_regions["away"].w,
            text_regions["home"].w,
        )
        single_specs = {"away": away_spec, "home": home_spec}

    # Build every text line first, so both sides share one row geometry and
    # one score font — independent fits would misalign the rows and can size
    # the two scores differently.
    # Without scores the card is mostly empty, so pre-game gets a larger abbr,
    # with the nickname underneath when it fits on both sides.
    pre_block = not have_scores and not three_lines
    pre_nicknames = pre_block and all(
        team.nickname and measure(TextSpec(team.nickname, 9))[0] <= text_regions[side].w
        for side, team in (("away", view.away), ("home", view.home))
    )

    lines: dict[str, list[tuple[str, Image.Image]]] = {}
    for side, team in (("away", view.away), ("home", view.home)):
        region = text_regions[side]
        if three_lines:
            city_img = _name_img(TextSpec(_city_text(team), name_font), team.accent, region.w)
            nick_text = _possessed(_ranked_nickname(team, side), team, side)
            nick_img = _name_img(TextSpec(nick_text, name_font), team.color, region.w)
            lines[side] = [(f"{side}.city", city_img), (f"{side}.name", nick_img)]
        elif pre_block:
            abbr_img = _name_img(TextSpec(team.abbr, 15), team.color, region.w)
            lines[side] = [(f"{side}.name", abbr_img)]
            if pre_nicknames:
                nick_img = _name_img(TextSpec(team.nickname, 9), team.accent, region.w)
                lines[side].append((f"{side}.nickname", nick_img))
        else:
            lines[side] = [(f"{side}.name", _name_img(single_specs[side], team.color, region.w))]

    n_lines = max(len(lines["away"]), len(lines["home"]))
    row_heights = [
        max(side_lines[i][1].height for side_lines in lines.values() if i < len(side_lines))
        for i in range(n_lines)
    ]
    name_h = sum(row_heights) + (n_lines - 1) * _GAP

    score_imgs: dict[str, Image.Image] = {}
    score_row_h = 0
    if have_scores:
        score_h = max(score_min_h - 4, content.h - name_h - _GAP - _SCORE_MARGIN)
        fonts = [
            fit_font_size(team.score, score_h, text_regions[side].w, bold=True, allow_large=True)
            for side, team in (("away", view.away), ("home", view.home))
        ]
        if all(f is not None for f in fonts):
            font = min(fonts)  # type: ignore[type-var]
            for side, team in (("away", view.away), ("home", view.home)):
                score_imgs[side] = text_img(TextSpec(team.score, font, bold=True), team.color)
            score_row_h = max(img.height for img in score_imgs.values())

    block_h = name_h + (_GAP + score_row_h if score_imgs else 0)
    y0 = content.y + max(0, (content.h - block_h) // 2)

    for side in ("away", "home"):
        region = text_regions[side]
        align = "l" if side == "away" else "r"
        y = y0
        for (box_name, img), row_h in zip(lines[side], row_heights):
            frame.place(box_name, img, Region(region.x, y, region.w, row_h),
                        anchor=f"{align}m", priority=1)
            y += row_h + _GAP
        if side in score_imgs:
            score_region = Region(region.x, y, region.w, max(1, region.bottom - y))
            frame.place(f"{side}.score", score_imgs[side], score_region,
                        anchor=f"{align}t", priority=0)

    _render_footer(frame, view, footer, show_records=True, diamond_in_footer=False)
