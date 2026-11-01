"""Auto-create a GitHub repo from generated files, server-side, stdlib only.

This is the site's repo step, per the user's Nov 1 instruction:
Vercel is SKIPPED on this site. When a PRD is given, the site itself
creates the GitHub repo and pushes the generated files, then shows
the repo link. No chat/WhatsApp paste is needed for that step.

Token: read ONLY from os.environ["GITHUB_TOKEN"] (set by the site
owner in the Vercel dashboard: ai-agent-bot-app -> Settings ->
Environment Variables, then redeploy). The token is never logged,
never returned, never written to a file. If it is absent, callers
must say so honestly and must NOT claim a repo was created.

Method: GitHub REST API, git-trees flow (one commit for all files),
so a 17-file repo is a handful of API calls, not 17 uploads:
  GET /user -> login
  POST /user/repos (or reuse the existing repo on 422)
  POST /repos/{owner}/{repo}/git/blobs (one per file)
  POST /repos/{owner}/{repo}/git/trees
  POST /repos/{owner}/{repo}/git/commits
  POST or PATCH /repos/{owner}/{repo}/git/refs/heads/main
Any failure returns (None, error_string) — callers show the error,
never a guessed link.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request

API = "https://api.github.com"
TIMEOUT = 15


def _token() -> str:
    return (os.environ.get("GITHUB_TOKEN", "")
            or os.environ.get("GH_TOKEN", "")).strip()


def slug(name: str) -> str:
    s = (name or "app").strip().lower()
    s = re.sub(r"^(prd|project)\s*:\s*", "", s)
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "app"


def _req(method: str, path: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + _token())
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "ai-agent-bot-app")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except Exception:
            body = {}
        return e.code, body


def create_repo_with_files(project_name: str, description: str,
                           files: dict) -> tuple:
    """files: {relative_path: bytes}. Returns (repo_url_or_None, error_or_None).

    error is None on success. On a missing token it is the exact
    string "token_missing" so the caller can show the setup step.
    """
    token = _token()
    if not token:
        return None, "token_missing"
    if not files:
        return None, "no files generated, nothing to push"
    status, me = _req("GET", "/user")
    if status != 200 or not me.get("login"):
        return None, "GitHub login check failed (HTTP %s)" % status
    owner = me["login"]
    repo = slug(project_name)
    status, created = _req("POST", "/user/repos", {
        "name": repo,
        "description": (description or "")[:350],
        "private": False,
        "auto_init": False,
    })
    existed = False
    if status == 422:
        # Repo name already taken under this account: reuse it and
        # push a new commit on top, rather than inventing a new name.
        status2, existing = _req("GET", "/repos/%s/%s" % (owner, repo))
        if status2 != 200 or not existing.get("html_url"):
            return None, "repo name %s already exists and could not be read" % repo
        existed = True
    elif status not in (200, 201):
        msg = created.get("message") if isinstance(created, dict) else ""
        return None, "repo creation failed (HTTP %s%s)" % (
            status, (": " + msg) if msg else "")
    # Blobs.
    tree = []
    for path in sorted(files):
        content = files[path]
        if isinstance(content, str):
            content = content.encode()
        status, blob = _req("POST", "/repos/%s/%s/git/blobs" % (owner, repo), {
            "content": base64.b64encode(content).decode(),
            "encoding": "base64",
        })
        if status not in (200, 201) or not blob.get("sha"):
            return None, "blob upload failed for %s (HTTP %s)" % (path, status)
        tree.append({"path": path, "mode": "100644",
                     "type": "blob", "sha": blob["sha"]})
    # Base commit, if the repo already has one.
    parents = []
    if existed:
        status, ref = _req("GET", "/repos/%s/%s/git/ref/heads/main" % (owner, repo))
        if status == 200 and ref.get("object", {}).get("sha"):
            parents = [ref["object"]["sha"]]
    status, tree_resp = _req("POST", "/repos/%s/%s/git/trees" % (owner, repo),
                             {"tree": tree})
    if status not in (200, 201) or not tree_resp.get("sha"):
        return None, "tree creation failed (HTTP %s)" % status
    status, commit = _req("POST", "/repos/%s/%s/git/commits" % (owner, repo), {
        "message": "Build from PRD: %s" % project_name,
        "tree": tree_resp["sha"],
        "parents": parents,
    })
    if status not in (200, 201) or not commit.get("sha"):
        return None, "commit creation failed (HTTP %s)" % status
    sha = commit["sha"]
    if parents:
        status, _ = _req("PATCH", "/repos/%s/%s/git/refs/heads/main" % (owner, repo),
                         {"sha": sha, "force": False})
        if status not in (200, 201):
            return None, "branch update failed (HTTP %s)" % status
    else:
        status, _ = _req("POST", "/repos/%s/%s/git/refs" % (owner, repo),
                         {"ref": "refs/heads/main", "sha": sha})
        if status not in (200, 201):
            return None, "branch creation failed (HTTP %s)" % status
    return "https://github.com/%s/%s" % (owner, repo), None
