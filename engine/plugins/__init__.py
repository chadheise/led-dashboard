from plugins.flights.plugin import FlightsPlugin
from plugins.sports.plugin import SportsPlugin
from plugins.stocks.plugin import StocksPlugin
from plugins.text.plugin import TextPlugin

REGISTRY: dict[str, type] = {
    TextPlugin.id: TextPlugin,
    StocksPlugin.id: StocksPlugin,
    SportsPlugin.id: SportsPlugin,
    FlightsPlugin.id: FlightsPlugin,
}
