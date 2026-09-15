"""Debug documents in the Glean datasource: count, sample IDs, and per-user access.

    python scripts/debug/document.py count
    python scripts/debug/document.py list <object_type> <doc_id> [<doc_id> ...]
    python scripts/debug/document.py access <object_type> <doc_id> <user_email>

There is no "list all documents" call in the Indexing API — `list` debugs the
specific IDs you already know (e.g. from `.outputs/` dry-run JSON, or the EMS
view's id_column) so you can confirm they landed and see their ACL.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from pprint import pprint
from typing import Any

from dotenv import load_dotenv
from glean.api_client import Glean
from glean.api_client import errors as glean_errors


def _load_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env", override=False)


def _get_client() -> Glean:
    api_token = os.environ.get("GLEAN_INDEXING_API_KEY")
    instance = os.environ.get("GLEAN_INSTANCE")
    return Glean(api_token=api_token, instance=instance)


def _recover_200(exc: glean_errors.GleanError) -> Any:
    """Recover the payload when the SDK misclassifies an HTTP 200 as an error.

    The indexing API often returns HTTP 200 with ``application/json`` while the
    generated client only accepts ``application/json; charset=UTF-8``, which
    surfaces as ``GleanError`` even on success (see status.py). Re-raise
    anything that isn't actually a 200.
    """
    if exc.status_code != 200:
        raise exc
    return json.loads(exc.body)


def cmd_count(datasource: str) -> int:
    with _get_client() as glean:
        try:
            res = glean.indexing.documents.count(datasource=datasource)
            print("DOCUMENT COUNT:", res.document_count)
        except glean_errors.GleanError as exc:
            pprint(_recover_200(exc))
    return 0


def cmd_list(datasource: str, object_type: str, doc_ids: list[str]) -> int:
    with _get_client() as glean:
        for doc_id in doc_ids:
            print(f"\n--- {object_type} / {doc_id} ---")
            try:
                dbg = glean.indexing.documents.debug(
                    datasource=datasource, object_type=object_type, doc_id=doc_id
                )
                pprint(dbg)
            except glean_errors.GleanError as exc:
                try:
                    pprint(_recover_200(exc))
                except glean_errors.GleanError:
                    logging.error("debug failed for %s: %s", doc_id, exc)
    return 0


def cmd_access(datasource: str, object_type: str, doc_id: str, user_email: str) -> int:
    with _get_client() as glean:
        try:
            res = glean.indexing.documents.check_access(
                datasource=datasource,
                object_type=object_type,
                doc_id=doc_id,
                user_email=user_email,
            )
            pprint(res)
        except glean_errors.GleanError as exc:
            pprint(_recover_200(exc))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _load_env()

    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    datasource = os.environ.get("GLEAN_DATASOURCE")
    if not datasource:
        raise SystemExit("Missing GLEAN_DATASOURCE in .env.")

    command = sys.argv[1]
    try:
        if command == "count":
            return cmd_count(datasource)
        if command == "list":
            if len(sys.argv) < 4:
                raise SystemExit("Usage: document.py list <object_type> <doc_id> [<doc_id> ...]")
            return cmd_list(datasource, sys.argv[2], sys.argv[3:])
        if command == "access":
            if len(sys.argv) != 5:
                raise SystemExit("Usage: document.py access <object_type> <doc_id> <user_email>")
            return cmd_access(datasource, sys.argv[2], sys.argv[3], sys.argv[4])
        raise SystemExit(__doc__)
    except glean_errors.GleanError as exc:
        logging.error("Glean API call failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
