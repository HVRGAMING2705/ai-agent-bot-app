"""AI Agent Bot — agent loop, stdlib only, no API key needed.

How it works:
  User message -> Agent decides a tool -> Tool runs -> Agent replies with result.
  No LLM is required. If OPENAI_API_KEY is set, the reply wording can be
  upgraded by that API later — the tools work without it, and the bot never
  claims an LLM ran when it did not.

Tools built in:
  - make_repo: give a PRD description, it writes a repo folder
  - health: run a RepoVerse health check on a folder
  - list_files: list files in a folder
  - help: show what the bot can do
"""
import os
import sys
from pathlib import Path

# Reuse RepoVerse v3 generator if present, otherwise fall back to a tiny local generator
REPOVERSE = Path(__file__).resolve().parent  # bundled core/ in vercel-app, else local RepoVerse
if str(REPOVERSE) not in sys.path and REPOVERSE.exists():
    sys.path.insert(0, str(REPOVERSE))

try:
    from core.prd_generator import parse_prd_markdown, generate_repo
    HAS_REPOVERSE = True
except Exception:
    HAS_REPOVERSE = False


def tool_make_repo(prd_text, output_dir):
    """Make a repo from a PRD description."""
    out = Path(output_dir)
    if HAS_REPOVERSE:
        prd = parse_prd_markdown(prd_text)
        files = generate_repo(prd, out)
        return f"Repo generated: {prd.get('project_name', 'Unnamed')} — {len(files)} files in {out}"
    # Fallback: minimal repo, no RepoVerse needed
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(f"# Generated Repo\n\n{prd_text}\n")
    (out / "main.py").write_text('print("Hello from the generated repo")\n')
    return f"Repo generated (fallback) — 2 files in {out}"


def tool_list_files(folder):
    p = Path(folder)
    if not p.exists():
        return f"Folder not found: {folder}"
    files = [str(f.relative_to(p)) for f in sorted(p.rglob("*")) if f.is_file()]
    return "\n".join(files) if files else "Folder is empty."


def tool_health(folder):
    p = Path(folder)
    checks = {
        "README.md": (p / "README.md").exists(),
        "LICENSE": (p / "LICENSE").exists(),
        "tests/": (p / "tests").exists(),
        ".github/workflows/": (p / ".github/workflows").exists(),
    }
    score = int(sum(checks.values()) * 100 / len(checks))
    lines = [f"[{'x' if v else ' '}] {k}" for k, v in checks.items()]
    return f"Health: {score}/100\n" + "\n".join(lines)


def agent_reply(message):
    """One agent turn: decide tool, run it, reply."""
    msg = message.strip()
    low = msg.lower()
    if low in ("help", "hi", "hello"):
        return ("I am the AI Agent Bot. I can:\n"
                "- make repo: <PRD description>  (writes a repo folder)\n"
                "- health: <folder>  (checks README, LICENSE, tests, workflows)\n"
                "- list files: <folder>\n"
                "Example: 'make repo: # Task App\\n\\n## Features\\n- Create task'")
    if low.startswith("make repo:"):
        prd = msg[len("make repo:"):].strip()
        out = Path.home() / "workspace/ai-agent-bot-app/output_repo"
        return tool_make_repo(prd, out)
    # PRD pasted without the "make repo:" prefix (as in the user's screenshot):
    # if it looks like a PRD (title + Features section), treat it as make-repo.
    if ("## features" in low or "### features" in low or "features" in low
            or msg.strip().startswith("#") or len(msg.strip()) > 80):
        out = Path.home() / "workspace/ai-agent-bot-app/output_repo"
        return tool_make_repo(msg, out)
    if low.startswith("health:"):
        return tool_health(msg[len("health:"):].strip())
    if low.startswith("list files:"):
        return tool_list_files(msg[len("list files:"):].strip())
    return ("I didn't understand that tool call. Type 'help'.\n"
            "Try: make repo: # My App\n\n## Features\n- Do thing")
