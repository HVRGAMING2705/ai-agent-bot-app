"""Vercel serverless function: POST /api/chat {message} -> {reply}
Stateful: every repo build is saved to the Vercel Blob builds store
(core/blobstore.py) and listed by GET /api/builds, so builds persist
across reloads and deploys. Generated files themselves are still
returned in the reply (copy/download if you want a local copy).
"""
import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import agent_reply, HAS_REPOVERSE


def make_repo_text(prd_text):
    if not HAS_REPOVERSE:
        return ("Repo generator not available on this deployment. "
                "Run the local app (python app.py) for full repo generation.")
    from core.prd_generator import parse_prd_markdown, generate_repo
    out = Path(tempfile.mkdtemp()) / "repo"
    prd = parse_prd_markdown(prd_text)
    files = generate_repo(prd, out)
    readme = (out / "README.md").read_text() if (out / "README.md").exists() else ""
    def _rel(f):
        p = Path(f)
        try:
            return str(p.relative_to(out))
        except Exception:
            return p.name
    names = "\n".join(f"- {_rel(f)}" for f in sorted(files, key=lambda x: _rel(x)))
    stack = ", ".join(prd.get("tech_stack", []))
    # Site repo step: Vercel skipped. Auto-create the GitHub repo.
    repo_url, github_line = _github_step(prd, out, files)
    try:
        from core.blobstore import build_record, save_build
        saved = save_build(build_record(
            prd.get('project_name', 'Unnamed'), len(files),
            prd.get("tech_stack", []), prd.get("features", []), link=repo_url))
    except Exception:
        saved = False
    return (f"Repo generated: {prd.get('project_name', 'Unnamed')} — {len(files)} files.\n"
            f"Detected stack (auto, from your PRD): {stack}.\n"
            f"{github_line}\n"
            f"Saved on this site: {'yes — listed in My Builds, even after reload.' if saved else 'no — Blob store unavailable for this build, output below is still complete.'}\n{names}\n\n"
            f"--- README.md ---\n{readme}")


def _github_step(prd, out, files):
    """Try the site's auto GitHub-repo step. Returns (url_or_None, line)."""
    try:
        from core.github_repo import create_repo_with_files
        payload = {}
        for f in files:
            p = Path(f)
            try:
                rel = str(p.relative_to(out))
            except Exception:
                rel = p.name
            payload[rel] = p.read_bytes()
        desc = ""
        try:
            desc = " ".join(str(prd.get("description", "")).split())[:350]
        except Exception:
            desc = ""
        url, err = create_repo_with_files(
            prd.get('project_name', 'Unnamed'), desc, payload)
        if url:
            return url, f"GitHub repo: {url} — created automatically from this PRD. Vercel skipped."
        if err == "token_missing":
            return None, ("GitHub repo: NOT created — GITHUB_TOKEN is not set on this site. "
                          "Owner step: Vercel dashboard -> ai-agent-bot-app -> Settings -> "
                          "Environment Variables -> add GITHUB_TOKEN (fine-grained PAT, public repos, "
                          "contents write), redeploy, then rebuild this PRD. Files above are complete. "
                          "Vercel skipped.")
        return None, f"GitHub repo: NOT created — {err}. Files above are complete. Vercel skipped."
    except Exception as e:
        return None, f"GitHub repo: NOT created — {e}. Files above are complete. Vercel skipped."



def build_stream(prd_text):
    """Yield one NDJSON event per REAL generation phase, in order.
    This replaces the old fixed 500ms timer: the frontend advances a step
    only when one of these events actually arrives from the server, and
    each event names the real file/phase being written at that moment.
    Generation itself is fast (milliseconds per file), so events arrive
    as fast as the server writes them — no artificial delay is added.
    """
    from core.prd_generator import parse_prd_markdown, generate_repo
    import tempfile, json as _json, time as _time
    _t0 = _time.monotonic()
    def ev(pct, label, done=False, reply=None):
        d = {"pct": pct, "label": label, "done": done,
             "t_ms": int((_time.monotonic() - _t0) * 1000)}
        if reply is not None:
            d["reply"] = reply
        return (_json.dumps(d) + "\n").encode()
    yield ev(2, "Reading PRD — title, description, features")
    prd = parse_prd_markdown(prd_text)
    yield ev(5, f"Parsed PRD: {prd.get('project_name', 'Unnamed')}")
    stack = ", ".join(prd.get("tech_stack", []))
    yield ev(11, f"Detected stack (auto): {stack}")
    out = Path(tempfile.mkdtemp()) / "repo"
    yield ev(15, "Scaffolding — creating project folder")
    files = generate_repo(prd, out)
    # generate_repo already wrote everything; report the REAL files, in
    # order, as the progress steps — one step per real file written.
    def _rel(f):
        p = Path(f)
        try:
            return str(p.relative_to(out))
        except Exception:
            return p.name
    names = sorted(_rel(f) for f in files)
    n = len(names)
    for i, name in enumerate(names):
        pct = 19 + int((i + 1) * (93 - 19) / max(n, 1))
        yield ev(pct, f"Writing {name}")
    readme = (out / "README.md").read_text() if (out / "README.md").exists() else ""
    yield ev(95, "Creating GitHub repo — Vercel skipped, repo only")
    repo_url, github_line = _github_step(prd, out, files)
    yield ev(97, "GitHub repo: " + (repo_url or "not created — see output below"))
    yield ev(99, "Saving build to this site")
    try:
        from core.blobstore import build_record, save_build
        saved = save_build(build_record(
            prd.get('project_name', 'Unnamed'), len(files),
            prd.get("tech_stack", []), prd.get("features", []), link=repo_url))
    except Exception:
        saved = False
    reply = (f"Repo generated: {prd.get('project_name', 'Unnamed')} — {len(files)} files.\n"
             f"Detected stack (auto, from your PRD): {stack}.\n"
             f"{github_line}\n"
             f"Saved on this site: {'yes — listed in My Builds, even after reload.' if saved else 'no — Blob store unavailable for this build, output below is still complete.'}\n"
             + "\n".join(f"- {nm}" for nm in names) + "\n\n--- README.md ---\n" + readme)
    yield ev(100, "Done — output ready below, on this website", done=True, reply=reply)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length).decode() or "{}")
        except Exception:
            body = {}
        message = body.get("message", "")
        low = message.strip().lower()
        # ANY paste counts as a repo build, unless it is one of the
        # explicit tool commands (help / health: / list files:).
        # Plain PRDs (e.g. Moodly, no 'make repo:' prefix, no Features
        # heading, even short ones) used to fall through to
        # "I didn't understand" and the frontend flow stopped at 11%.
        is_prd = not (low in ("help", "hi", "hello")
                      or low.startswith("health:") or low.startswith("list files:"))
        if is_prd:
            prd_text = message.strip()[len("make repo:"):].strip() if low.startswith("make repo:") else message.strip()
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for chunk in build_stream(prd_text):
                    try:
                        self.wfile.write(chunk); self.wfile.flush()
                    except Exception:
                        break
                return
            reply = make_repo_text(prd_text)
        else:
            reply = agent_reply(message)
        out = json.dumps({"reply": reply}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        out = json.dumps({"reply": "Send a POST with {\"message\": \"help\"}"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass
