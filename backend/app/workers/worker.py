import logging
import multiprocessing
import signal
import sys
from typing import Any

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def run_worker(index: int) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    connection = Redis.from_url(settings.redis_url)
    worker = Worker(
        [Queue("mediafetch", connection=connection)],
        connection=connection,
        name=f"mediafetch-worker-{index}",
    )
    worker.work(with_scheduler=True)


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    processes = [
        multiprocessing.Process(target=run_worker, args=(index,), name=f"worker-{index}")
        for index in range(1, settings.max_global_workers + 1)
    ]
    stopping = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        logger.info("Stopping worker pool")
        for process in processes:
            if process.is_alive():
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for process in processes:
        process.start()
    for process in processes:
        process.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
