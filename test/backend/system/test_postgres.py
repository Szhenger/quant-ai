"""PostgreSQL storage behavior — the things the ORM can't promise.

The suite runs on the production engine (see config/test_settings.py), so these
tests exercise real JSONB, real check constraints, real row locks and real
cascades — exactly the behaviors that silently degrade to no-ops on sqlite.
"""
import threading

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, OperationalError, connection, transaction

from strategies.models import Alert, Strategy
from identity.models import Workspace
from watchlist.models import WatchedTicker

pytestmark = pytest.mark.django_db


def _strategy(workspace, **overrides):
    fields = dict(
        workspace=workspace, name="Sanity", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0, ai_enabled=False,
    )
    fields.update(overrides)
    return Strategy.objects.create(**fields)


# --------------------------------------------------------------------------- #
# JSONB round-trips and queries
# --------------------------------------------------------------------------- #
def test_jsonb_roundtrips_nested_structures(workspace):
    tree = {"all": [{"left": {"indicator": "RSI", "params": {"period": 14}},
                     "operator": "<", "right": 30.0}]}
    strategy = _strategy(workspace, params={"window": 20}, condition=tree)
    strategy.refresh_from_db()
    assert strategy.params == {"window": 20}
    assert strategy.condition == tree


def test_jsonb_containment_query_works_on_the_real_engine(workspace):
    _strategy(workspace, params={"window": 20})
    _strategy(workspace, name="Other", params={"window": 50})
    matches = Strategy.objects.filter(params__contains={"window": 20})
    assert matches.count() == 1


# --------------------------------------------------------------------------- #
# Constraints
# --------------------------------------------------------------------------- #
def test_positive_integer_check_constraint_is_enforced_by_the_database(workspace):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _strategy(workspace, cooldown_minutes=-1)


def test_watchlist_uniqueness_is_a_database_constraint(workspace):
    WatchedTicker.objects.create(workspace=workspace, ticker="AAPL")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            # bypass the API-level check; " aapl " normalises to the same row
            WatchedTicker.objects.create(workspace=workspace, ticker=" aapl ")


def test_ticker_is_normalised_on_save(workspace):
    strategy = _strategy(workspace, ticker="  msft ")
    strategy.refresh_from_db()
    assert strategy.ticker == "MSFT"


# --------------------------------------------------------------------------- #
# Referential integrity
# --------------------------------------------------------------------------- #
def test_deleting_a_workspace_cascades_to_strategies_and_alerts(workspace):
    strategy = _strategy(workspace)
    Alert.objects.create(workspace=workspace, strategy=strategy, ticker="AAPL",
                         indicator="PRICE", operator=">", threshold=0.0)
    workspace.delete()
    assert Strategy.objects.count() == 0
    assert Alert.objects.count() == 0


def test_deleting_a_strategy_orphans_but_keeps_its_alerts(workspace):
    strategy = _strategy(workspace)
    alert = Alert.objects.create(workspace=workspace, strategy=strategy,
                                 ticker="AAPL", indicator="PRICE",
                                 operator=">", threshold=0.0)
    strategy.delete()
    alert.refresh_from_db()
    assert alert.strategy is None  # history survives the strategy


# --------------------------------------------------------------------------- #
# Indexes
# --------------------------------------------------------------------------- #
def test_alert_cursor_pagination_index_exists():
    """The (workspace, -created_at) index backs cursor pagination; losing it in
    a migration would silently turn every page into an offset scan."""
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, Alert._meta.db_table)
    assert any(
        c["index"] and c["columns"] == ["workspace_id", "created_at"]
        for c in constraints.values()
    ), "missing the (workspace, -created_at) alert index"


# --------------------------------------------------------------------------- #
# Row locking (real SELECT FOR UPDATE, two connections)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db(transaction=True)
def test_select_for_update_actually_locks_the_row():
    user = get_user_model().objects.create_user(username="locker", password="pw12345!")
    workspace = Workspace.objects.create(name="Locks", owner=user)
    strategy = _strategy(workspace)
    outcome = []

    def contender():
        try:
            with transaction.atomic():
                try:
                    Strategy.objects.select_for_update(nowait=True).get(pk=strategy.pk)
                    outcome.append("acquired")
                except OperationalError:
                    outcome.append("blocked")
        finally:
            connection.close()  # this thread's own connection

    with transaction.atomic():
        Strategy.objects.select_for_update().get(pk=strategy.pk)
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(timeout=15)
    assert outcome == ["blocked"], (
        "a second connection acquired a row this transaction holds FOR UPDATE"
    )


# --------------------------------------------------------------------------- #
# Migration hygiene
# --------------------------------------------------------------------------- #
def test_models_match_the_committed_migrations():
    try:
        call_command("makemigrations", check=True, dry_run=True, verbosity=0)
    except SystemExit:
        pytest.fail("model changes are not reflected in the committed migrations")
