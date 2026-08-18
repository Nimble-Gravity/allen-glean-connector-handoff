"""Helpers for exporting connector data to JSON files when indexing is disabled."""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _outputs_dir() -> Path:
    """Directory for dry-run JSON dumps.

    Based on CONNECTOR_OUTPUT_DIR (or the current working directory), NOT the
    package location: the connector is pip-installed into a read-only
    site-packages inside the container, so a ``__file__``-relative path would not
    be writable by the non-root user. Locally (run from the repo root) this
    resolves to ``<repo>/.outputs`` as before.
    """
    base = os.environ.get("CONNECTOR_OUTPUT_DIR") or os.getcwd()
    return Path(base) / ".outputs"


def export_view_to_json(df: pd.DataFrame, view_name: str, excluded_columns: list[str]) -> Path:
    """Write a DataFrame (minus excluded_columns) to .outputs/<view_name>_<ts>.json."""
    export_df = df.drop(columns=[c for c in excluded_columns if c in df.columns], errors="ignore")
    output_dir = _outputs_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    output_path = output_dir / f"{view_name}_{timestamp}.json"
    records = export_df.to_dict(orient="records")
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, default=str)
    logger.info("Exported %s rows to %s", len(export_df), output_path)
    return output_path


def export_documents_to_json(documents: list, view_name: str) -> Path:
    """Write built DocumentDefinitions as JSON summaries to
    .outputs/<view_name>_documents_<ts>.json.

    A faithful preview of what the live push sends: includes the ``viewUrl`` and
    ``customProperties`` (e.g. EventInstanceID) alongside id/title/body, so a dry run
    surfaces exactly what Glean will receive.
    """
    output_dir = _outputs_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    output_path = output_dir / f"{view_name}_documents_{timestamp}.json"
    records = [_document_summary(doc) for doc in documents]
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    logger.info("Exported %s document summaries to %s", len(records), output_path)
    return output_path


def _document_summary(doc) -> dict:
    """A JSON-friendly summary of a built DocumentDefinition for dry-run inspection."""
    props = getattr(doc, "custom_properties", None) or []
    return {
        "id": doc.id,
        "title": doc.title,
        "viewUrl": getattr(doc, "view_url", None),
        "customProperties": [{"name": p.name, "value": p.value} for p in props],
        "body": json.loads(doc.body.text_content),
    }
