"""Cross-cutting mechanics shared by every feature app.

Nothing here knows about strategies, watchlists or markets: the compute
cache + conditional GET (``caching``), input validators (``validators``), the
workspace event bus (``events``) and the health probe (``health``).
"""
