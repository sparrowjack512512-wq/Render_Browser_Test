
import logging
import signal
import sys
import threading
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
    log.info("Shutdown signal received.")
    stop_event.set()


def main():
    driver = None

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        log.info("STEP 1: Starting Chrome")

        driver = Driver(
            browser="chrome",
            headless=False,
            binary_location="/usr/bin/google-chrome",
        )

        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)

        log.info("STEP 2: Chrome launched successfully")

        log.info("STEP 3: Opening initial test website")
        driver.get("https://example.com/")

        log.info("STEP 4: Initial navigation completed")
        log.info("Initial page title: %s", driver.title)
        log.info("Initial page URL: %s", driver.current_url)

        log.info("STEP 5: Starting browser health-check loop")

        while not stop_event.is_set():
            log.info("WAITING: Next health check in 60 seconds")

            if stop_event.wait(60):
                break

            try:
                log.info("HEARTBEAT: Checking browser URL")

                current_url = driver.current_url
                log.info("HEARTBEAT: URL check passed: %s", current_url)

                log.info("HEARTBEAT: Checking browser page title")

                page_title = driver.title
                log.info("HEARTBEAT: Title check passed: %s", page_title)

                log.info("HEARTBEAT: Browser session is responding")

            except Exception:
                log.error(
                    "HEARTBEAT FAILED:\n%s",
                    traceback.format_exc(),
                )

        log.info("Worker shutdown requested")

    except Exception:
        log.critical(
            "WORKER STARTUP FAILED:\n%s",
            traceback.format_exc(),
        )
        sys.exit(1)

    finally:
        if driver is not None:
            try:
                log.info("Closing Chrome")
                driver.quit()
                log.info("Chrome closed successfully")
            except Exception:
                log.exception("Error while closing Chrome")

        log.info("Worker stopped")


if __name__ == "__main__":
    main()
