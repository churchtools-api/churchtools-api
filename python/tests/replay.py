"""Local HTTP server answering with responses recorded from a real instance.

The live tests record them into `fixtures/recorded/<operationId>.json`. With
`op` set, every request gets that operation's recording; otherwise the
recording is chosen by method and path. Unrecorded requests get HTTP 501.
"""

from __future__ import annotations

import json
import re
import threading
import typing as _t
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORDED = ROOT / "fixtures" / "recorded"
CATALOG = json.loads((ROOT / "python" / "tests" / "live" / "operations.json").read_text())


def recorded(op_id: str) -> bytes | None:
    path = RECORDED / f"{op_id}.json"
    if not path.exists():
        return None
    return json.dumps(json.loads(path.read_text())["body"]).encode()


def _pattern(path: str) -> re.Pattern[str]:
    return re.compile("^/api" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$")


# Most literal segments first, so /persons/birthdays wins over /persons/{id}.
ROUTES = sorted(
    ((e["method"], _pattern(e["path"]), e["op_id"]) for e in CATALOG),
    key=lambda r: (r[1].pattern.count("[^/]+"), -len(r[1].pattern)),
)


class ReplayServer:
    def __init__(self) -> None:
        self.op: str | None = None
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: _t.Any) -> None:
                pass

            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                path = self.path.split("?")[0]
                op = server.op or next((o for m, rx, o in ROUTES if m == self.command and rx.match(path)), None)
                body = recorded(op) if op else None
                data = body if body is not None else b'{"message": "no recording for this request"}'
                self.send_response(200 if body is not None else 501)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _answer

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._http.server_port}"
        threading.Thread(target=self._http.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._http.shutdown()
