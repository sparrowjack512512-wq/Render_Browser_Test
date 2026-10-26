
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
ERROR_RETRY_SECONDS = 5
HEARTBEAT_INTERVAL_SECONDS = 15

FLASK_PORT = int(os.environ.get("PORT", "10000"))

# ---------------- LOGGING ----------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

log = logging.getLogger("render-browser-worker")

# ---------------- APPLICATION STATE ----------------

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
    "last_activity": None,
}


def update_state(**kwargs):
    with state_lock:
        state.update(kwargs)


def get_state():
    with state_lock:
        return dict(state)


def record_activity(message):
    update_state(
        last_activity=time.strftime(
            "%Y-%m-%d %H:%M:%S UTC",
            time.gmtime(),
        )
    )
    log.info("%s", message)


# ---------------- SHUTDOWN HANDLING ----------------

def handle_shutdown(signum, frame):
    log.info("Shutdown signal received: %s", signum)
    stop_event.set()


# ---------------- CHROME ----------------

def create_browser():
    record_activity("BROWSER: Starting Chrome")

    browser = Driver(
        browser="chrome",
        headless=True,
        binary_location="/usr/bin/google-chrome",
    )

    browser.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
    browser.set_script_timeout(PAGE_LOAD_TIMEOUT_SECONDS)

    record_activity("BROWSER: Chrome started successfully")
    return browser


def close_browser(browser):
    if browser is None:
        return

    try:
        record_activity("BROWSER: Closing Chrome")
        browser.quit()
        record_activity("BROWSER: Chrome closed successfully")
    except Exception:
        log.exception("BROWSER: Error while closing Chrome")


# ---------------- TEST CYCLE ----------------

def run_test_cycle(browser, cycle_number):
    record_activity(
        f"CYCLE {cycle_number}: Starting website navigation"
    )

    browser.get(TEST_URL)

    record_activity(
        f"CYCLE {cycle_number}: Navigation completed"
    )

    title = browser.title
    url = browser.current_url

    if not title:
        raise RuntimeError("Test page returned an empty title")

    record_activity(
        f"CYCLE {cycle_number} PASSED | "
        f"title={title!r} | url={url}"
    )

    update_state(
        cycle=cycle_number,
        last_success=time.strftime(
            "%Y-%m-%d %H:%M:%S UTC",
            time.gmtime(),
        ),
        last_error=None,
    )


# ---------------- HEARTBEAT ----------------

def heartbeat_monitor():
    log.info("WATCHDOG: Heartbeat monitor started")

    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        current = get_state()

        log.info(
            "WATCHDOG: Process alive | "
            "worker_running=%s | browser_ready=%s | "
            "last_completed_cycle=%s | browser_restarts=%s | "
            "last_error=%s",
            current["running"],
            current["browser_ready"],
            current["cycle"],
            current["browser_restarts"],
            current["last_error"],
        )


# ---------------- BACKGROUND WORKER ----------------

def worker():
    browser = None
    cycles_since_restart = 0

    update_state(
        running=True,
        browser_ready=False,
        last_error=None,
    )

    record_activity("WORKER: Background worker started")

    try:
        while not stop_event.is_set():
            try:
                if browser is None:
                    browser = create_browser()
                    update_state(browser_ready=True)

                cycle_number = cycles_since_restart + 1

                run_test_cycle(browser, cycle_number)
                cycles_since_restart += 1

                # Restart Chrome after the configured number of cycles.
                if cycles_since_restart >= RESTART_AFTER_CYCLES:
                    record_activity(
                        f"BROWSER: Restarting after "
                        f"{cycles_since_restart} successful cycles"
                    )

                    update_state(browser_ready=False)
                    close_browser(browser)
                    browser = None
                    cycles_since_restart = 0

                    if stop_event.is_set():
                        break

                    browser = create_browser()

                    update_state(
                        browser_ready=True,
                        browser_restarts=(
                            get_state()["browser_restarts"] + 1
                        ),
                    )

                    record_activity(
                        "BROWSER: Restart completed successfully"
                    )

                # Explicit logs around the wait help identify a stall.
                record_activity(
                    f"WAIT: Beginning {CYCLE_INTERVAL_SECONDS}-second delay"
                )

                interrupted = stop_event.wait(
                    CYCLE_INTERVAL_SECONDS
                )

                if interrupted:
                    record_activity(
                        "WAIT: Delay interrupted by shutdown"
                    )
                    break

                record_activity(
                    "WAIT: Delay finished; starting next cycle"
                )

            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"

                log.error("WORKER: Cycle failed: %s", error_text)
                log.debug("%s", traceback.format_exc())

                update_state(
                    browser_ready=False,
                    last_error=error_text,
                )

                close_browser(browser)
                browser = None
                cycles_since_restart = 0

                if stop_event.wait(ERROR_RETRY_SECONDS):
                    break

    finally:
        update_state(browser_ready=False)

        close_browser(browser)

        update_state(running=False)

        record_activity("WORKER: Background worker stopped")


# ---------------- HEALTH ENDPOINTS ----------------

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


# ---------------- STARTUP ----------------

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    log.info("CONTAINER APPLICATION STARTING")

    worker_thread = threading.Thread(
        target=worker,
        name="browser-worker",
        daemon=True,
    )

    heartbeat_thread = threading.Thread(
        target=heartbeat_monitor,
        name="heartbeat-monitor",
        daemon=True,
    )

    worker_thread.start()
    heartbeat_thread.start()

    log.info(
        "Starting Flask health server on port %s",
        FLASK_PORT,
    )

    try:
        app.run(
            host="0.0.0.0",
            port=FLASK_PORT,
            use_reloader=False,
            threaded=True,
        )

    finally:
        log.info("APPLICATION: Shutdown started")
        stop_event.set()

        worker_thread.join(timeout=10)
        heartbeat_thread.join(timeout=3)

        log.info("APPLICATION: Shutdown complete")
