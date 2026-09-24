"""Login gate for the studio.

Everything in this module funnels through ``verify_credentials``. That is
deliberate: this is a local, single-user dev tool, so a hardcoded dummy
credential is fine for now, but the day a real user store shows up, this is
the *only* function that needs to change -- no route anywhere else in the
studio touches ``_DUMMY_USERS`` directly.

Not production-grade, and not meant to be: password is sent in the clear
over plain HTTP and compared in the clear server-side, there's no rate
limiting, and the session secret is a locally-generated file (see
``studio/__init__.py``). That's an acceptable trade for a tool that only
ever binds to 127.0.0.1, the same way ``python -m drone_demo serve`` does.
"""

from __future__ import annotations

from functools import wraps

from flask import redirect, session, url_for

#: Replace this dict -- and only this dict, via verify_credentials -- with a
#: real user store when "later" arrives.
_DUMMY_USERS = {"admin": "admin"}


def verify_credentials(username: str, password: str) -> bool:
    return _DUMMY_USERS.get(username) == password


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("views.login", next=_safe_next()))
        return view(*args, **kwargs)

    return wrapped


def _safe_next() -> str:
    from flask import request

    return request.path
