"""Server-side builds store backed by Vercel Blob (stdlib only, no SDK).

Design (kept deliberately simple so it can be verified by curl):
- One blob file, pathname ``builds/builds.json``, holding
  ``{"builds": [record, ...]}`` with newest first.
- A record is a real build only: {name, link, file_count, stack,
  features, created_at, prd_title, desc}. No seed beyond the 3 real
  builds that already exist (Notes App, Moodly, FocusFlow).
- Reads: list blobs with prefix ``builds/`` (token required), find
  ``builds/builds.json``, download it (public store, no token needed
  for the download itself). If the blob is missing or the token is
  absent, return the seed list with persisted=False — never invent
  a saved build.
- Writes: read current list (seed if none persisted yet), drop any
  existing record with the same normalised name, prepend the new
  record, cap at 50, PUT the whole file back, then re-read and
  confirm the new record is present. Any failure returns False;
  callers must never claim a build was saved when this returns False.
- The token is read ONLY from os.environ["BLOB_READ_WRITE_TOKEN"]
  (wired automatically by Vercel when the Blob store was created
  for this project). It is never logged, never returned, never
  written to a file.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

BLOB_BASE = "https://blob.vercel-storage.com"
PATHNAME = "builds/builds.json"
TIMEOUT = 5

# Seed: only the 3 real builds, exactly as in builds.json. File counts
# for Moodly/FocusFlow are the verified upload counts (17 each).
# Notes App's generated file count is not on record, so it is None
# rather than an invented number.
SEED_BUILDS = [
    {
        "name": "FocusFlow - Pomodoro Study Timer",
        "link": "https://focusflow-app-hvrgaming2705s-projects.vercel.app/",
        "desc": "Pomodoro study timer built from a PRD on this site.",
        "file_count": 17,
        "stack": ["React", "Tailwind CSS", "localStorage"],
        "features": ["session tracking", "break management", "productivity dashboard"],
        "created_at": None,
        "prd_title": "FocusFlow - Pomodoro Study Timer",
    },
    {
        "name": "Moodly - Mood Tracker App",
        "link": "https://moodly-app-hvrgaming2705s-projects.vercel.app/",
        "desc": "Mood tracker app built from a PRD on this site.",
        "file_count": 17,
        "stack": ["React", "Tailwind CSS", "localStorage"],
        "features": ["daily entries", "mood history", "visual statistics"],
        "created_at": None,
        "prd_title": "Moodly - Mood Tracker App",
    },
    {
        "name": "Notes App",
        "link": "https://notes-app-prd.vercel.app/",
        "desc": "Built from a PRD: lightweight notes, polished UI, rounded cards, localStorage, no login. This is the output, on this website — not just in chat.",
        "file_count": None,
        "stack": [],
        "features": [],
        "created_at": None,
        "prd_title": "Notes App",
    },
]


def _norm(name: str) -> str:
    n = (name or "").strip().lower()
    n = re.sub(r"^(prd|project)\s*:\s*", "", n)
    n = n.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", n).strip()


def _token() -> str:
    return os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()


def _req(method: str, url: str, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, method=method)
    token = _token()
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def _find_builds_url() -> str | None:
    """List blobs with prefix builds/ and return the builds.json URL, or None."""
    try:
        with _req("GET", BLOB_BASE + "?prefix=builds/") as resp:
            payload = json.loads(resp.read().decode() or "{}")
    except Exception:
        return None
    blobs = payload.get("blobs") or payload.get("items") or []
    for b in blobs:
        if isinstance(b, dict) and (b.get("pathname") == PATHNAME
                                    or (b.get("url") or "").endswith("/" + PATHNAME)):
            return b.get("url")
    return None


def get_builds():
    """Return (builds, persisted). persisted=False means seed fallback."""
    url = _find_builds_url()
    if not url:
        return list(SEED_BUILDS), False
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode() or "{}")
        builds = payload.get("builds")
        if isinstance(builds, list) and builds:
            return builds, True
    except Exception:
        pass
    return list(SEED_BUILDS), False


def build_record(name, file_count, stack, features, link=None, desc=""):
    return {
        "name": name,
        "link": link,
        "desc": desc,
        "file_count": file_count,
        "stack": list(stack or []),
        "features": [f.get("name") if isinstance(f, dict) else str(f)
                     for f in (features or [])],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prd_title": name,
    }


def save_build(record) -> bool:
    """Persist one build record. Returns True only if a re-read confirms it."""
    if not _token():
        return False
    try:
        current, _persisted = get_builds()
        name = _norm(record.get("name", ""))
        kept = [b for b in current if _norm(b.get("name", "")) != name]
        builds = [record] + kept[:49]
        body = json.dumps({"builds": builds}).encode()
        req = urllib.request.Request(
            BLOB_BASE + "/" + PATHNAME, data=body, method="PUT")
        req.add_header("Authorization", "Bearer " + _token())
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            resp.read()
        # Verify: re-read must show this record newest.
        fresh, persisted = get_builds()
        return bool(persisted and fresh
                    and _norm(fresh[0].get("name", "")) == name)
    except Exception:
        return False
