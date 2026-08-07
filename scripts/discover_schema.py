#!/usr/bin/env python
"""Discover the real EMS view schema so the view catalog can be filled in.

Run on the dev VM (real DB reachable) from the repo root with the venv active:

    python scripts/discover_schema.py

Reads the shared .env, connects, and for every user view (INFORMATION_SCHEMA.VIEWS)
lists its columns and guesses the id / title / watermark columns. Writes the full
picture to ``.outputs/schema.json`` and prints ready-to-paste ViewCatalogEntry
snippets for ``src/allenco_connector/views/catalog.py``.

This does NOT change any code — it only reads the catalogue tables. Use its output
to replace the seed entries in catalog.py with the real Conference views.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=ROOT / ".env", override=True)

import pyodbc  # noqa: E402

from allenco_connector.db_connection import build_connection_string  # noqa: E402
from config.config import load_db_settings  # noqa: E402

# System schemas to skip when listing user views.
_SYSTEM_SCHEMAS = {"sys", "INFORMATION_SCHEMA", "guest"}

# SQL Server date/time-ish types that can serve as an incremental watermark.
_DATETIME_TYPES = {
    "datetime",
    "datetime2",
    "smalldatetime",
    "date",
    "datetimeoffset",
    "timestamp",
    "rowversion",
}
_STRING_TYPES = {"varchar", "nvarchar", "char", "nchar", "text", "ntext"}

# Column-name fragments that make a good human title.
_TITLE_HINTS = ("name", "title", "subject", "firstname", "lastname", "company", "event")
# Column-name fragments that mark a change-tracking (watermark) column.
_WATERMARK_HINTS = ("modif", "updat", "chang", "lastmod")


def _object_type_from_view(view_name: str) -> str:
    """v_Attendee_Event -> 'attendee_event' (strip a leading v_/V_, lowercase)."""
    stripped = view_name[2:] if view_name[:2].lower() == "v_" else view_name
    return stripped.strip().lower().replace(" ", "_")


def _guess_id_column(columns: list[dict]) -> str:
    for col in columns:
        if col["name"].lower().endswith("id"):
            return col["name"]
    return columns[0]["name"] if columns else ""


def _guess_title_columns(columns: list[dict]) -> list[str]:
    hits = [
        col["name"]
        for col in columns
        if col["type"] in _STRING_TYPES and any(h in col["name"].lower() for h in _TITLE_HINTS)
    ]
    return hits[:2]


def _guess_watermark_column(columns: list[dict]) -> str | None:
    dt = [col for col in columns if col["type"] in _DATETIME_TYPES]
    for col in dt:
        if any(h in col["name"].lower() for h in _WATERMARK_HINTS):
            return col["name"]
    return dt[0]["name"] if dt else None


def _catalog_snippet(view: dict, default_schema: str) -> str:
    g = view["guessed"]
    titles = ", ".join(f'"{c}"' for c in g["title_columns"])
    title_tuple = f"({titles},)" if len(g["title_columns"]) == 1 else f"({titles})"
    lines = [
        "    ViewCatalogEntry(",
        f'        view_name="{view["name"]}",',
        f'        object_type="{_object_type_from_view(view["name"])}",',
        f'        id_column="{g["id_column"]}",',
        f"        title_columns={title_tuple},",
    ]
    if g["watermark_column"]:
        lines.append(f'        watermark_column="{g["watermark_column"]}",')
    else:
        lines.append("        watermark_column=None,  # no datetime column found")
    if view["schema"] != default_schema:
        lines.append(f'        schema="{view["schema"]}",')
    lines.append("    ),")
    return "\n".join(lines)


def main() -> int:
    print("=== SCHEMA DISCOVERY ===")
    try:
        settings = load_db_settings()
    except Exception as exc:
        print("CONFIG ERROR:", exc)
        return 2
    print("DB_SERVER:", repr(settings.server), " DB_SCHEMA:", repr(settings.schema))

    try:
        conn = pyodbc.connect(build_connection_string(settings), timeout=10)
    except Exception as exc:
        print("RESULT: FAIL (could not connect)")
        print("ERROR:", str(exc)[:400])
        return 1

    views: list[dict] = []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.VIEWS "
            "ORDER BY TABLE_SCHEMA, TABLE_NAME"
        )
        found = [(s, n) for (s, n) in cur.fetchall() if s not in _SYSTEM_SCHEMAS]
        print(f"Found {len(found)} view(s):", ", ".join(sorted({s for s, _ in found})) or "(none)")

        for schema, name in found:
            cur.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                "ORDER BY ORDINAL_POSITION",
                [schema, name],
            )
            columns = [
                {
                    "name": r[0],
                    "type": str(r[1]).lower(),
                    "nullable": str(r[2]).upper() == "YES",
                    "ordinal": int(r[3]),
                }
                for r in cur.fetchall()
            ]
            views.append(
                {
                    "schema": schema,
                    "name": name,
                    "columns": columns,
                    "guessed": {
                        "id_column": _guess_id_column(columns),
                        "title_columns": _guess_title_columns(columns),
                        "watermark_column": _guess_watermark_column(columns),
                    },
                }
            )
    finally:
        conn.close()

    out_base = Path(os.environ.get("CONNECTOR_OUTPUT_DIR") or ROOT)
    out_dir = out_base / ".outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "schema.json"
    out_path.write_text(
        json.dumps({"default_schema": settings.schema, "views": views}, indent=2),
        encoding="utf-8",
    )

    print(f"\nWrote {out_path} ({len(views)} view(s)).")
    print("\n--- paste into src/allenco_connector/views/catalog.py (confirm guessed columns) ---\n")
    print("VIEW_CATALOG = (")
    for view in views:
        print(_catalog_snippet(view, settings.schema))
    print(")")
    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
