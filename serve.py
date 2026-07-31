#!/usr/bin/env python3
"""Serve the IPO Desk frontend + output JSON from the project root."""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # Avoid stale JSON while iterating on the scraper.
        if self.path.endswith(".json"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        sys_stderr_write = __import__("sys").stderr.write
        sys_stderr_write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve IPO Desk at http://localhost:PORT")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", args.port), Handler) as httpd:
        print(f"IPO Desk -> http://localhost:{args.port}/web/")
        print(f"JSON     -> http://localhost:{args.port}/output/ipos.json")
        print("Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
