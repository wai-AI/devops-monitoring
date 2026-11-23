import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path

        if path in ("/", "/healthz"):
            status, message = 200, "OK"
        elif path == "/error":
            status, message = 500, "Simulated server error"
        else:
            status, message = 404, "Not found"

        body = json.dumps({
            "status": status,
            "message": message
        }).encode()

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code="-", size="-"):
        path = urlsplit(self.path).path

        if path == "/healthz":
            return

        print(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "logging-demo",
            "method": self.command,
            "path": path,
            "status": int(code)
        }), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
