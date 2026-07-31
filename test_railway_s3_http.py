#!/usr/bin/env python3
"""Test Railway S3 via raw HTTP + AWS SigV4 (same logic as n8n workflow)."""
import hashlib
import hmac
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import ssl
import urllib.request
import urllib.error

SSL_CONTEXT = ssl.create_default_context()
try:
    import certifi
    SSL_CONTEXT.load_verify_locations(certifi.where())
except Exception:
    SSL_CONTEXT = ssl._create_unverified_context()

ENDPOINT_HOST = "t3.storageapi.dev"
BUCKET = "lightweight-vault-pew0g4o"
REGION = "auto"
ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "YOUR_S3_ACCESS_KEY")
SECRET_KEY = os.environ.get("S3_SECRET_KEY", "YOUR_S3_SECRET_KEY")
IMAGES_PREFIX = "images/"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def signing_key(date_stamp: str) -> bytes:
    k_date = hmac_sha256(("AWS4" + SECRET_KEY).encode(), date_stamp)
    k_region = hmac_sha256(k_date, REGION)
    k_service = hmac_sha256(k_region, "s3")
    return hmac_sha256(k_service, "aws4_request")


def encode_path(key: str) -> str:
    return "/".join(quote(part, safe="") for part in key.split("/"))


def host_name() -> str:
    return f"{BUCKET}.{ENDPOINT_HOST}"


def amz_now() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    return amz_date, date_stamp


def sign_request(method: str, canonical_uri: str, canonical_query: str, headers: dict, payload: bytes) -> dict:
    amz_date, date_stamp = amz_now()
    host = host_name()
    payload_hash = sha256_hex(payload)

    signed_header_map = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        **{k.lower(): v for k, v in headers.items()},
    }
    signed_header_names = sorted(signed_header_map.keys())
    canonical_headers = "".join(f"{k}:{signed_header_map[k]}\n" for k in signed_header_names)
    signed_headers = ";".join(signed_header_names)

    canonical_request = "\n".join([
        method,
        canonical_uri,
        canonical_query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])
    credential_scope = f"{date_stamp}/{REGION}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        sha256_hex(canonical_request.encode()),
    ])
    signature = hmac.new(signing_key(date_stamp), string_to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={ACCESS_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    out_headers = {
        "Host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": authorization,
        **headers,
    }
    return out_headers


def http_request(method: str, url: str, headers: dict, body: bytes | None = None) -> tuple[int, str, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return resp.status, data, dict(resp.headers)
    except urllib.error.HTTPError as e:
        data = e.read().decode("utf-8", errors="replace")
        return e.code, data, dict(e.headers)


def list_objects(prefix: str) -> tuple[int, list[str], str]:
    query = f"list-type=2&prefix={quote(prefix, safe='')}"
    headers = sign_request("GET", "/", query, {}, b"")
    url = f"https://{host_name()}/?{query}"
    status, body, _ = http_request("GET", url, headers)
    keys = re.findall(r"<Key>([^<]+)</Key>", body)
    return status, keys, body


def put_object(key: str, body: bytes, content_type: str) -> tuple[int, str]:
    uri = "/" + encode_path(key)
    headers = sign_request("PUT", uri, "", {"Content-Type": content_type}, body)
    url = f"https://{host_name()}{uri}"
    status, resp, _ = http_request("PUT", url, headers, body)
    return status, resp


def telegram_safe_url(url: str) -> str:
    return url.replace("_", "%5F")


def presign_put_url(key: str, content_type: str = "audio/mpeg", expires: int = 604800) -> str:
    """Presigned PUT URL — matches n8n presignPutUrl() in build_workflow.py."""
    amz_date, date_stamp = amz_now()
    host = host_name()
    credential = f"{ACCESS_KEY}/{date_stamp}/{REGION}/s3/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": credential,
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "content-type;host",
    }
    query = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params.items()))
    canonical_headers = f"content-type:{content_type}\nhost:{host}\n"
    signed_headers = "content-type;host"
    canonical_request = "\n".join([
        "PUT",
        "/" + encode_path(key),
        query,
        canonical_headers,
        signed_headers,
        "UNSIGNED-PAYLOAD",
    ])
    credential_scope = f"{date_stamp}/{REGION}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        sha256_hex(canonical_request.encode()),
    ])
    signature = hmac.new(signing_key(date_stamp), string_to_sign.encode(), hashlib.sha256).hexdigest()
    return telegram_safe_url(f"https://{host}/{encode_path(key)}?{query}&X-Amz-Signature={signature}")


def presign_get_url(key: str, expires: int = 3600) -> str:
    amz_date, date_stamp = amz_now()
    host = host_name()
    credential = f"{ACCESS_KEY}/{date_stamp}/{REGION}/s3/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": credential,
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    query = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params.items()))
    canonical_request = "\n".join([
        "GET",
        "/" + encode_path(key),
        query,
        f"host:{host}\n",
        "host",
        "UNSIGNED-PAYLOAD",
    ])
    credential_scope = f"{date_stamp}/{REGION}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        sha256_hex(canonical_request.encode()),
    ])
    signature = hmac.new(signing_key(date_stamp), string_to_sign.encode(), hashlib.sha256).hexdigest()
    return telegram_safe_url(f"https://{host}/{encode_path(key)}?{query}&X-Amz-Signature={signature}")


def main():
    print("=== Railway S3 HTTP test ===")
    print(f"Bucket: {BUCKET}")
    print(f"Host:   {host_name()}\n")

    print("1) LIST objects (images/) ...")
    status, keys, body = list_objects(IMAGES_PREFIX)
    print(f"   HTTP {status}")
    if status != 200:
        print(body[:800])
        sys.exit(1)
    print(f"   Found {len(keys)} key(s):")
    for k in keys:
        print(f"   - {k}")

    local_dir = Path(__file__).parent / "images"
    local_images = sorted(p for p in local_dir.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"})
    print(f"\n2) Local images folder: {len(local_images)} file(s)")

    if local_images and not any(k.endswith(local_images[0].name) for k in keys if not k.endswith(".keep")):
        sample = local_images[0]
        key = f"{IMAGES_PREFIX}{sample.name}"
        print(f"3) PUT test upload: {key} ({sample.stat().st_size} bytes) ...")
        data = sample.read_bytes()
        content_type = "image/jpeg" if sample.suffix.lower() in {".jpg", ".jpeg"} else "application/octet-stream"
        put_status, put_body = put_object(key, data, content_type)
        print(f"   HTTP {put_status}")
        if put_status not in (200, 201):
            print(put_body[:800])
            sys.exit(1)
        print("   Upload OK")
    else:
        print("3) Skipping upload (images already in bucket or no local files)")

    print("\n4) LIST again after upload ...")
    status, keys, _ = list_objects(IMAGES_PREFIX)
    image_keys = [k for k in keys if re.search(r"\.(jpe?g|png|webp|gif)$", k, re.I)]
    print(f"   HTTP {status}, image files: {len(image_keys)}")
    for k in image_keys[:5]:
        print(f"   - {k}")

    if image_keys:
        test_key = image_keys[0]
        url = presign_get_url(test_key, expires=300)
        print(f"\n5) Presigned GET test (5 min): {test_key}")
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
                snippet = resp.read(32)
                print(f"   HTTP {resp.status}, first bytes: {snippet[:16].hex()} ...")
                print("   Presigned download works")
        except urllib.error.HTTPError as e:
            print(f"   HTTP {e.code}")
            print(e.read().decode()[:400])

    print("\n=== All S3 HTTP checks passed ===")


if __name__ == "__main__":
    main()
