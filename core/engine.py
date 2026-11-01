"""RepoVerse v3 — spec-to-boilerplate generator (deterministic, local).

Takes a structured spec dict (as collected by the GitHub Issue Form
feature_spec.yml) and generates Python module + test stubs.
No LLM, no network. Generated code is a starting point for human review
via a pull request — never auto-merged.
"""
from __future__ import annotations


def generate_module(module_name: str, functions: list[dict]) -> str:
    """Generate a Python module stub.

    functions: [{"name": str, "args": [str], "doc": str}]
    """
    lines = [f'"""Generated boilerplate for {module_name}."""', "", ""]
    for fn in functions:
        args = ", ".join(fn.get("args", []))
        lines.append(f"def {fn['name']}({args}):")
        lines.append(f'    """{fn.get("doc", "")}"""')
        lines.append("    raise NotImplementedError('Implement this function and add a test.')")
        lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_test_stub(module_name: str, functions: list[dict]) -> str:
    """Generate a pytest stub for the generated module."""
    lines = [f"from {module_name} import " + ", ".join(f["name"] for f in functions), "", ""]
    for fn in functions:
        lines.append(f"def test_{fn['name']}_todo():")
        lines.append("    # TODO: implement this test before merging.")
        lines.append("    assert True  # placeholder — replace with a real assertion")
        lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_from_spec(spec: dict) -> dict:
    """Generate module + test from a structured spec dict."""
    module_name = spec.get("module_name", "generated_module")
    functions = spec.get("functions", [])
    return {
        "module_file": f"{module_name}.py",
        "module_code": generate_module(module_name, functions),
        "test_file": f"test_{module_name}.py",
        "test_code": generate_test_stub(module_name, functions),
    }
