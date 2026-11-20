# implement security requirements


from __future__ import annotations
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from flask import abort, request, session


# prevent two threads from changing rate limit data at once
_rate_lock = threading.Lock()
# for each key, store times of recent requests
_rate_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def csrf_token() -> str:
    # reuse current session token
    token = session.get("csrf_token")
    if not isinstance(token, str):  # or create token and save
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf() -> None:
    # get the saves session token
    # get token sent by form/request
    expected = session.get("csrf_token", "")
    submitted = request.form.get("csrf_token", "") or request.headers.get(
        "X-CSRF-Token", ""
    )
    # if missing or do not match, reject
    if (
        not expected
        or not submitted
        or not hmac.compare_digest(str(expected), str(submitted))
    ):  # avoid timing difference
        abort(400)


def consume_rate_limit(limit: int, seconds: int, key: str) -> bool:
    now = time.monotonic()
    # random rate-limit ID.
    session_id = session.get("rate_limit_id")
    if not isinstance(session_id, str):
        session_id = secrets.token_urlsafe(16)
        session["rate_limit_id"] = session_id
    # seperate the counters
    bucket_key = (f"{key}:{session_id}", str(seconds))
    with _rate_lock:
        events = _rate_events[bucket_key]
        # remove expired requests
        while events and now - events[0] >= seconds:
            events.popleft()
        # reject requests over limit
        if len(events) >= limit:
            return False
        # record request and allow
        events.append(now)
        return True


# returns a decorator for routes
def rate_limit(limit: int, seconds: int, key: str, *, post_only: bool = True):
    def decorate(function):
        @wraps(function)  # keep original route name/details
        def wrapped(*args, **kwargs):
            should_check = not post_only or request.method == "POST"
            if should_check and not consume_rate_limit(limit, seconds, key):
                abort(429)
            # limit is fine, original route
            return function(*args, **kwargs)

        return wrapped

    return decorate