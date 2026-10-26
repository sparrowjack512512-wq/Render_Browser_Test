
import logging
import signal
import sys
import threading
import time
import traceback

from seleniumbase import Driver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)

log = logging.getLogger("render-browser-worker")
stop_event = threading.Event()


def handle_shutdown(signum, frame):
    log.info("Shutdown signal received. Stopping worker...")
    stop_event.set()


def main():
    driver = None

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        log.info("STEP 1: Starting persistent Chrome worker")

        driver = Driver(
            browser="chrome",
            headless=False,
            binary_location="/usr/bin/google-chrome",
        )

        log.info("STEP 2: Chrome launched successfully")

        driver.get("https://example.com/")

        log.info("STEP 3: Initial page loaded")
        log.info("Page title: %s", driver.title)
        log.info("Current URL: %s", driver.current_url)

        log.info("Worker is now running. Heartbeat interval: 60 seconds")

        while not stop_event.wait(60):
            try:
                driver.get("https://example.com/")

                log.info(
                    "HEARTBEAT: Browser is responding | title=%s | url=%s",
                    driver.title,
                    driver.current_url,
                )

            except Exception:
                log.error(
                    "Browser health check failed:\n%s",
                    traceback.format_exc(),
                )

    except Exception:
        log.critical(
            "Worker startup failed:\n%s",
            traceback.format_exc(),
        )
        sys.exit(1)

    finally:
        if driver is not None:
            try:
                driver.quit()
                log.info("Chrome closed successfully")
            except Exception:
                log.exception("Error while closing Chrome")

        log.info("Worker stopped")


if __name__ == "__main__":
    main()
