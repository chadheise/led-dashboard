from plugins.flights.plugin import FlightsApp
from plugins.sports.plugin import SportsApp
from plugins.stocks.plugin import StocksApp
from plugins.text.plugin import TextApp

APP_REGISTRY: dict[str, type] = {
    TextApp.id: TextApp,
    StocksApp.id: StocksApp,
    SportsApp.id: SportsApp,
    FlightsApp.id: FlightsApp,
}
