
import logging
import sys
import traceback
from seleniumbase import Driver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)

log = logging.getLogger("render-browser-test")


def main():
    driver = None

    try:
        log.info("STEP 1: Starting SeleniumBase")

        driver = Driver(
            browser="chrome",
            headless=False,
            binary_location="/usr/bin/google-chrome",
        )

        log.info("STEP 2: Chrome launched successfully")

        driver.get("https://example.com")

        log.info("STEP 3: Website opened")
        log.info("Page title: %s", driver.title)
        log.info("Current URL: %s", driver.current_url)

        driver.save_screenshot("/tmp/browser-test.png")
        log.info("STEP 4: Screenshot saved")

        log.info("SUCCESS: Render Chrome test passed")

    except BaseException as e:
        log.critical("FAILED: %s: %s", type(e).__name__, e)
        log.critical(traceback.format_exc())
        sys.exit(1)

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
