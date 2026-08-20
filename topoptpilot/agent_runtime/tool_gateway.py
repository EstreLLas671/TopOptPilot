"""Loopback-only authenticated HTTP gateway for the Pi extension."""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from topoptpilot.schemas import ToolRequest


class ToolGateway:
    def __init__(self, service):
        self.service = service
        self.token = secrets.token_urlsafe(32)
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                if self.path != "/tool" or self.headers.get("x-topopt-token") != gateway.token:
                    return self._reply(403, {"ok": False, "error": "forbidden"})
                try:
                    size = min(int(self.headers.get("content-length", "0")), 1_000_000)
                    request = ToolRequest.model_validate_json(self.rfile.read(size))
                    result = gateway.service.tools.invoke(request.research_id, request.tool,
                                                          request.arguments)
                    self._reply(200, {"ok": True, "result": result})
                except Exception as exc:
                    self._reply(400, {"ok": False, "error": str(exc)})

            def _reply(self, code, value):
                body = json.dumps(value, default=str).encode("utf-8")
                self.send_response(code)
                self.send_header("content-type", "application/json; charset=utf-8")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True,
                                       name="topoptpilot-tool-gateway")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        if not self.thread.is_alive():
            self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
