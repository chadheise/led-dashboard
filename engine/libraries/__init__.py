from libraries.base import Library
from libraries.canvas_utils.library import CanvasUtilsLibrary
from libraries.text_renderer.library import TextRendererLibrary
from libraries.yahoo_finance.library import YahooFinanceLibrary
from libraries.espn_sports.library import ESPNSportsLibrary
from libraries.opensky.library import OpenSkyLibrary
from libraries.flightaware.library import FlightAwareLibrary
from libraries.location.library import LocationLibrary
from libraries.spotify.library import SpotifyLibrary
from libraries.open_meteo.library import OpenMeteoLibrary
from libraries.timezones.library import TimezonesLibrary
from libraries.holidays.library import HolidaysLibrary

LIBRARY_REGISTRY: dict[str, type[Library]] = {
    "canvas_utils": CanvasUtilsLibrary,
    "text_renderer": TextRendererLibrary,
    "yahoo_finance": YahooFinanceLibrary,
    "espn_sports": ESPNSportsLibrary,
    "opensky": OpenSkyLibrary,
    "flightaware": FlightAwareLibrary,
    "location": LocationLibrary,
    "spotify": SpotifyLibrary,
    "open_meteo": OpenMeteoLibrary,
    "timezones": TimezonesLibrary,
    "holidays": HolidaysLibrary,
}
