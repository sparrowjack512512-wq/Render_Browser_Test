
import logging
import os
import signal
import sys
import threading
import time
import traceback

from flask import Flask, jsonify
from seleniumbase import Driver

# ---------------- CONFIGURATION ----------------

TEST_URL = "https://example.com/"
RESTART_AFTER_CYCLES = 30
CYCLE_INTERVAL_SECONDS = 10
PAGE_LOAD_TIMEOUT_SECONDS = 30
FLASK_PORT = int(os.environ.get("PORT", "10000"))

# ---------------- LOGGING ----------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

log = logging.getLogger("render-browser-worker")

# ---------------- STATE ----------------

app = Flask(__name__)
stop_event = threading.Event()
state_lock = threading.Lock()

state = {
    "running": False,
    "browser_ready": False,
    "cycle": 0,
    "browser_restarts": 0,
    "last_error": None,
    "last_success": None,
}


def update_state(**kwargs):
    with state_lock:
        state.update(kwargs)


def get_state():
    with state_lock:
        return dict(state)


def handle_shutdown(signum, frame):
    log.info("Shutdown signal received: %s", signum)
    stop_event.set()


def create_browser():
    log.info("Starting Chrome browser")

    browser = Driver(
        browser="chrome",
        headless=True,
        binary_location="/usr/bin/google-chrome",
    )

    browser.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
    browser.set_script_timeout(PAGE_LOAD_TIMEOUT_SECONDS)

    log.info("Chrome started successfully")
    return browser


def run_test_cycle(browser, cycle_number):
    log.info("Cycle %s: opening test website", cycle_number)

    browser.get(TEST_URL)

    title = browser.title
    url = browser.current_url

    if not title:
        raise RuntimeError("Test page returned an empty title")

    log.info(
        "Cycle %s passed | title=%r | url=%s",
        cycle_number,
        title,
        url,
    )

    update_state(
        cycle=cycle_number,
        last_success=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        last_error=None,
    )


def worker():
    browser = None
    cycles_since_restart = 0

    update_state(running=True, browser_ready=False)
    log.info("Worker started")

    try:
        while not stop_event.is_set():
            try:
                if browser is None:
                    browser = create_browser()
                    update_state(browser_ready=True)

                cycle_number = cycles_since_restart + 1
                run_test_cycle(browser, cycle_number)
                cycles_since_restart += 1

                if cycles_since_restart >= RESTART_AFTER_CYCLES:
                    log.info(
                        "Completed %s cycles; restarting browser",
                        cycles_since_restart,
                    )

                    update_state(browser_ready=False)

                    try:
                        browser.quit()
                        log.info("Old browser closed")
                    except Exception:
                        log.exception("Error closing old browser")

                    browser = None
                    cycles_since_restart = 0

                    if stop_event.is_set():
                        break

                    browser = create_browser()
                    update_state(
                        browser_ready=True,
                        browser_restarts=get_state()["browser_restarts"] + 1,
                    )
                    log.info("Browser restart completed")

            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                log.error("Cycle failed: %s", error_text)
                log.debug("%s", traceback.format_exc())

                update_state(
                    browser_ready=False,
                    last_error=error_text,
                )

                if browser is not None:
                    try:
                        browser.quit()
                    except Exception:
                        log.exception("Error closing failed browser")

                    browser = None

                if stop_event.wait(5):
                    break

            log.info("WAIT: Beginning %s-second cycle delay", CYCLE_INTERVAL_SECONDS)

            if stop_event.wait(CYCLE_INTERVAL_SECONDS):
                log.info("Shutdown requested during cycle delay")
                break
            
            log.info("WAIT: Delay finished; starting next cycle")

    finally:
        update_state(browser_ready=False)

        if browser is not None:
            try:
                browser.quit()
                log.info("Chrome closed successfully")
            except Exception:
                log.exception("Error during browser shutdown")

        update_state(running=False)
        log.info("Worker stopped")


@app.route("/")
def health():
    current = get_state()
    status_code = 200 if current["running"] else 503

    return jsonify({
        "service": "Render Browser Test",
        **current,
    }), status_code


@app.route("/health")
def health_check():
    current = get_state()

    healthy = (
        current["running"]
        and current["browser_ready"]
        and current["last_error"] is None
    )

    return jsonify({
        "healthy": healthy,
        **current,
    }), 200 if healthy else 503


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    worker_thread = threading.Thread(
        target=worker,
        name="browser-worker",
        daemon=True,
    )
    worker_thread.start()

    log.info("Starting Flask health server on port %s", FLASK_PORT)

    try:
        app.run(
            host="0.0.0.0",
            port=FLASK_PORT,
            use_reloader=False,
        )
    finally:
        stop_event.set()
        worker_thread.join(timeout=10)
