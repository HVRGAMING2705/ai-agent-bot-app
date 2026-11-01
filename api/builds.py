"""Vercel serverless function: GET /api/builds -> saved builds, newest first.

Reads from the Vercel Blob builds store (core/blobstore.py). If Blob is
unavailable, returns the real seed builds with persisted=false so the
frontend never presents a seed list as if it were saved.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.blobstore import get_builds


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        builds, persisted = get_builds()
        out = json.dumps({
            "builds": builds,
            "persisted": persisted,
            "source": "blob" if persisted else "seed",
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass
