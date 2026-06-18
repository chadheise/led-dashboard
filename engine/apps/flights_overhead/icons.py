"""Aircraft category fallback icons from Material Design Icons, Tabler Icons, and Font Awesome.

Sources (all open-source, permissive licenses):
  - Material Design Icons (Apache 2.0)  https://pictogrammers.com/library/mdi/
  - Tabler Icons (MIT)                  https://tabler.io/icons
  - Font Awesome Free (CC BY 4.0)       https://fontawesome.com/license/free
Icons used: fa:plane, fa:jet-fighter, fa:helicopter, mdi:airballoon,
            mdi:parachute, mdi:kite, mdi:drone, mdi:rocket-launch, mdi:car,
            mdi:alert-circle, mdi:help-circle, tabler:plane (filled)
"""
from __future__ import annotations

from io import BytesIO

import cairosvg
from PIL import Image

_COLOR = "#6482A0"  # blue-gray

# Each entry: (viewBox, path_d)
_ICONS: dict[str, tuple[str, str]] = {
    # fa:plane (Font Awesome Free, CC BY 4.0) — side-view commercial airliner
    "airplane_jet": (
        "0 0 576 512",
        "M482.3 192c34.2 0 93.7 29 93.7 64c0 36-59.5 64-93.7 64l-116.6 0"
        "L265.2 495.9c-5.7 10-16.3 16.1-27.8 16.1l-56.2 0"
        "c-10.6 0-18.3-10.2-15.4-20.4l49-171.6L112 320 68.8 377.6"
        "c-3 4-7.8 6.4-12.8 6.4l-42 0c-7.8 0-14-6.3-14-14"
        "c0-1.3 .2-2.6 .5-3.9L32 256 .5 145.9c-.4-1.3-.5-2.6-.5-3.9"
        "c0-7.8 6.3-14 14-14l42 0c5 0 9.8 2.4 12.8 6.4L112 192l102.9 0"
        "-49-171.6C162.9 10.2 170.6 0 181.2 0l56.2 0"
        "c11.5 0 22.1 6.2 27.8 16.1L365.7 192l116.6 0z",
    ),
    # tabler:plane (filled, MIT) — side view, horizontal; clearly a smaller aircraft
    "airplane_small": (
        "0 0 24 24",
        "M12.868 2.504l3.712 6.496h3.42a3 3 0 0 1 0 6h-3.42l-3.712 6.496"
        "a1 1 0 0 1 -.868 .504h-3a1 1 0 0 1 -.962 -1.275l1.636 -5.725h-2.26"
        "l-1.707 1.707a1 1 0 0 1 -.707 .293h-3a1 1 0 0 1 -.894 -1.447"
        "l1.776 -3.553l-1.776 -3.553a1 1 0 0 1 .894 -1.447h3"
        "a1 1 0 0 1 .707 .293l1.707 1.707h2.26l-1.636 -5.725"
        "a1 1 0 0 1 .962 -1.275h3a1 1 0 0 1 .868 .504",
    ),
    # fa:jet-fighter (Font Awesome Free, CC BY 4.0) — side-view fighter jet
    "airplane_hp": (
        "0 0 640 512",
        "M160 24c0-13.3 10.7-24 24-24L296 0c13.3 0 24 10.7 24 24s-10.7 24-24 24"
        "l-16 0L384 192l116.4 0c7.7 0 15.3 1.4 22.5 4.1L625 234.4"
        "c9 3.4 15 12 15 21.6s-6 18.2-15 21.6L522.9 315.9"
        "c-7.2 2.7-14.8 4.1-22.5 4.1L384 320 280 464l16 0"
        "c13.3 0 24 10.7 24 24s-10.7 24-24 24l-112 0"
        "c-13.3 0-24-10.7-24-24s10.7-24 24-24l8 0 0-144-32 0"
        "-54.6 54.6c-6 6-14.1 9.4-22.6 9.4L64 384"
        "c-17.7 0-32-14.3-32-32l0-64c-17.7 0-32-14.3-32-32s14.3-32 32-32"
        "l0-64c0-17.7 14.3-32 32-32l18.7 0c8.5 0 16.6 3.4 22.6 9.4"
        "L160 192l32 0 0-144-8 0c-13.3 0-24-10.7-24-24z"
        "M80 240c-8.8 0-16 7.2-16 16s7.2 16 16 16l64 0"
        "c8.8 0 16-7.2 16-16s-7.2-16-16-16l-64 0z",
    ),
    # fa:helicopter (Font Awesome Free, CC BY 4.0) — side-view helicopter
    "helicopter": (
        "0 0 640 512",
        "M128 32c0-17.7 14.3-32 32-32L544 0c17.7 0 32 14.3 32 32s-14.3 32-32 32"
        "L384 64l0 64 32 0c88.4 0 160 71.6 160 160l0 64c0 17.7-14.3 32-32 32"
        "l-160 0-64 0c-20.1 0-39.1-9.5-51.2-25.6l-71.4-95.2"
        "c-3.5-4.7-8.3-8.3-13.7-10.5L47.2 198.1c-9.5-3.8-16.7-12-19.2-22"
        "L5 83.9C2.4 73.8 10.1 64 20.5 64L48 64c10.1 0 19.6 4.7 25.6 12.8"
        "L112 128l208 0 0-64L160 64c-17.7 0-32-14.3-32-32z"
        "M384 320l128 0 0-32c0-53-43-96-96-96l-32 0 0 128z"
        "M630.6 425.4c12.5 12.5 12.5 32.8 0 45.3l-3.9 3.9"
        "c-24 24-56.6 37.5-90.5 37.5L256 512c-17.7 0-32-14.3-32-32"
        "s14.3-32 32-32l280.2 0c17 0 33.3-6.7 45.3-18.7l3.9-3.9"
        "c12.5-12.5 32.8-12.5 45.3 0z",
    ),
    # mdi:kite — gliders, sailplanes, ultralights, hang-gliders
    "kite": (
        "0 0 24 24",
        "M13.69 3.46C13.35 3.15 12.96 3 12.5 3C12.05 3 11.66 3.15 11.33 3.46"
        "L5.54 9.08C5.23 9.38 5.06 9.75 5 10.2C5 10.64 5.08 11.04 5.33 11.4"
        "L11.45 19.83C11.2 20.36 10.75 20.62 10.09 20.62C9.29 20.62 8.79 20.25"
        " 8.6 19.5C8.4 18.84 8 18.27 7.38 17.8C6.76 17.34 6.1 17.1 5.41 17.1"
        "C4.36 17.1 3.5 17.5 2.85 18.3L4.21 19.42C4.5 19.03 4.92 18.84 5.41 18.84"
        "C6.21 18.84 6.71 19.21 6.9 19.95C7.09 20.62 7.5 21.19 8.12 21.67"
        "C8.74 22.15 9.4 22.4 10.09 22.4C11.33 22.4 12.28 21.83 12.94 20.7"
        "L19.68 11.39C19.93 11.04 20.03 10.64 20 10.2"
        "C19.95 9.75 19.77 9.38 19.47 9.08L13.69 3.46Z",
    ),
    # mdi:airballoon — lighter-than-air (hot air balloon, blimp)
    "balloon": (
        "0 0 24 24",
        "M11,23A2,2 0 0,1 9,21V19H15V21A2,2 0 0,1 13,23H11"
        "M12,1C12.71,1 13.39,1.09 14.05,1.26C15.22,2.83 16,5.71 16,9"
        "C16,11.28 15.62,13.37 15,16A2,2 0 0,1 13,18H11A2,2 0 0,1 9,16"
        "C8.38,13.37 8,11.28 8,9C8,5.71 8.78,2.83 9.95,1.26"
        "C10.61,1.09 11.29,1 12,1"
        "M20,8C20,11.18 18.15,15.92 15.46,17.21C16.41,15.39 17,11.83 17,9"
        "C17,6.17 16.41,3.61 15.46,1.79C18.15,3.08 20,4.82 20,8"
        "M4,8C4,4.82 5.85,3.08 8.54,1.79C7.59,3.61 7,6.17 7,9"
        "C7,11.83 7.59,15.39 8.54,17.21C5.85,15.92 4,11.18 4,8Z",
    ),
    # mdi:parachute — parachutist / skydiver
    "parachute": (
        "0 0 24 24",
        "M21.2,10.95L12,23L2.78,10.96L2.87,10.88C3.08,10.67 3.33,10.5 3.58,10.36"
        "L10.73,19.69L8.58,13L9.24,11.81L12,20.38L14.73,11.8L15.4,13"
        "L13.27,19.69L20.41,10.35C20.66,10.5 20.9,10.64 21.1,10.85L21.2,10.95"
        "M5,9C6.5,9 7.81,9.86 8.5,11.1C9.17,9.86 10.47,9 12,9"
        "C13.5,9 14.8,9.85 15.5,11.09C16.16,9.84 17.47,9 19,9"
        "C20.09,9 21.09,9.42 21.81,10.14C20.94,5.5 16.88,2 12,2"
        "C7.09,2 3.03,5.5 2.16,10.17C2.89,9.45 3.89,9 5,9Z",
    ),
    # mdi:drone — unmanned aerial vehicle (UAV)
    "drone": (
        "0 0 24 24",
        "M22,11H21L20,9H13.75L16,12.5H14L10.75,9H4C3.45,9 2,8.55 2,8"
        "C2,7.45 3.5,5.5 5.5,5.5C7.5,5.5 7.67,6.5 9,7H21A1,1 0 0 1 22,8V9L22,11"
        "M10.75,6.5L14,3H16L13.75,6.5H10.75M18,11V9.5H19.75L19,11H18"
        "M3,19A1,1 0 0 1 2,18A1,1 0 0 1 3,17A4,4 0 0 1 7,21A1,1 0 0 1 6,22"
        "A1,1 0 0 1 5,21A2,2 0 0 0 3,19"
        "M11,21A1,1 0 0 1 10,22A1,1 0 0 1 9,21A6,6 0 0 0 3,15"
        "A1,1 0 0 1 2,14A1,1 0 0 1 3,13A8,8 0 0 1 11,21Z",
    ),
    # mdi:rocket-launch — space / trans-atmospheric vehicle
    "rocket": (
        "0 0 24 24",
        "M13.13 22.19L11.5 18.36C13.07 17.78 14.54 17 15.9 16.09L13.13 22.19"
        "M5.64 12.5L1.81 10.87L7.91 8.1C7 9.46 6.22 10.93 5.64 12.5"
        "M21.61 2.39C21.61 2.39 16.66 .269 11 5.93C8.81 8.12 7.5 10.53 6.65 12.64"
        "C6.37 13.39 6.56 14.21 7.11 14.77L9.24 16.89"
        "C9.79 17.45 10.61 17.63 11.36 17.35C13.5 16.53 15.88 15.19 18.07 13"
        "C23.73 7.34 21.61 2.39 21.61 2.39"
        "M14.54 9.46C13.76 8.68 13.76 7.41 14.54 6.63S16.59 5.85 17.37 6.63"
        "C18.14 7.41 18.15 8.68 17.37 9.46C16.59 10.24 15.32 10.24 14.54 9.46"
        "M8.88 16.53L7.47 15.12L8.88 16.53"
        "M6.24 22L9.88 18.36C9.54 18.27 9.21 18.12 8.91 17.91L4.83 22H6.24"
        "M2 22H3.41L8.18 17.24L6.76 15.83L2 20.59V22"
        "M2 19.17L6.09 15.09C5.88 14.79 5.73 14.47 5.64 14.12L2 17.76V19.17Z",
    ),
    # mdi:car — surface vehicles (emergency & service)
    "car": (
        "0 0 24 24",
        "M5,11L6.5,6.5H17.5L19,11M17.5,16A1.5,1.5 0 0,1 16,14.5A1.5,1.5 0 0,1"
        " 17.5,13A1.5,1.5 0 0,1 19,14.5A1.5,1.5 0 0,1 17.5,16"
        "M6.5,16A1.5,1.5 0 0,1 5,14.5A1.5,1.5 0 0,1 6.5,13A1.5,1.5 0 0,1"
        " 8,14.5A1.5,1.5 0 0,1 6.5,16"
        "M18.92,6C18.72,5.42 18.16,5 17.5,5H6.5C5.84,5 5.28,5.42 5.08,6"
        "L3,12V20A1,1 0 0,0 4,21H5A1,1 0 0,0 6,20V19H18V20A1,1 0 0,0 19,21"
        "H20A1,1 0 0,0 21,20V12L18.92,6Z",
    ),
    # mdi:alert-circle — point/cluster/line obstacles
    "alert": (
        "0 0 24 24",
        "M13,13H11V7H13M13,17H11V15H13"
        "M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12"
        "A10,10 0 0,0 12,2Z",
    ),
    # mdi:help-circle — reserved / no ADS-B category info
    "unknown": (
        "0 0 24 24",
        "M15.07,11.25L14.17,12.17C13.45,12.89 13,13.5 13,15H11V14.5"
        "C11,13.39 11.45,12.39 12.17,11.67L13.41,10.41C13.78,10.05 14,9.55 14,9"
        "C14,7.89 13.1,7 12,7A2,2 0 0 0 10,9H8A4,4 0 0 1 12,5A4,4 0 0 1 16,9"
        "C16,9.88 15.64,10.67 15.07,11.25M13,19H11V17H13"
        "M12,2A10,10 0 0 0 2,12A10,10 0 0 0 12,22A10,10 0 0 0 22,12"
        "C22,6.47 17.5,2 12,2Z",
    ),
}

# OpenSky ADS-B category → logical icon name
_CATEGORY_ICON: dict[int | None, str] = {
    None: "airplane_jet",    # no data — default to commercial jet
    0:  "airplane_jet",      # no information
    1:  "unknown",           # no ADS-B emitter category info broadcast
    2:  "airplane_small",    # light (< 15,500 lbs) — prop planes, GA aircraft
    3:  "airplane_small",    # small (15,500–75,000 lbs) — turboprops, small jets
    4:  "airplane_jet",      # large (75,000–300,000 lbs) — narrowbody jets
    5:  "airplane_jet",      # high vortex large (e.g. B-757)
    6:  "airplane_jet",      # heavy (> 300,000 lbs) — widebody jets
    7:  "airplane_hp",       # high performance (> 5g & 400 kts) — fighter jets
    8:  "helicopter",        # rotorcraft
    9:  "kite",              # glider / sailplane
    10: "balloon",           # lighter-than-air (hot air balloon, blimp)
    11: "parachute",         # parachutist / skydiver
    12: "kite",              # ultralight / hang-glider / paraglider
    13: "unknown",           # reserved
    14: "drone",             # unmanned aerial vehicle (UAV)
    15: "rocket",            # space / trans-atmospheric vehicle
    16: "car",               # surface vehicle – emergency
    17: "car",               # surface vehicle – service
    18: "alert",             # point obstacle (tethered balloon, tower, etc.)
    19: "alert",             # cluster obstacle
    20: "alert",             # line obstacle
}

_cache: dict[tuple[str, int], Image.Image] = {}


def render_category_icon(category: int | None, size: int) -> Image.Image:
    """Return a blue-gray RGBA PIL image for the given OpenSky ADS-B category."""
    icon_name = _CATEGORY_ICON.get(category, "airplane_jet")
    key = (icon_name, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    viewbox, path_d = _ICONS[icon_name]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}"'
        f' width="{size}" height="{size}">'
        f'<path d="{path_d}" fill="{_COLOR}"/>'
        f'</svg>'
    )
    png = cairosvg.svg2png(bytestring=svg.encode())
    img = Image.open(BytesIO(png)).convert("RGBA")
    _cache[key] = img
    return img
