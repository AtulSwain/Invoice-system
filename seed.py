"""First-time setup: creates the database, the owner and worker logins, and the starting customer list.

    python seed.py

Passwords are typed in (never stored in code). On hosts without a console you can
instead set OWNER_USERNAME, OWNER_PASSWORD, WORKER_USERNAME, WORKER_PASSWORD as
environment variables for one run, then remove them.
Running it again is safe: existing users and customers are left alone.
"""
import getpass
import os
import sys

from app.auth import create_user, password_problem
from app.config import load_config
from app.db import SEED_CUSTOMERS, connect, init_db


def ask_password(label):
    print("  NOTE: for safety, nothing appears on screen while you type a password (not even * or dots).")
    print("  Just type it and press Enter.")
    while True:
        pw = getpass.getpass(f"Password for {label} (min 8 characters): ")
        problem = password_problem(pw)
        if problem:
            print(" ", problem)
            continue
        if getpass.getpass("Type it again: ") != pw:
            print("  The two passwords did not match. Try again.")
            continue
        return pw


def ensure_user(conn, role, default_name):
    env_user = os.environ.get(f"{role.upper()}_USERNAME")
    env_pass = os.environ.get(f"{role.upper()}_PASSWORD")
    if conn.execute("SELECT 1 FROM users WHERE role = ? AND active = 1", (role,)).fetchone():
        print(f"- A {role} account already exists. Skipping.")
        return
    if env_user and env_pass:
        username, password = env_user, env_pass
    elif not sys.stdin.isatty():
        print(f"- No {role} account and no console to ask. Set {role.upper()}_USERNAME/{role.upper()}_PASSWORD.")
        return
    else:
        username = input(f"Username for the {role} [{default_name}]: ").strip() or default_name
        password = ask_password(username)
    create_user(conn, username, password, role)
    print(f"- Created {role} account '{username}'.")


def main():
    cfg = load_config()
    conn = connect(cfg["DATABASE_PATH"])
    init_db(conn, seed_customers=True)
    print(f"Database: {cfg['DATABASE_PATH']}")
    print("- Customers ready:", ", ".join(SEED_CUSTOMERS))
    ensure_user(conn, "owner", "owner")
    ensure_user(conn, "worker", "worker")
    seq = conn.execute("SELECT next_number, confirmed FROM invoice_sequence").fetchone()
    print(f"- Next invoice number: {seq['next_number']} "
          f"({'confirmed' if seq['confirmed'] else 'owner must confirm it in the app before the first invoice'})")
    conn.close()


if __name__ == "__main__":
    main()
