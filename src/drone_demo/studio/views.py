"""Login, the editor shell, and read-only passthroughs to web/.

The passthrough routes let the studio reuse the already-vendored three.js,
the published manifest.json/drone.glb, and viewer.js's createViewer() for
its read-only assembly backdrop, instead of vendoring three.js a second
time under studio/. They're not login-gated: everything they serve is the
same data already public on the published site.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from drone_demo.cli import WEB_DIR
from drone_demo.studio.auth import login_required, verify_credentials

bp = Blueprint("views", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_credentials(username, password):
            session["user"] = username
            return redirect(request.args.get("next") or url_for("views.editor"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    return redirect(url_for("views.login"))


@bp.route("/")
@login_required
def editor():
    return render_template("editor.html", username=session.get("user"))


@bp.route("/context/vendor/<path:filename>")
def context_vendor(filename: str):
    return send_from_directory(str(WEB_DIR / "vendor"), filename)


@bp.route("/context/assets/<path:filename>")
def context_assets(filename: str):
    return send_from_directory(str(WEB_DIR / "assets"), filename)


@bp.route("/context/viewer.js")
def context_viewer_js():
    return send_from_directory(str(WEB_DIR / "js"), "viewer.js")
