"""Entry point for hosts that load a WSGI app (PythonAnywhere, gunicorn, waitress-serve)."""
from app import create_app

application = app = create_app()
