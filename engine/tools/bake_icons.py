#!/usr/bin/env python3
"""Bake the committed SVG icon sources into the PNG assets the engine ships.

Two icon families are produced:

* **Weather** — the free amCharts animated SVG weather icons (CSS-keyframe
  animations on a small set of ``am-weather-*`` classes). Each icon's
  animation is evaluated in Python (interpolating ``transform``,
  ``stroke-dashoffset``/``-dasharray``, ``opacity`` and ``fill`` per frame),
  rasterized with cairosvg, and packed into a horizontal sprite strip at
  ``libraries/open_meteo/icons/<name>.png`` plus a shared ``meta.json``.

* **Countdown** — Twemoji holiday glyphs, rasterized to static 64x64 PNGs at
  ``libraries/holidays/icons/<icon_id>.png``.

Frames are rendered oversized, cropped to the union alpha bounding box of the
whole animation (the sources carry generous padding that would waste pixels
on an LED panel), squared, and downscaled to the shipped size.

Run from the ``engine`` directory: ``python tools/bake_icons.py``.
Requires ``cairosvg`` (dev-only; see requirements-dev.txt). Uses only the
committed sources under ``tools/icon_sources/`` — no network access.
"""

from __future__ import annotations

import io
import json
import math
import re
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import cairosvg
from PIL import Image

TOOLS_DIR = Path(__file__).parent
ENGINE_DIR = TOOLS_DIR.parent
AMCHARTS_DIR = TOOLS_DIR / "icon_sources" / "amcharts"
TWEMOJI_DIR = TOOLS_DIR / "icon_sources" / "twemoji"
WEATHER_OUT = ENGINE_DIR / "libraries" / "open_meteo" / "icons"
HOLIDAY_OUT = ENGINE_DIR / "libraries" / "holidays" / "icons"

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

SPRITE_SIZE = 64  # shipped frame size, px
RENDER_SIZE = 256  # oversampled raster size before crop+downscale
FPS = 10
CROP_PAD = 0.02  # padding around the union content box, as a fraction

# Per-icon animation-duration overrides (selector -> seconds). The source
# durations are mutually incommensurate (e.g. 7s clouds with 8s rain would
# only loop every 56s); nudging one duration per icon yields a short, clean
# loop with no visible change in character.
DURATION_OVERRIDES: dict[str, dict[str, float]] = {
    "day": {".am-weather-sun-shiny line": 2.25},  # 9s/4
    "cloudy": {".am-weather-cloud-1": 6.0},
    "rainy-6": {".am-weather-cloud-1": 8.0},
    "thunder": {".am-weather-stroke": 7.0 / 6.0},
}

_NAMED_COLORS = {"orange": (255, 165, 0), "white": (255, 255, 255), "black": (0, 0, 0)}


# ── CSS parsing ─────────────────────────────────────────────────────────────


def _strip_vendor_prefixes(css: str) -> str:
    return re.sub(r"\s*-(?:webkit|moz|ms|o)-[^;{}]+;", "", css)


def _parse_props(body: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for decl in body.split(";"):
        if ":" in decl:
            key, value = decl.split(":", 1)
            props[key.strip()] = value.strip()
    return props


def parse_css(svg_text: str) -> tuple[dict[str, list[tuple[float, dict[str, str]]]], dict[str, dict[str, str]]]:
    """Extract (keyframes, rules) from the SVG's embedded stylesheet.

    keyframes: name -> sorted [(offset 0..1, {prop: value})]
    rules: selector -> merged {prop: value} (later rules win, as in CSS)
    """
    css = "\n".join(re.findall(r"<!\[CDATA\[(.*?)\]\]>", svg_text, re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = _strip_vendor_prefixes(css)

    keyframes: dict[str, list[tuple[float, dict[str, str]]]] = {}
    for name, body in re.findall(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", css):
        stops: list[tuple[float, dict[str, str]]] = []
        for offsets, decls in re.findall(r"([\d.%,\s]+)\{([^{}]*)\}", body):
            for off in offsets.split(","):
                stops.append((float(off.strip().rstrip("%")) / 100.0, _parse_props(decls)))
        keyframes[name] = sorted(stops, key=lambda s: s[0])

    rules: dict[str, dict[str, str]] = {}
    css_no_kf = re.sub(r"@keyframes\s+[\w-]+\s*\{(?:[^{}]*\{[^{}]*\})*\s*\}", "", css)
    for selector, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css_no_kf):
        rules.setdefault(selector.strip(), {}).update(_parse_props(body))
    return keyframes, rules


# ── Value interpolation ─────────────────────────────────────────────────────


def _ease_in_out(u: float) -> float:
    """CSS ease-in-out: cubic-bezier(0.42, 0, 0.58, 1), solved for x=u."""
    if u <= 0.0 or u >= 1.0:
        return max(0.0, min(1.0, u))
    # x(t) and y(t) for the bezier; invert x numerically (monotonic in t).
    def bez(p1: float, p2: float, t: float) -> float:
        return 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3

    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if bez(0.42, 0.58, mid) < u:
            lo = mid
        else:
            hi = mid
    return bez(0.0, 1.0, (lo + hi) / 2)


_TRANSFORM_FN = re.compile(r"([\w-]+)\(([^)]*)\)")


def _parse_transform(value: str) -> list[tuple[str, list[float]]]:
    """Normalize a CSS transform list to [(fn, args)] with translate/rotate only."""
    out: list[tuple[str, list[float]]] = []
    for fn, raw_args in _TRANSFORM_FN.findall(value):
        args = [float(re.sub(r"(px|deg)$", "", a.strip())) for a in raw_args.replace(",", " ").split()]
        if fn == "translateX":
            out.append(("translate", [args[0], 0.0]))
        elif fn == "translateY":
            out.append(("translate", [0.0, args[0]]))
        elif fn == "translate":
            out.append(("translate", args if len(args) == 2 else [args[0], 0.0]))
        elif fn == "rotate":
            out.append(("rotate", [args[0]]))
        else:
            raise ValueError(f"unsupported transform function: {fn}")
    return out


def _lerp_transform(a: str, b: str, u: float) -> str:
    fa, fb = _parse_transform(a), _parse_transform(b)
    if [f for f, _ in fa] != [f for f, _ in fb]:
        raise ValueError(f"transform lists differ: {a!r} vs {b!r}")
    parts = []
    for (fn, args_a), (_, args_b) in zip(fa, fb):
        args = [x + (y - x) * u for x, y in zip(args_a, args_b)]
        parts.append(f"{fn}({','.join(f'{v:.4f}' for v in args)})")
    return " ".join(parts)


def _parse_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lower()
    if value in _NAMED_COLORS:
        return _NAMED_COLORS[value]
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    raise ValueError(f"unsupported color: {value}")


def _lerp_value(prop: str, a: str, b: str, u: float) -> str:
    if prop == "transform":
        return _lerp_transform(a, b, u)
    if prop == "fill":
        ca, cb = _parse_color(a), _parse_color(b)
        return "#%02x%02x%02x" % tuple(round(x + (y - x) * u) for x, y in zip(ca, cb))
    nums_a = [float(re.sub(r"px$", "", n)) for n in a.replace(",", " ").split()]
    nums_b = [float(re.sub(r"px$", "", n)) for n in b.replace(",", " ").split()]
    return " ".join(f"{x + (y - x) * u:.4f}" for x, y in zip(nums_a, nums_b))


# ── Animation evaluation ────────────────────────────────────────────────────


class ElementAnimation:
    """One CSS animation bound to one element: evaluates style at time t."""

    def __init__(
        self,
        stops: list[tuple[float, dict[str, str]]],
        duration: float,
        delay: float,
        timing: str,
        base_style: dict[str, str],
    ) -> None:
        self.duration = duration
        self.delay = delay
        self.ease = _ease_in_out if timing == "ease-in-out" else (lambda u: u)
        # Per-property stop lists; properties missing at 0%/100% fall back to
        # the element's base (un-animated) value, as CSS specifies.
        props = {p for _, decls in stops for p in decls}
        self.tracks: dict[str, list[tuple[float, str]]] = {}
        for prop in props:
            track = [(off, decls[prop]) for off, decls in stops if prop in decls]
            base = base_style.get(prop)
            if base is None:
                base = {"opacity": "1", "transform": track[0][1], "stroke-dashoffset": "0"}.get(prop)
            if base is not None:
                if track[0][0] > 0.0:
                    track.insert(0, (0.0, base))
                if track[-1][0] < 1.0:
                    track.append((1.0, base))
            self.tracks[prop] = track

    def style_at(self, t: float) -> dict[str, str]:
        progress = ((t - self.delay) % self.duration) / self.duration
        out: dict[str, str] = {}
        for prop, track in self.tracks.items():
            if len(track) == 1:
                out[prop] = track[0][1]
                continue
            for (off0, val0), (off1, val1) in zip(track, track[1:]):
                if progress <= off1 or (off1, val1) == track[-1]:
                    span = off1 - off0
                    u = 0.0 if span <= 0 else max(0.0, min(1.0, (progress - off0) / span))
                    out[prop] = _lerp_value(prop, val0, val1, self.ease(u))
                    break
        return out


def _classes(el: ET.Element) -> list[str]:
    return el.get("class", "").split()


def _match_elements(root: ET.Element, selector: str) -> list[ET.Element]:
    """Resolve the two selector shapes the icon set uses: `.cls` and `.cls tag`."""
    parts = selector.split()
    cls = parts[0].lstrip(".")
    hosts = [el for el in root.iter() if cls in _classes(el)]
    if len(parts) == 1:
        return hosts
    tag = f"{{{SVG_NS}}}{parts[1]}"
    return [d for host in hosts for d in host.iter(tag) if d is not host]


def _rule_for_element(el: ET.Element, rules: dict[str, dict[str, str]]) -> dict[str, str]:
    """Merge all single-class rules that apply to `el`, in stylesheet order."""
    merged: dict[str, str] = {}
    for selector, props in rules.items():
        if " " not in selector and selector.lstrip(".") in _classes(el):
            merged.update(props)
    return merged


def build_animations(
    root: ET.Element,
    keyframes: dict[str, list[tuple[float, dict[str, str]]]],
    rules: dict[str, dict[str, str]],
    overrides: dict[str, float],
) -> list[tuple[ET.Element, ElementAnimation]]:
    bound: dict[int, tuple[ET.Element, ElementAnimation]] = {}
    for selector, props in rules.items():
        name = props.get("animation-name")
        if not name or name not in keyframes:
            continue
        if props.get("animation-iteration-count", "infinite") != "infinite":
            # One-shot fades (the night-sky stars) have no steady-state motion:
            # with the default fill-mode they revert to base style, so a looping
            # sprite just renders them un-animated.
            continue
        for el in _match_elements(root, selector):
            style = _rule_for_element(el, rules) if " " not in selector else dict(props)
            duration = overrides.get(selector, float(style["animation-duration"].rstrip("s")))
            delay = float(style.get("animation-delay", "0s").rstrip("s"))
            timing = style.get("animation-timing-function", "linear")
            base = {k: el.get(k) for k in ("transform", "opacity", "fill", "stroke-dasharray", "stroke-dashoffset")}
            base_style = {k: v for k, v in base.items() if v is not None}
            anim = ElementAnimation(keyframes[name], duration, delay, timing, base_style)
            origin = style.get("transform-origin")
            if origin is not None and "transform" in anim.tracks:
                ox, oy = [float(v.rstrip("px")) for v in origin.split()[:2]]
                anim.origin = (ox, oy)  # type: ignore[attr-defined]
            bound[id(el)] = (el, anim)
    return list(bound.values())


def _apply_style(el: ET.Element, style: dict[str, str], anim: ElementAnimation) -> None:
    for prop, value in style.items():
        if prop == "transform":
            origin = getattr(anim, "origin", None)
            if origin is not None:
                value = f"translate({origin[0]},{origin[1]}) {value} translate({-origin[0]},{-origin[1]})"
            el.set("transform", value)
        else:
            el.set(prop, value)


# ── Rendering ───────────────────────────────────────────────────────────────


def _prepare_tree(svg_text: str) -> ET.ElementTree:
    """Parse the SVG and drop the stylesheet, filters, and filter references."""
    tree = ET.ElementTree(ET.fromstring(svg_text))
    root = tree.getroot()
    for parent in root.iter():
        for child in list(parent):
            if child.tag in (f"{{{SVG_NS}}}style", f"{{{SVG_NS}}}filter"):
                parent.remove(child)
    for el in root.iter():
        if el.get("filter") is not None:
            del el.attrib["filter"]
    return tree


def _render_tree(tree: ET.ElementTree) -> Image.Image:
    data = ET.tostring(tree.getroot(), encoding="unicode")
    png = cairosvg.svg2png(bytestring=data.encode(), output_width=RENDER_SIZE, output_height=RENDER_SIZE)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _loop_duration(anims: list[tuple[ET.Element, ElementAnimation]]) -> float:
    """The least common multiple of all animation periods, in seconds."""
    periods = [Fraction(anim.duration).limit_denominator(1000) for _, anim in anims]
    if not periods:
        return 1.0
    lcm = periods[0]
    for p in periods[1:]:
        # lcm of fractions in lowest terms: lcm(numerators) / gcd(denominators)
        lcm = Fraction(math.lcm(lcm.numerator, p.numerator), math.gcd(lcm.denominator, p.denominator))
    return float(lcm)


def _union_bbox(frames: list[Image.Image]) -> tuple[int, int, int, int]:
    box = None
    for frame in frames:
        b = frame.getchannel("A").getbbox()
        if b is None:
            continue
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return box or (0, 0, frames[0].width, frames[0].height)


def _square_crop(frames: list[Image.Image]) -> list[Image.Image]:
    """Crop all frames identically: union content box, padded, squared."""
    left, top, right, bottom = _union_bbox(frames)
    pad = round(frames[0].width * CROP_PAD)
    left, top = left - pad, top - pad
    right, bottom = right + pad, bottom + pad
    side = max(right - left, bottom - top)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    box = (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))
    return [f.crop(box) for f in frames]


def bake_weather_icon(path: Path) -> tuple[Image.Image, int]:
    """Render one animated icon into a horizontal sprite strip."""
    svg_text = path.read_text(encoding="utf-8")
    keyframes, rules = parse_css(svg_text)
    overrides = DURATION_OVERRIDES.get(path.stem, {})
    tree = _prepare_tree(svg_text)
    anims = build_animations(tree.getroot(), keyframes, rules, overrides)

    loop = _loop_duration(anims)
    n_frames = max(1, round(loop * FPS))
    frames = []
    for i in range(n_frames):
        t = i / FPS
        for el, anim in anims:
            _apply_style(el, anim.style_at(t), anim)
        frames.append(_render_tree(tree))

    frames = [f.resize((SPRITE_SIZE, SPRITE_SIZE), Image.LANCZOS) for f in _square_crop(frames)]
    strip = Image.new("RGBA", (SPRITE_SIZE * n_frames, SPRITE_SIZE))
    for i, frame in enumerate(frames):
        strip.paste(frame, (i * SPRITE_SIZE, 0))
    return strip, n_frames


def bake_weather() -> None:
    WEATHER_OUT.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"fps": FPS, "frame_size": SPRITE_SIZE, "icons": {}}
    for path in sorted(AMCHARTS_DIR.glob("*.svg")):
        strip, n_frames = bake_weather_icon(path)
        strip.save(WEATHER_OUT / f"{path.stem}.png", optimize=True)
        meta["icons"][path.stem] = {"frames": n_frames}  # type: ignore[index]
        print(f"  {path.stem}: {n_frames} frames")
    (WEATHER_OUT / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def bake_holidays() -> None:
    HOLIDAY_OUT.mkdir(parents=True, exist_ok=True)
    for path in sorted(TWEMOJI_DIR.glob("*.svg")):
        png = cairosvg.svg2png(url=str(path), output_width=RENDER_SIZE, output_height=RENDER_SIZE)
        frame = Image.open(io.BytesIO(png)).convert("RGBA")
        frame = _square_crop([frame])[0].resize((SPRITE_SIZE, SPRITE_SIZE), Image.LANCZOS)
        frame.save(HOLIDAY_OUT / f"{path.stem}.png", optimize=True)
        print(f"  {path.stem}")


if __name__ == "__main__":
    print("Baking weather icons (amCharts):")
    bake_weather()
    print("Baking holiday icons (Twemoji):")
    bake_holidays()
