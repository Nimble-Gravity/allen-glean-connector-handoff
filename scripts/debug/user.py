"""Debug a user's Glean identity/permissions for this datasource.

    python scripts/debug/user.py <user_email>
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from pprint import pprint

from dotenv import load_dotenv
from glean.api_client import Glean
from glean.api_client import errors as glean_errors


def _load_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env", override=False)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _load_env()

    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/debug/user.py <user_email>")
    email = sys.argv[1]

    api_token = os.environ.get("GLEAN_INDEXING_API_KEY")
    instance = os.environ.get("GLEAN_INSTANCE")
    datasource = os.environ.get("GLEAN_DATASOURCE")

    if not datasource:
        raise SystemExit("Missing GLEAN_DATASOURCE in .env.")

    try:
        with Glean(api_token=api_token, instance=instance) as glean:
            res = glean.indexing.people.debug(datasource=datasource, email=email)
            pprint(res)
    except glean_errors.GleanError as exc:
        logging.error("indexing.people.debug failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
