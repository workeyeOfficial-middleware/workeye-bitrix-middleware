"""
server.py
=========
Serves frontend + proxies API calls + serves WorkEye screenshots.

Paths served:
  /index.html           → frontend dashboard
  /screenshots/...      → actual screenshot images from WorkEye backend
  /get-*  /sync-*       → proxied to FastAPI backend on port 8001
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.request
import os

BACKEND = "https://workeye-bitrix-integration.onrender.com"

# ── Path to WorkEye screenshots folder ──────────────────
SCREENSHOTS_DIR = r"C:\Users\hr\Downloads\WorkEye-Project-Backend-main (1)\WorkEye-Project-Backend-main\screenshots"
# ────────────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):

    def do_POST(self):
        # Bitrix24 sends POST on install — serve index.html
        if self.path.startswith("/index.html") or self.path == "/" or "DOMAIN=" in self.path:
            self.path = "/index.html"
            super().do_GET()
            return
        # Proxy login and sync calls
        if self.path.startswith("/login") or self.path.startswith("/sync-"):
            self._proxy()
            return
        self._proxy()

    def do_GET(self):
        # Root → index.html
        if self.path == "/" or self.path.startswith("/?"):
            self.path = "/index.html"
            super().do_GET()
            return

        # Serve screenshot images directly from WorkEye folder
        if self.path.startswith("/screenshots/"):
            self._serve_screenshot()
            return

        # Proxy API calls to FastAPI backend
        path = self.path.split("?")[0]  # get path without query string
        if path.startswith("/get-") or path.startswith("/sync-") or path == "/login" or path == "/proxy-image":
            self._proxy()
            return

        # Serve static files (index.html, css, js)
        super().do_GET()

    def _serve_screenshot(self):
        """Serve a screenshot file from WorkEye backend folder."""
        rel_path = self.path[len("/screenshots/"):]
        rel_path = rel_path.split("?")[0]

        full_path = os.path.join(SCREENSHOTS_DIR, rel_path.replace("/", os.sep))

        if not os.path.exists(full_path):
            self.send_response(404)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"Screenshot not found: " + full_path.encode())
            return

        try:
            with open(full_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/webp")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "max-age=3600")
            self.send_header("ngrok-skip-browser-warning", "true")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def _proxy(self):
        """Proxy API calls to FastAPI backend."""
        target = BACKEND + self.path
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else None
            req = urllib.request.Request(
                target,
                data=body,
                method=self.command,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def end_headers(self):
        self.send_header("ngrok-skip-browser-warning", "true")
        self.send_header("X-Frame-Options", "ALLOWALL")
        self.send_header("Content-Security-Policy", "frame-ancestors *")
        super().end_headers()

    def log_message(self, format, *args):
        print(format % args)

print("Server running on http://localhost:3000")
HTTPServer(("", 3000), Handler).serve_forever()