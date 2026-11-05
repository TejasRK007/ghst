"""
GhostTrace - Web Dashboard & Live API Server.
Directly connects the React frontend to the Python audit engine.
Serves live REST endpoints under /api/... and production React SPA under /.

Usage:
    python code/dashboard.py            # Start live API + UI server
    python code/dashboard.py --rebuild  # Rebuild frontend bundle & launch
"""

import os
import sys
import webbrowser
import subprocess

from dotenv import load_dotenv

PORT = 8000
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Load .env from project root so GROQ_API_KEY is available
load_dotenv(os.path.join(ROOT, ".env"), override=True)
DIRECTORY = os.path.join(ROOT, "docs")
FRONTEND = os.path.join(ROOT, "frontend")
PYTHON = sys.executable


def rebuild_frontend():
    """Build the production React SPA bundle into docs/."""
    print("🔨 Building production frontend bundle...")
    subprocess.run(["npm", "run", "build"], check=True, cwd=FRONTEND)
    print("✅ Frontend built successfully.\n")


def main():
    rebuild_flag = "--rebuild" in sys.argv

    if rebuild_flag or not os.path.exists(os.path.join(DIRECTORY, "index.html")):
        rebuild_frontend()

    if not os.path.exists(os.path.join(DIRECTORY, "index.html")):
        print("❌ docs/index.html not found. Run: cd frontend && npm run build")
        sys.exit(1)

    url = f"http://localhost:{PORT}/"
    print("=" * 65)
    print("        🚀 GHOSTTRACE LIVE ENGINE & DASHBOARD SERVER")
    print("=" * 65)
    print(f"  • Dashboard URL:    {url}")
    print(f"  • API Root:         {url}api/health")
    print(f"  • Dataset Source:   dataset/ (518 evaluation requests)")
    print(f"  • Output Model:     output.csv")
    print(f"  • Live Backend:     FastAPI + Uvicorn")
    print(f"  • Rebuild UI:       python code/dashboard.py --rebuild")
    print("  • Press Ctrl+C to stop server.")
    print("=" * 65)

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        import uvicorn
        # Ensure project root is in path
        sys.path.insert(0, ROOT)
        from code.server import app
        uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
    except ImportError:
        # Fallback to SimpleHTTPRequestHandler if uvicorn is not installed
        import http.server
        import socketserver

        class SPAHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=DIRECTORY, **kwargs)

            def do_GET(self):
                path = self.translate_path(self.path)
                if os.path.exists(path) and os.path.isfile(path):
                    return super().do_GET()
                if not os.path.splitext(self.path)[1]:
                    self.path = "/index.html"
                return super().do_GET()

        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", PORT), SPAHandler) as httpd:
            httpd.serve_forever()


if __name__ == "__main__":
    main()
