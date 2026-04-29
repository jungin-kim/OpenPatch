from threading import Lock


_active_request_id: str | None = None
_lock = Lock()


def mark_repository_open_request_current(request_id: str | None) -> None:
    if not request_id:
        return
    with _lock:
        global _active_request_id
        _active_request_id = request_id


def is_repository_open_request_current(request_id: str | None) -> bool:
    if not request_id:
        return True
    with _lock:
        return _active_request_id == request_id


def clear_repository_open_request(request_id: str | None) -> None:
    if not request_id:
        return
    with _lock:
        global _active_request_id
        if _active_request_id == request_id:
            _active_request_id = None
