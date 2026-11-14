"""Keep a fresh GitHub OIDC token on disk for Anthropic Workload Identity Federation.

GitHub's OIDC JWT expires ~5 minutes after issuance, and this job runs longer than that.
The Anthropic SDK re-reads ANTHROPIC_IDENTITY_TOKEN_FILE whenever it refreshes its access
token, so a background thread rewrites the file every few minutes.
"""

import base64
import json
import logging
import os
import threading
from pathlib import Path

import httpx

log = logging.getLogger(__name__)
AUDIENCE = "https://api.anthropic.com"
REFRESH_SECONDS = 180
WIF_VARS = ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
            "ANTHROPIC_SERVICE_ACCOUNT_ID", "ANTHROPIC_IDENTITY_TOKEN_FILE")


def wif_configured() -> bool:
    return all(os.environ.get(v) for v in WIF_VARS)


def _fetch_github_jwt() -> str:
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    token = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
    resp = httpx.get(url, params={"audience": AUDIENCE},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    resp.raise_for_status()
    return resp.json()["value"]


def describe_claims(jwt: str) -> dict:
    """Decode the (unverified) payload for diagnostics. Never log the token itself."""
    payload = jwt.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    keys = ("iss", "sub", "aud", "repository", "repository_owner", "ref", "event_name")
    return {k: claims.get(k) for k in keys}


def _write(path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_fetch_github_jwt(), encoding="utf-8")
    tmp.replace(path)  # atomic, so the SDK never reads a half-written token


def start_token_refresher() -> None:
    """Write a token now (raising on failure), then refresh it in a daemon thread."""
    if not os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
        log.info("not in GitHub Actions with id-token permission; using existing token file")
        return
    path = Path(os.environ["ANTHROPIC_IDENTITY_TOKEN_FILE"])
    _write(path)
    log.info("GitHub OIDC claims: %s", describe_claims(path.read_text(encoding="utf-8")))
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(REFRESH_SECONDS):
            try:
                _write(path)
            except (httpx.HTTPError, KeyError) as e:
                log.warning("OIDC token refresh failed: %s", e)

    threading.Thread(target=loop, daemon=True).start()
