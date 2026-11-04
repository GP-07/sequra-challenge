import logging

logger = logging.getLogger("disbursements.alerts")


def alert(message, *, critical=False):
    """Single notification point. For now, an ERROR or CRITICAL log."""
    logger.log(logging.CRITICAL if critical else logging.ERROR, message)
