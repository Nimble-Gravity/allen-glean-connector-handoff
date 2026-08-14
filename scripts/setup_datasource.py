#!/usr/bin/env python
"""Register the Glean custom datasource config (object types + urlRegex) from the catalog.

Glean requires each document's **object type** to be declared on the datasource before
indexing ("Object definitions not found for object types: ..."). This configures the
datasource (``GLEAN_DATASOURCE``) via the Indexing API using only the token — no admin
console needed.

Run ONCE before the first index, and again whenever you add/rename/enable a view:

    python scripts/setup_datasource.py

- Object types come from the **enabled** entries in ``views/catalog.py``.
- ``urlRegex`` is derived from ``VIEW_URL_BASE`` so it matches the viewURLs the
  connector stamps (keeping the two in sync automatically).

⚠️ This UPSERTS the datasource config (name/category/urlRegex/object types). For the
test that is fine (placeholders). The real category/urlRegex come from the client
(see infra/allenco/GLEAN-API-KEY.md) — override via DATASOURCE_DISPLAY_NAME / the
env below when known.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=ROOT / ".env", override=True)

from glean.api_client import models  # noqa: E402

from allenco_connector.views.catalog import VIEW_CATALOG  # noqa: E402
from glean_index.client import GleanConfig, get_glean_client  # noqa: E402


def _label(object_type: str) -> str:
    """camelCase/underscore object type -> a readable display label.

    e.g. 'attendeeContact' -> 'Attendee Contact'.
    """
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", object_type.replace("_", " "))
    return spaced.strip().title()


def main() -> int:
    print("=== DATASOURCE SETUP ===")
    datasource = (os.environ.get("GLEAN_DATASOURCE") or "").strip()
    if not datasource:
        print("CONFIG ERROR: GLEAN_DATASOURCE not set.")
        return 2
    view_url_base = (
        (os.environ.get("VIEW_URL_BASE") or "https://ems.allenco.com").strip().rstrip("/")
    )
    display_name = (os.environ.get("DATASOURCE_DISPLAY_NAME") or "Allen & Co EMS").strip()

    object_types = sorted({e.object_type for e in VIEW_CATALOG if e.enabled})
    object_definitions = [
        models.ObjectDefinition(
            name=ot, display_label=_label(ot), doc_category=models.DocCategory.CRM
        )
        for ot in object_types
    ]
    url_regex = f"{view_url_base}/.*"

    print("GLEAN_DATASOURCE :", datasource)
    print("urlRegex         :", url_regex)
    print("object types     :", ", ".join(object_types))

    try:
        client = get_glean_client(GleanConfig.from_env())
        client.indexing.datasources.add(
            name=datasource,
            display_name=display_name,
            datasource_category=models.DatasourceCategory.CRM,
            url_regex=url_regex,
            object_definitions=object_definitions,
            is_user_referenced_by_email=True,
        )
    except Exception as exc:
        print("RESULT: FAIL")
        print("ERROR:", str(exc)[:500])
        return 1

    print(
        f"\nRESULT: PASS — datasource '{datasource}' configured with "
        f"{len(object_definitions)} object type(s). You can index now."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
