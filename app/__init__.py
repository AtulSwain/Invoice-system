"""Vinayak Creation invoicing app (Flask + SQLite)."""
import secrets
import time

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

from .config import load_config
from .db import connect, get_settings, init_db, today_ist
from .money import inr, plain
from .words import amount_in_words

SESSION_IDLE_SECONDS = 8 * 60 * 60


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(load_config())
    if overrides:
        app.config.update(overrides)
    app.config["PERMANENT_SESSION_LIFETIME"] = SESSION_IDLE_SECONDS
    app.config["SESSION_REFRESH_EACH_REQUEST"] = True

    if app.config["PRODUCTION"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    conn = connect(app.config["DATABASE_PATH"])
    init_db(conn, seed_customers=False)  # tables + default settings; customers come from seed.py
    conn.close()

    def get_db():
        if "db" not in g:
            g.db = connect(app.config["DATABASE_PATH"])
        return g.db

    app.get_db = get_db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    last_backup_check = {"t": 0.0}

    @app.before_request
    def before():
        if app.config["PRODUCTION"] and not request.is_secure and request.endpoint != "health":
            return redirect(request.url.replace("http://", "https://", 1), code=301)
        g.user = None
        uid = session.get("uid")
        if uid:
            idle = time.time() - session.get("last_seen", 0)
            user = get_db().execute("SELECT * FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
            if idle > SESSION_IDLE_SECONDS or not user:
                session.clear()
                flash("You were logged out after 8 hours without use. Please log in again.", "info")
            else:
                g.user = user
                session.permanent = True
                session["last_seen"] = time.time()
        if request.method == "POST":
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "This form has expired. Go back, refresh the page and try again.")
        if app.config["AUTO_BACKUP"] and time.time() - last_backup_check["t"] > 3600:
            last_backup_check["t"] = time.time()
            try:
                from .backup import run_backup
                run_backup(app.config["DATABASE_PATH"], app.config["BACKUP_DIR"], today_ist())
            except Exception:  # a failed backup must never stop invoicing
                app.logger.exception("Automatic backup failed")

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if app.config["PRODUCTION"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    @app.context_processor
    def inject():
        return {"csrf_token": csrf_token, "user": g.get("user"),
                "biz": get_settings(get_db()), "is_owner": bool(g.get("user") and g.user["role"] == "owner")}

    def dmy(value):
        if not value:
            return ""
        s = str(value)[:10]
        y, m, d = s.split("-")
        return f"{d}/{m}/{y}"

    app.jinja_env.filters.update(inr=inr, plain=plain, dmy=dmy, words=amount_in_words)

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", title="Not allowed",
                               message="Only the owner can open that page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", title="Not found", message="That page does not exist."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", title="Please try again", message=e.description), 400

    @app.route("/health")
    def health():
        return "ok"

    from .views import bp
    app.register_blueprint(bp)
    return app
