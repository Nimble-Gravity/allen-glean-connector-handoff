from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from pprint import pprint
from typing import Any

from dotenv import load_dotenv
from glean.api_client import Glean
from glean.api_client import errors as glean_errors


def _load_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env", override=False)


def _pprint_datasource_status(glean: Glean, datasource: str) -> None:
    """Call debug datasource status and print the payload.

    The indexing API often returns HTTP 200 with ``application/json`` while the
    generated client only accepts ``application/json; charset=UTF-8``, which
    surfaces as ``GleanError`` even on success. Recover by parsing the body.
    """
    try:
        res = glean.indexing.datasource.status(datasource=datasource)
        pprint(res)
    except glean_errors.GleanError as exc:
        if exc.status_code != 200:
            raise
        try:
            data: Any = json.loads(exc.body)
        except json.JSONDecodeError as decode_exc:
            raise RuntimeError(
                "HTTP 200 from datasource status but body is not valid JSON"
            ) from decode_exc
        pprint(data)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _load_env()

    api_token = os.environ.get("GLEAN_INDEXING_API_KEY")
    instance = os.environ.get("GLEAN_INSTANCE")
    datasource = os.environ.get("GLEAN_DATASOURCE")

    try:
        with Glean(api_token=api_token, instance=instance) as glean:
            _pprint_datasource_status(glean, datasource)
    except glean_errors.GleanError as exc:
        logging.error("indexing.datasource.status failed: %s", exc)
        return 1
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
