from apps.flights.app import FlightsApp
from apps.sports.app import SportsApp
from apps.stocks.app import StocksApp
from apps.text.app import TextApp

APP_REGISTRY: dict[str, type] = {
    TextApp.id: TextApp,
    StocksApp.id: StocksApp,
    SportsApp.id: SportsApp,
    FlightsApp.id: FlightsApp,
}
