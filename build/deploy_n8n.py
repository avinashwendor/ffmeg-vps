#!/usr/bin/env python3
"""Push automations/mini_automation_for_reels.json to n8n via REST API."""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from config import N8N_API_KEY  # noqa: F401
from paths import MAIN_WORKFLOW_JSON

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "https://n8n.wendor.in")
WORKFLOW_ID = os.environ.get("N8N_WORKFLOW_ID", "VMLfuo2WF1m5lOwc")
WORKFLOW_FILE = Path(os.environ.get("N8N_WORKFLOW_FILE", str(MAIN_WORKFLOW_JSON)))


def api_request(method, path, body=None):
    api_key = os.environ.get("N8N_API_KEY") or N8N_API_KEY
    if not api_key:
        raise SystemExit(
            "Missing N8N_API_KEY. Set env var or add to build/secrets_local.py.\n"
            "Get it from n8n → Settings → API → Create API key."
        )
    url = f"{N8N_BASE_URL.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        body_text = err.read().decode()
        raise SystemExit(f"n8n API {method} {path} failed ({err.code}): {body_text[:800]}") from err


def main():
    with open(WORKFLOW_FILE, encoding="utf-8") as f:
        workflow = json.load(f)

    payload = {
        "name": workflow["name"],
        "nodes": workflow["nodes"],
        "connections": workflow["connections"],
        "settings": workflow.get("settings", {}),
    }

    status, result = api_request("PUT", f"/api/v1/workflows/{WORKFLOW_ID}", payload)
    print(f"Updated workflow {WORKFLOW_ID} ({workflow['name']}) — HTTP {status}")
    print(f"Nodes: {len(workflow['nodes'])}")
    if isinstance(result, dict) and result.get("id"):
        print(f"Active: {result.get('active')}")


if __name__ == "__main__":
    main()
