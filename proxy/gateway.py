"""Placeholder for the self-hosted rotating proxy gateway (PLAN.md §4.8).

Phase A only needs this container to build and answer a health check so the
compose stack is green end-to-end. The real rotating forward-proxy (exit-IP
pool, per-batch affinity, health-check/eviction) is Phase B scope.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body = b'{"status":"ok","gateway":"stub"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8888), HealthHandler).serve_forever()
