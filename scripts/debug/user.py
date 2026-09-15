from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from pprint import pprint

import glean_indexing_api_client
from dotenv import load_dotenv
from glean_indexing_api_client.api import troubleshooting_api
from glean_indexing_api_client.model.debug_user_request import DebugUserRequest


def _load_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env", override=False)


def _build_api_client() -> glean_indexing_api_client.ApiClient:
    instance = dotenv.get("GLEAN_INSTANCE")
    token = dotenv.get("GLEAN_INDEXING_API_KEY")
    host = dotenv.get("GLEAN_HOST")

    if not instance or not token:
        raise SystemExit(
            "Missing Glean configuration. Set GLEAN_INSTANCE and GLEAN_INDEXING_API_KEY in .env."
        )

    if not host:
        host = f"https://{instance}-be.glean.com/api/index/v1"

    config = glean_indexing_api_client.Configuration(host=host, access_token=token)
    return glean_indexing_api_client.ApiClient(config)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _load_env()

    datasource = dotenv.get("GLEAN_DATASOURCE")
    email = "test@email.com"
    if not datasource:
        raise SystemExit("Missing datasource. Provide --datasource or set GLEAN_DATASOURCE in .env.")
    if not email:
        raise SystemExit("Missing email. Provide --email or set GLEAN_DEBUG_EMAIL in .env.")

    debug_user_request = DebugUserRequest(email=email)

    try:
        with _build_api_client() as api_client:
            troubleshoot_api = troubleshooting_api.TroubleshootingApi(api_client)
            api_response = troubleshoot_api.debug_datasource_user_post(
                datasource, debug_user_request
            )
            pprint(api_response)
    except glean_indexing_api_client.ApiException as exc:
        logging.error("TroubleshootingApi debug_datasource_user_post failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())