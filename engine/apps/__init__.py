from apps.debug.app import DebugApp
from apps.countdown.app import CountdownApp
from apps.flights_overhead.app import FlightsOverheadApp
from apps.flight_tracker.app import FlightTrackerApp
from apps.sports.app import SportsApp
from apps.spotify.app import SpotifyApp
from apps.stocks.app import StocksApp
from apps.text.app import TextApp
from apps.weather.app import WeatherApp
from apps.world_clock.app import WorldClockApp

APP_REGISTRY: dict[str, type] = {
    DebugApp.id: DebugApp,
    TextApp.id: TextApp,
    StocksApp.id: StocksApp,
    SportsApp.id: SportsApp,
    FlightsOverheadApp.id: FlightsOverheadApp,
    FlightTrackerApp.id: FlightTrackerApp,
    CountdownApp.id: CountdownApp,
    SpotifyApp.id: SpotifyApp,
    WeatherApp.id: WeatherApp,
    WorldClockApp.id: WorldClockApp,
}
