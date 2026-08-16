"""Project-wide pagination defaults."""
from rest_framework.pagination import LimitOffsetPagination


class BoundedLimitOffsetPagination(LimitOffsetPagination):
    """LimitOffset with a ceiling on ``?limit=``.

    DRF's default LimitOffsetPagination honours any client-supplied limit, so
    ``?limit=1000000`` serializes an entire table in one response — an easy
    memory/CPU amplification against the API tier. Alerts already use bounded
    cursor pagination; this closes the same hole for every LimitOffset list.
    The console pages at the server default (50), so nothing legitimate is
    affected.
    """

    max_limit = 200
