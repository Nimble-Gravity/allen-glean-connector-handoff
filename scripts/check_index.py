#!/usr/bin/env python
"""Verify indexing from the CONNECTOR side — no Glean user account needed.

Uses only the Indexing API token (GLEAN_INDEXING_API_KEY) to report how many
documents Glean holds for the datasource, and optionally to debug one document's
indexing status / permissions. Run after a live index (GLEAN_ENABLE_INDEXING=true):

    python scripts/check_index.py                       # datasource document count
    python scripts/check_index.py attendee attendee:2001  # + debug one document

The count is the strong "did it land" signal you can check yourself on the VM
(searching in the Glean UI needs a real Glean user — an Allen & Co person).
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=ROOT / ".env", override=True)

from glean_index.client import GleanConfig, get_glean_client  # noqa: E402


def main() -> int:
    print("=== INDEX CHECK ===")
    datasource = (os.environ.get("GLEAN_DATASOURCE") or "").strip()
    print("GLEAN_INSTANCE  :", repr(os.environ.get("GLEAN_INSTANCE")))
    print("GLEAN_DATASOURCE:", repr(datasource))
    if not datasource:
        print("CONFIG ERROR: GLEAN_DATASOURCE not set.")
        return 2

    try:
        client = get_glean_client(GleanConfig.from_env())
    except Exception as exc:
        print("CONFIG ERROR:", exc)
        return 2

    try:
        res = client.indexing.documents.count(datasource=datasource)
        print("DOCUMENT COUNT  :", res.document_count)
    except Exception as exc:
        print("RESULT: FAIL (could not read document count)")
        print("ERROR:", str(exc)[:400])
        return 1

    # Optional: debug a single document's indexing status / ACL.
    if len(sys.argv) >= 3:
        object_type, doc_id = sys.argv[1], sys.argv[2]
        print(f"\n--- debug {object_type} / {doc_id} ---")
        try:
            dbg = client.indexing.documents.debug(
                datasource=datasource, object_type=object_type, doc_id=doc_id
            )
            print(str(dbg)[:1500])
        except Exception as exc:
            print("DEBUG ERROR:", str(exc)[:300])

    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
