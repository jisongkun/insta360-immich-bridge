from concurrent.futures import CancelledError


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError("Operation stopped")
