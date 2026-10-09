"""Users, passwords, login lockout and role checks."""
from datetime import datetime, timedelta
from functools import wraps

from flask import abort, flash, g, redirect, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import IST, audit, now_ist, now_str, transaction

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    # scrypt: a slow, salted hash of the same family as bcrypt (built into Werkzeug, no extra dependency)
    return generate_password_hash(password, method="scrypt")


def password_problem(password: str):
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    return None


def create_user(conn, username, password, role, by_user=None):
    username = (username or "").strip()
    if not username:
        raise ValueError("Username is required")
    if role not in ("owner", "worker"):
        raise ValueError("Role must be owner or worker")
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise ValueError("That username already exists")
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
            (username, hash_password(password), role, now_str()),
        )
        audit(conn, by_user, "user_created", details=f"{role} account '{username}' created")
        return cur.lastrowid


def set_password(conn, user_id, password, by_user=None):
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    with transaction(conn):
        conn.execute("UPDATE users SET password_hash = ?, failed_logins = 0, locked_until = NULL WHERE id = ?",
                     (hash_password(password), user_id))
        audit(conn, by_user, "password_changed", details=f"Password reset for user id {user_id}")


def attempt_login(conn, username, password):
    """Returns (user, error_message)."""
    generic = "Wrong username or password"
    user = conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
    if not user or not user["active"]:
        check_password_hash(hash_password("x" * 8), password or "")  # similar timing for unknown users
        return None, generic
    now = now_ist()
    if user["locked_until"]:
        until = datetime.fromisoformat(user["locked_until"]).replace(tzinfo=IST)
        if until > now:
            return None, f"Too many wrong attempts. This account is locked until {until:%I:%M %p}."
    with transaction(conn):
        if check_password_hash(user["password_hash"], password or ""):
            conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user["id"],))
            audit(conn, user, "login")
            return user, None
        failed = user["failed_logins"] + 1
        if failed >= MAX_FAILED_LOGINS:
            until = now + timedelta(minutes=LOCK_MINUTES)
            conn.execute("UPDATE users SET failed_logins = 0, locked_until = ? WHERE id = ?",
                         (until.strftime("%Y-%m-%d %H:%M:%S"), user["id"]))
            audit(conn, user, "account_locked", details=f"{MAX_FAILED_LOGINS} wrong passwords")
            return None, f"Too many wrong attempts. This account is locked for {LOCK_MINUTES} minutes."
        conn.execute("UPDATE users SET failed_logins = ? WHERE id = ?", (failed, user["id"]))
        audit(conn, user, "login_failed")
    return None, generic


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("main.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def owner_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("main.login", next=request.path))
        if g.user["role"] != "owner":
            flash("Only the owner can open that page.", "error")
            abort(403)
        return view(*args, **kwargs)
    return wrapped
