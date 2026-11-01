"""RepoVerse v3 — PRD → Repo generator.

Pure Python, no network, no LLM. Input is a structured PRD
(Markdown with sections, or a YAML/JSON dict); output is a complete
repo folder: README, pyproject, source modules, test stubs, CI,
LICENSE, CONTRIBUTING, SECURITY, CHANGELOG, .gitignore.

Generated code is boilerplate stubs for human review via a pull
request — never auto-merged. Full implementation logic from a PRD
is Future Work, not claimed as built here.

Reuses core/engine.py generate_module / generate_test_stub instead
of duplicating stub-generation logic.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.engine import generate_module, generate_test_stub

TEAM_LINE = (
    "Vikranth Reddy Hardageri (lead, 24WU0102008), "
    "Kavya Praktur (24WU0104038), "
    "Nischal Vir Medarmetla (24WU0104025), Member 5 = TBC"
)

GITIGNORE = """# Python
__pycache__/
*.py[cod]
*.pyc
.venv/
venv/
.pytest_cache/
# Secrets — never commit these
*.pem
*.key
.env
id_rsa*
credentials*
"""

CI_YML = """name: CI Pipeline
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
  pull-requests: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install pytest
        run: pip install pytest
      - name: Run tests
        run: python -m pytest tests/ -q
"""

CONTRIBUTING = """# Contributing

Team: {team}

- Open a pull request for every change; human review is required. Nothing is auto-merged.
- Run `python -m pytest tests/ -q` before submitting.
- Generated boilerplate from a PRD must be completed and tested before merging.
""".format(team=TEAM_LINE)

SECURITY = """# Security

Do not commit secrets. If a secret is committed, rotate it — deleting it from
history alone is not enough. Report security issues via a GitHub issue
marked `security`.
"""


TECH_KEYWORDS = {
    "react": "React", "next.js": "Next.js", "nextjs": "Next.js", "vue": "Vue",
    "angular": "Angular", "svelte": "Svelte", "tailwind": "Tailwind CSS",
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
    "node": "Node.js", "nodejs": "Node.js", "express": "Express",
    "typescript": "TypeScript", "javascript": "JavaScript",
    "python": "Python", "localstorage": "localStorage", "sqlite": "SQLite",
    "postgresql": "PostgreSQL", "mongodb": "MongoDB", "firebase": "Firebase",
}


def detect_tech(text: str) -> list[str]:
    """Auto-detect the stack from ANY PRD text — prose, bullets, or both.
    No dropdown choice needed: 'Use React, Tailwind CSS, and localStorage'
    in a prose Technology section must detect React + Tailwind + localStorage,
    not fall back to Python."""
    low = text.lower()
    found = []
    for key, label in TECH_KEYWORDS.items():
        if re.search(r"\b" + re.escape(key) + r"\b", low) and label not in found:
            found.append(label)
    return found


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower()
    if not slug:
        raise ValueError("project_name must contain at least one letter or digit")
    if slug[0].isdigit():
        slug = "project_" + slug
    return slug


def _feature_dict(item) -> dict:
    if isinstance(item, dict):
        return {"name": str(item.get("name", "")).strip(),
                "description": str(item.get("description", "")).strip()}
    return {"name": str(item).strip(), "description": ""}


def _endpoint_dict(item) -> dict:
    if isinstance(item, dict):
        return {"method": str(item.get("method", "GET")).upper(),
                "path": str(item.get("path", "")).strip(),
                "description": str(item.get("description", "")).strip()}
    # "GET /tasks - List tasks" or "GET /tasks: List tasks"
    m = re.match(r"\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)\s*[-:]\s*(.*)", str(item))
    if m:
        return {"method": m.group(1), "path": m.group(2), "description": m.group(3).strip()}
    return {"method": "GET", "path": str(item).strip(), "description": ""}


def _function_dict(item) -> dict:
    if isinstance(item, dict):
        return {"name": str(item.get("name", "")).strip(),
                "args": list(item.get("args", [])),
                "doc": str(item.get("doc", item.get("description", ""))).strip()}
    return {"name": str(item).strip(), "args": [], "doc": ""}


def _module_dict(item) -> dict:
    if isinstance(item, dict):
        return {"name": slugify(str(item.get("name", ""))),
                "functions": [_function_dict(f) for f in item.get("functions", [])]}
    return {"name": slugify(str(item)), "functions": []}


def normalize_prd(data: dict) -> dict:
    """Normalise a structured PRD dict. Raises ValueError if project_name is missing."""
    if not isinstance(data, dict):
        raise ValueError("PRD must be a dict")
    name = str(data.get("project_name", data.get("name", ""))).strip()
    if not name:
        raise ValueError("PRD is missing project_name")
    features = [_feature_dict(f) for f in data.get("features", []) if str(f).strip()]
    endpoints = [_endpoint_dict(e) for e in data.get("api_endpoints", []) if str(e).strip()]
    modules = [_module_dict(m) for m in data.get("modules", []) if str(m).strip()]
    if not modules and features:
        # One function per feature, in a module named after the project.
        funcs = [{"name": slugify(f["name"]), "args": [], "doc": f["description"]}
                 for f in features if f["name"]]
        modules = [{"name": slugify(name), "functions": funcs}]
    tech = data.get("tech_stack") or []
    if isinstance(tech, str):
        tech = [t.strip() for t in tech.split(",") if t.strip()]
    # Auto-detect: a PRD that says React/Tailwind/FastAPI/etc. must NOT
    # silently become Python just because its Technology section was prose.
    detected = data.get("detected_tech") or []
    for d in detected:
        if d not in tech:
            tech.append(d)
    if not tech:
        tech = ["python"]
    return {
        "project_name": name,
        "package": slugify(name),
        "description": str(data.get("description", "")).strip(),
        "tech_stack": [str(t).strip() for t in tech],
        "features": features,
        "api_endpoints": endpoints,
        "modules": modules,
    }


def parse_prd_markdown(text: str) -> dict:
    """Parse a Markdown PRD. Sections (case-insensitive):
    # Title, ## Description, ## Tech Stack, ## Features, ## API Endpoints, ## Modules.
    Features: '- **Name**: description' or '- Name: description' or '- Name'.
    Endpoints: '- GET /tasks: description' or '- GET /tasks - description'.
    Modules: '- module_name: func1(arg), func2()' or '- module_name'.
    """
    sections: dict[str, list[str]] = {}
    current = "title"
    sections[current] = []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level, heading = len(m.group(1)), m.group(2).strip()
            if level == 1:
                current = "title"
                sections[current] = [heading]
            else:
                current = heading.lower()
                sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    def bullets(section: str) -> list[str]:
        out = []
        for line in sections.get(section, []):
            m = re.match(r"^\s*[-*]\s+(.*)", line)
            if m:
                out.append(m.group(1).strip())
        return out

    title = (sections.get("title") or [""])[0].strip()
    # Strip a leading "PRD:" / "Project:" prefix if present.
    title = re.sub(r"^(prd|project)\s*:\s*", "", title, flags=re.I)
    description = " ".join(
        line.strip() for line in sections.get("description", [])
        if line.strip() and not line.strip().startswith("#")
    )
    # Also accept ## Overview as description, and Objective / Expected
    # Outcome prose (plain PRDs like Moodly have no Description section).
    if not description:
        description = " ".join(
            line.strip() for line in sections.get("overview", [])
            if line.strip()
        )
    if not description:
        parts = []
        for sec in ("objective", "expected outcome", "expected outcomes", "goal"):
            parts.extend(line.strip() for line in sections.get(sec, []) if line.strip())
        description = " ".join(parts)
    features = []
    for b in bullets("features"):
        m = re.match(r"\*\*(.+?)\*\*\s*[-:]\s*(.*)", b) or re.match(r"(.+?)\s*[-:]\s+(.*)", b)
        if m:
            features.append({"name": m.group(1).strip(), "description": m.group(2).strip()})
        else:
            features.append({"name": b, "description": ""})
    # Any PRD, not just ## Features PRDs: bullets under ANY other section
    # (Objective, Expected Outcome, ...) are also features.
    if not features:
        for sec, lines in sections.items():
            if sec in ("title", "features", "tech stack", "technology",
                       "api endpoints", "modules", "description", "overview"):
                continue
            for b in bullets(sec):
                m = re.match(r"\*\*(.+?)\*\*\s*[-:]\s*(.*)", b) or re.match(r"(.+?)\s*[-:]\s+(.*)", b)
                if m:
                    features.append({"name": m.group(1).strip(), "description": m.group(2).strip()})
                else:
                    features.append({"name": b, "description": ""})
    # Still none (pure prose PRD, e.g. Moodly): derive features from the
    # prose itself — "allows users to <phrase>" and comma/and lists after
    # "with" in the Objective / Expected Outcome text. These come from the
    # user's own words, not a hardcoded app list.
    if not features:
        prose = " ".join(
            line.strip() for sec in ("objective", "expected outcome", "expected outcomes", "description", "overview")
            for line in sections.get(sec, []) if line.strip()
        )
        prose = re.sub(r"\*\*", "", prose)
        seen = set()
        def add_feature(name, desc=""):
            name = re.sub(r"^(a|an|the)\s+", "", name.strip(), flags=re.I).strip(" .")
            if not name or len(name) > 60:
                return
            key = name.lower()
            if key not in seen:
                seen.add(key)
                features.append({"name": name, "description": desc})
        m = re.search(r"allows users to\s+([^.]+)", prose, flags=re.I)
        if m:
            add_feature(m.group(1))
        m = re.search(r"\bwith\s+([^.]+)", prose, flags=re.I)
        if m:
            for part in re.split(r",|\band\b", m.group(1)):
                add_feature(part)
        if not features:
            for sent in re.split(r"\.\s+", prose):
                sent = sent.strip()
                if sent:
                    add_feature(sent[:60])
    tech_raw = bullets("tech stack") or bullets("technology") or []
    tech = []
    for b in tech_raw:
        tech.extend(t.strip() for t in b.split(",") if t.strip())
    # Prose Technology section (e.g. 'Use React, Tailwind CSS, and
    # localStorage.') — detect keywords from its lines too.
    for sec in ("technology", "tech stack"):
        for line in sections.get(sec, []):
            tech.extend(detect_tech(line))
    detected = detect_tech(text)
    endpoints = [_endpoint_dict(b) for b in bullets("api endpoints")]
    modules = []
    for b in bullets("modules"):
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)", b)
        if not m:
            modules.append({"name": b, "functions": []})
            continue
        funcs = []
        for part in m.group(2).split(","):
            part = part.strip()
            if not part:
                continue
            fm = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)", part)
            if fm:
                args = [a.strip() for a in fm.group(2).split(",") if a.strip()]
                funcs.append({"name": fm.group(1), "args": args, "doc": ""})
            else:
                funcs.append({"name": part, "args": [], "doc": ""})
        modules.append({"name": m.group(1), "functions": funcs})
    return normalize_prd({
        "project_name": title,
        "description": description,
        "tech_stack": tech,
        "detected_tech": detected,
        "features": features,
        "api_endpoints": endpoints,
        "modules": modules,
    })


def parse_prd_file(path) -> dict:
    """Parse a PRD file: .md → Markdown, .json/.yaml/.yml → structured dict."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix in (".json", ".yaml", ".yml"):
        if suffix == ".json":
            data = json.loads(text)
        else:
            import yaml  # PyYAML, used by the v3 workflow checks as well
            data = yaml.safe_load(text)
        return normalize_prd(data)
    return parse_prd_markdown(text)


def _readme(prd: dict) -> str:
    lines = [f"# {prd['project_name']}", "", prd["description"], "",
             "## Features", ""]
    for f in prd["features"]:
        lines.append(f"- **{f['name']}**: {f['description']}" if f["description"] else f"- {f['name']}")
    if prd["api_endpoints"]:
        lines += ["", "## API Endpoints", "",
                  "| Method | Path | Description |", "| --- | --- | --- |"]
        for e in prd["api_endpoints"]:
            lines.append(f"| {e['method']} | {e['path']} | {e['description']} |")
    lines += ["", "## Modules", ""]
    for m in prd["modules"]:
        lines.append(f"- `{m['name']}`: " + ", ".join(f["name"] for f in m["functions"]))
    lines += ["", "## Tech Stack", "",
              ", ".join(prd["tech_stack"]), "",
              "## Team", "", TEAM_LINE, "",
              "## Run", "",
              "```bash", "python -m pytest tests/ -q", "```", "",
              "## Note", "",
              "This repo was generated from a PRD as boilerplate stubs for human "
              "review via a pull request — never auto-merged. Full implementation "
              "logic from the PRD is Future Work, not claimed as built here."]
    return "\n".join(lines) + "\n"


def _pyproject(prd: dict) -> str:
    return (
        "[build-system]\n"
        "requires = [\"setuptools\"]\n"
        "build-backend = \"setuptools.build_meta\"\n\n"
        "[project]\n"
        f"name = \"{prd['package']}\"\n"
        "version = \"0.1.0\"\n"
        f"description = \"{prd['description']}\"\n"
        "requires-python = \">=3.10\"\n"
        "dependencies = []\n\n"
        "[tool.setuptools.packages.find]\n"
        "where = [\"src\"]\n"
    )


def generate_repo(prd: dict, output_dir) -> list[Path]:
    """Generate a full repo folder from a normalised PRD dict. Returns created files."""
    prd = normalize_prd(prd)
    out = Path(output_dir)
    pkg = prd["package"]
    created: list[Path] = []

    def write(rel: str, content: str) -> None:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        created.append(p)

    write("README.md", _readme(prd))
    write("pyproject.toml", _pyproject(prd))
    write("requirements.txt", "pytest\n")
    write("src/__init__.py", "")
    write(f"src/{pkg}/__init__.py", f'"""Generated from PRD: {prd["project_name"]}."""\n')
    for mod in prd["modules"]:
        write(f"src/{pkg}/{mod['name']}.py", generate_module(mod["name"], mod["functions"]))
        qualified = f"src.{pkg}.{mod['name']}"
        write(f"tests/test_{mod['name']}.py",
              generate_test_stub(qualified, mod["functions"]))
    write("tests/__init__.py", "")
    # Auto-detected stack files — the output follows the PRD's own stack,
    # not a manual dropdown. React PRDs get a React app, FastAPI PRDs get
    # a FastAPI app, otherwise the Python scaffold.
    tech_low = [x.lower() for x in prd["tech_stack"]]
    if any("react" in x or "next" in x for x in tech_low):
        feat_js = ", ".join(f'"{f["name"]}"' for f in prd["features"]) or '"Items"'
        write("package.json",
              '{\n  "name": "%s",\n  "version": "0.1.0",\n  "private": true,\n'
              '  "dependencies": { "react": "^18.0.0", "react-dom": "^18.0.0" },\n'
              '  "scripts": { "start": "vite" }\n}\n' % prd["package"])
        write("src/App.jsx",
              'import { useState } from "react";\n\n'
              f'const FEATURES = [{feat_js}];\n\n'
              'export default function App() {\n'
              '  const [items, setItems] = useState(() => JSON.parse(localStorage.getItem("' + pkg + '_items") || "[]"));\n'
              '  const [text, setText] = useState("");\n'
              '  const add = () => { if (!text.trim()) return; const next = [...items, text]; setItems(next); localStorage.setItem("' + pkg + '_items", JSON.stringify(next)); setText(""); };\n'
              '  return (<div><h1>' + prd["project_name"] + '</h1>{FEATURES.map(f => <div key={f}>{f}</div>)}'
              '<input value={text} onChange={e => setText(e.target.value)} placeholder="Add an entry…" />'
              '<button onClick={add}>Add</button><ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>);\n}\n')
    if any("fastapi" in x for x in tech_low):
        write("main.py",
              'from fastapi import FastAPI\n\napp = FastAPI(title="' + prd["project_name"] + '")\n\n'
              '@app.get("/")\ndef root():\n    return {"project": "' + prd["project_name"] + '"}\n')
        write("requirements.txt", "fastapi\nuvicorn\npytest\n")
    if any(x == "flask" for x in tech_low):
        write("app.py",
              'from flask import Flask\n\napp = Flask(__name__)\n\n'
              '@app.route("/")\ndef index():\n    return "' + prd["project_name"] + '"\n')
        write("requirements.txt", "flask\npytest\n")
    # A real, usable web app for ANY PRD — not just the 6 starter examples.
    # Generic localStorage CRUD over the PRD's features, so a prose PRD
    # (Moodly, etc.) still produces an app you can open and use, not only
    # Python stubs. Feature names come from the PRD, never hardcoded.
    feat_names = [f["name"] for f in prd["features"]] or ["Items"]
    feat_cards = "\n".join(
        f'      <div class="card"><b>{n}</b><p>{n} — manage it below.</p></div>' for n in feat_names
    )
    app_html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{prd["project_name"]}</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-950 text-white min-h-screen p-6">
<h1 class="text-3xl font-bold">{prd["project_name"]}</h1>
<p class="text-slate-400 mt-2">{prd["description"]}</p>
<div class="grid gap-4 mt-6 sm:grid-cols-2 lg:grid-cols-3">{feat_cards}</div>
<div class="mt-8 bg-slate-900 rounded-2xl p-4">
<input id="item" class="w-full bg-slate-800 rounded-xl p-3" placeholder="Add an entry…">
<button onclick="addItem()" class="mt-3 bg-amber-400 text-black font-bold px-5 py-2 rounded-xl">Add</button>
<ul id="list" class="mt-4 space-y-2"></ul></div>
<script>
const KEY = "{pkg}_items";
function render(){{ const items = JSON.parse(localStorage.getItem(KEY) || "[]");
document.getElementById("list").innerHTML = items.map((x, i) =>
  `<li class="bg-slate-800 rounded-xl p-3 flex justify-between"><span>${{x}}</span><button onclick="delItem(${{i}})">Delete</button></li>`).join(""); }}
function addItem(){{ const v = document.getElementById("item").value.trim(); if (!v) return;
const items = JSON.parse(localStorage.getItem(KEY) || "[]"); items.push(v);
localStorage.setItem(KEY, JSON.stringify(items)); document.getElementById("item").value = ""; render(); }}
function delItem(i){{ const items = JSON.parse(localStorage.getItem(KEY) || "[]"); items.splice(i, 1);
localStorage.setItem(KEY, JSON.stringify(items)); render(); }}
render();
</script></body></html>
'''
    write("app/index.html", app_html)
    write(".github/workflows/ci.yml", CI_YML)
    write("LICENSE", "MIT License\n\nCopyright (c) 2026 " + TEAM_LINE.split(" (lead")[0] + "\n")
    write("CONTRIBUTING.md", CONTRIBUTING)
    write("SECURITY.md", SECURITY)
    write("CHANGELOG.md", "# Changelog\n\n## Unreleased\n\n- Initial repo generated from PRD\n")
    write(".gitignore", GITIGNORE)
    return created
