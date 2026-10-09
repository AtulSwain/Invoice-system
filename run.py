"""Start the app:  python run.py   then open http://localhost:8000

Uses the Waitress server when installed (it is in requirements.txt), which is
fine for both local use and production. Settings come from environment variables.
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    try:
        from waitress import serve
    except ImportError:
        print(f"Open http://localhost:{port}  (Waitress not installed: using Flask's development server)")
        app.run(host=host, port=port)
    else:
        print(f"Vinayak Creation invoicing is running. Open http://localhost:{port}  (Ctrl+C to stop)")
        serve(app, host=host, port=port, threads=8)
