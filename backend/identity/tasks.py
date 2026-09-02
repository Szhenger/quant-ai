"""Identity housekeeping on the Beat schedule."""
import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def flush_expired_tokens():
    """Daily: drop expired JWTs from the blacklist tables. Refresh rotation
    writes one row per refresh, forever, so without this the table only grows."""
    call_command("flushexpiredtokens")
    logger.info("Retention: flushed expired tokens")
