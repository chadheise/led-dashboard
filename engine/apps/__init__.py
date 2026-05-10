from apps.flights.plugin import FlightsApp
from apps.sports.plugin import SportsApp
from apps.stocks.plugin import StocksApp
from apps.text.plugin import TextApp

APP_REGISTRY: dict[str, type] = {
    TextApp.id: TextApp,
    StocksApp.id: StocksApp,
    SportsApp.id: SportsApp,
    FlightsApp.id: FlightsApp,
}
