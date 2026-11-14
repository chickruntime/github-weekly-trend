"""Anthropic Workload Identity Federation for GitHub Actions.

Each token exchange gets a freshly minted GitHub OIDC JWT: GitHub's tokens expire after
~5 minutes and an already-exchanged assertion is rejected, so a cached token file is not
enough for a multi-minute job. The SDK caches the resulting Anthropic access token.
"""

import base64
import json
import logging
import os

import httpx
from anthropic.lib.credentials import WorkloadIdentityCredentials

log = logging.getLogger(__name__)
AUDIENCE = "https://api.anthropic.com"
ID_VARS = ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_SERVICE_ACCOUNT_ID")


def wif_configured() -> bool:
    return all(os.environ.get(v) for v in ID_VARS) and bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"))


def describe_claims(jwt: str) -> dict:
    """Decode the (unverified) payload for diagnostics. Never log the token itself."""
    payload = jwt.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    keys = ("iss", "sub", "aud", "repository", "repository_owner", "ref", "event_name")
    return {k: claims.get(k) for k in keys}


def fetch_github_jwt() -> str:
    resp = httpx.get(
        os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"],
        params={"audience": AUDIENCE},
        headers={"Authorization": f"Bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["value"]


def make_credentials() -> WorkloadIdentityCredentials:
    log.info("GitHub OIDC claims: %s", describe_claims(fetch_github_jwt()))
    return WorkloadIdentityCredentials(
        identity_token_provider=fetch_github_jwt,
        federation_rule_id=os.environ["ANTHROPIC_FEDERATION_RULE_ID"],
        organization_id=os.environ["ANTHROPIC_ORGANIZATION_ID"],
        service_account_id=os.environ["ANTHROPIC_SERVICE_ACCOUNT_ID"],
    )
