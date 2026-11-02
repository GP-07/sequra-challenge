import logging

logger = logging.getLogger("disbursements.alerts")


def alert(message, *, critical=False):
    """Punto único de notificación. Por ahora, un log ERROR o CRITICAL."""
    raise NotImplementedError
