#!/usr/bin/env python3
"""One-shot LinkedIn v2 publish smoke test (person or org author URN).

Usage:
  export LINKEDIN_ACCESS_TOKEN="..."   # from n8n credential OAuth data
  export LINKEDIN_PUBLISH_AS=person  # or organization
  python3 build/test_linkedin_publish.py

Get token from n8n: Credentials → jusmeen<> lakshit LinkedIn account → OAuth token
(or reconnect and copy from browser network tab during test request).
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from config import LINKEDIN_ORG_ID, LINKEDIN_PERSON_URN, LINKEDIN_PUBLISH_AS  # noqa: E402

TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
PUBLISH_AS = (os.environ.get("LINKEDIN_PUBLISH_AS") or LINKEDIN_PUBLISH_AS or "person").lower()
AUTHOR = (
    LINKEDIN_PERSON_URN
    if PUBLISH_AS == "person"
    else f"urn:li:organization:{LINKEDIN_ORG_ID or 'ORG_ID'}"
)
TEST_POST = (
    "Smoke test — smart vending in India. Wendor builds machines for UPI, "
    "remote monitoring, and Indian site conditions. (automated test — safe to delete)"
)


def li_request(method, url, body=None, content_type="application/json", raw=None):
    if not TOKEN:
        raise SystemExit("Set LINKEDIN_ACCESS_TOKEN env var (OAuth access token).")
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    data = None
    if raw is not None:
        data = raw
    elif body is not None:
        headers["Content-Type"] = content_type
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as err:
        raise SystemExit(f"HTTP {err.code} {url}\n{err.read().decode()[:1200]}") from err


def main():
    print(f"Author: {AUTHOR} (publish_as={PUBLISH_AS})")

    # 1x1 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    )

    reg_body = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": AUTHOR,
            "serviceRelationships": [{
                "relationshipType": "OWNER",
                "identifier": "urn:li:userGeneratedContent",
            }],
        }
    }
    _, reg_raw, _ = li_request(
        "POST",
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        body=reg_body,
    )
    reg = json.loads(reg_raw.decode())
    asset = reg["value"]["asset"]
    upload_url = reg["value"]["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    print(f"Registered asset: {asset}")

    upload_req = urllib.request.Request(
        upload_url,
        data=png,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/octet-stream",
        },
    )
    with urllib.request.urlopen(upload_req) as resp:
        print(f"Uploaded image: HTTP {resp.status}")

    publish_body = {
        "author": AUTHOR,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": TEST_POST},
                "shareMediaCategory": "IMAGE",
                "media": [{"status": "READY", "media": asset, "title": {"text": "Wendor test"}}],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    _, pub_raw, pub_headers = li_request(
        "POST",
        "https://api.linkedin.com/v2/ugcPosts",
        body=publish_body,
    )
    share_id = pub_headers.get("x-restli-id") or pub_headers.get("X-Restli-Id")
    print("Publish OK")
    if share_id:
        print(f"URL: https://www.linkedin.com/feed/update/{share_id}")
    else:
        print(pub_raw.decode()[:500])


if __name__ == "__main__":
    main()
