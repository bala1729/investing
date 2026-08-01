"""Example strategy implementations."""

from src.bot.strategies.examples.ema_crossover import EMACrossoverStrategy
from src.bot.strategies.examples.heikin_ashi_confluence import HeikinAshiConfluenceStrategy
from src.bot.strategies.examples.moving_average_crossover import (
    MovingAverageCrossoverStrategy,
)

__all__ = [
    "EMACrossoverStrategy",
    "HeikinAshiConfluenceStrategy",
    "MovingAverageCrossoverStrategy",
]
