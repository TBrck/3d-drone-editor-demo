"""The parts & assembly studio: a local, login-gated authoring tool.

Not part of the published pipeline -- ``python -m drone_demo build``/``all``/
``serve`` never import this package, and its own frontend lives in a
top-level ``studio/`` directory, not under ``web/``, specifically so it is
never picked up by ``.github/workflows/pages.yml`` (which publishes
``web/`` verbatim to the public portfolio site).
"""

from __future__ import annotations

import secrets
from pathlib import Path

from flask import Flask

from drone_demo.cli import REPO_ROOT

STUDIO_DIR = REPO_ROOT / "studio"


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(STUDIO_DIR / "templates"),
        static_folder=str(STUDIO_DIR / "static"),
        instance_path=str(REPO_ROOT / "instance"),
        instance_relative_config=True,
    )
    app.config["SECRET_KEY"] = _load_or_create_secret_key(Path(app.instance_path))

    from drone_demo.studio import api, views

    app.register_blueprint(views.bp)
    app.register_blueprint(api.bp)
    return app


def _load_or_create_secret_key(instance_path: Path) -> str:
    """A signed-session secret, persisted locally so logins survive a restart.

    Generated on first run, not committed (``instance/`` is already covered
    by the stock Python .gitignore's Flask block). Fine for a single-user
    local tool; a real deployment would want this from an environment
    variable or a secrets manager instead.
    """
    instance_path.mkdir(parents=True, exist_ok=True)
    key_path = instance_path / "secret_key"
    if not key_path.exists():
        key_path.write_text(secrets.token_hex(32), encoding="utf-8")
    return key_path.read_text(encoding="utf-8").strip()
