"""Tiny retry helper with exponential backoff."""
import time


def retry(fn, attempts: int = 3, base_delay: float = 2.0, log=None, what: str = "call", retry_if=None):
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if retry_if is not None and not retry_if(e):
                raise
            if i < attempts:
                delay = base_delay * 2 ** (i - 1)
                if log:
                    log.warning(f"{what} failed (attempt {i}/{attempts}): {str(e)[:200]} - retrying in {delay:.0f}s")
                time.sleep(delay)
    raise last
