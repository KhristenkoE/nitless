"""Outbox relay worker: ``python -m app.worker``."""

import signal
import time
from types import FrameType

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger
from app.services.notifier import WebhookNotifier
from app.services.outbox_relay import relay_pending

log = get_logger(__name__)

_running = True


def _stop(signum: int, frame: FrameType | None) -> None:
    global _running
    _running = False


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    notifier = WebhookNotifier(settings)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("outbox_worker_started", batch_size=settings.outbox_batch_size)
    while _running:
        with session_scope() as session:
            delivered = relay_pending(
                session,
                notifier,
                batch_size=settings.outbox_batch_size,
                max_attempts=settings.outbox_max_attempts,
            )
        if delivered == 0:
            time.sleep(settings.outbox_poll_interval_seconds)
    log.info("outbox_worker_stopped")


if __name__ == "__main__":
    main()
