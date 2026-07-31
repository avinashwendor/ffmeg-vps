#!/usr/bin/env python3
"""Static checks on a generated n8n workflow.

The failure that motivated this: a Python format-string slip emitted
`${{escapeHtml(x)}}` into a Code node, which is a JavaScript SyntaxError. n8n
only surfaces that when the node runs, so `/compose` looked like it did nothing
at all. Every Code node now gets parsed by node(1) at build time instead.

    python3 build/validate_workflow.py [workflow.json ...]
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from paths import LINKEDIN_WORKFLOW_JSON, MAIN_WORKFLOW_JSON

TRIGGER_TYPES = (
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.telegramTrigger",
    "n8n-nodes-base.executeWorkflowTrigger",
    "n8n-nodes-base.manualTrigger",
)


def check_js(name, code, errors):
    """n8n wraps Code node bodies in an async function, so mirror that."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write("async function __n8nNode() {\n")
        f.write(code)
        f.write("\n}\n")
        path = f.name
    try:
        result = subprocess.run(
            ["node", "--check", path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or "").strip().splitlines()
            snippet = "\n      ".join(detail[:6])
            errors.append(f"{name}: JavaScript does not parse\n      {snippet}")
    finally:
        Path(path).unlink(missing_ok=True)


def check_python_format_leftovers(name, code, errors):
    """`${{x}}` in emitted JS always means a Python f-string was missed."""
    if "${{" in code:
        line = next(
            (l.strip() for l in code.splitlines() if "${{" in l),
            "",
        )
        errors.append(
            f"{name}: contains `${{{{` — a plain Python string that should be an f-string\n"
            f"      {line[:160]}"
        )


def validate(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    connections = data.get("connections", {})
    names = {n["name"] for n in nodes}
    errors = []

    for node in nodes:
        name = node["name"]
        code = node.get("parameters", {}).get("jsCode")
        if code:
            check_python_format_leftovers(name, code, errors)
            check_js(name, code, errors)

    # Every connection endpoint must exist, or n8n silently drops the branch.
    for src, outputs in connections.items():
        if src not in names:
            errors.append(f"connection source {src!r} is not a node in this workflow")
        for branch in outputs.get("main", []):
            for link in branch:
                if link["node"] not in names:
                    errors.append(f"{src} → {link['node']!r}: target node does not exist")

    # A node with no inbound connection and no trigger can never run.
    reachable = set()
    for outputs in connections.values():
        for branch in outputs.get("main", []):
            for link in branch:
                reachable.add(link["node"])
    for node in nodes:
        if node["type"] in TRIGGER_TYPES or node["type"] == "n8n-nodes-base.stickyNote":
            continue
        if node["name"] not in reachable:
            errors.append(f"{node['name']}: nothing connects to it — it can never run")

    # Overlapping nodes make the canvas unreadable and usually mean a missed
    # NODE_POSITIONS update.
    seen = {}
    for node in nodes:
        if node["type"] == "n8n-nodes-base.stickyNote":
            continue
        pos = tuple(node["position"])
        if pos in seen:
            errors.append(f"{node['name']} sits on top of {seen[pos]} at {list(pos)}")
        seen[pos] = node["name"]

    label = Path(path).name
    if errors:
        print(f"FAIL {label} ({len(nodes)} nodes)")
        for e in errors:
            print(f"  ✗ {e}")
        return False
    print(f"OK   {label} ({len(nodes)} nodes, {sum(1 for n in nodes if n.get('parameters', {}).get('jsCode'))} code nodes checked)")
    return True


if __name__ == "__main__":
    targets = sys.argv[1:] or [str(MAIN_WORKFLOW_JSON), str(LINKEDIN_WORKFLOW_JSON)]
    ok = all(validate(t) for t in targets)
    raise SystemExit(0 if ok else 1)
