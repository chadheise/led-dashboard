from libraries.base import Library
from libraries.canvas_utils.library import CanvasUtilsLibrary
from libraries.text_renderer.library import TextRendererLibrary
from libraries.yahoo_finance.library import YahooFinanceLibrary
from libraries.espn_sports.library import ESPNSportsLibrary
from libraries.opensky.library import OpenSkyLibrary
from libraries.flightaware.library import FlightAwareLibrary

LIBRARY_REGISTRY: dict[str, type[Library]] = {
    "canvas_utils": CanvasUtilsLibrary,
    "text_renderer": TextRendererLibrary,
    "yahoo_finance": YahooFinanceLibrary,
    "espn_sports": ESPNSportsLibrary,
    "opensky": OpenSkyLibrary,
    "flightaware": FlightAwareLibrary,
}
