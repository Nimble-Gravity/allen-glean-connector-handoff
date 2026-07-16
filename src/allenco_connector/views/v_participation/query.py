"""EMS v_Participation view identifiers (used by the registry)."""

VIEW_NAME = "v_Participation"

# Change-tracking column for incremental sync. Matches the mock schema's
# ModifiedDate. TODO Allen & Co: confirm the real EMS change-tracking column,
# or set to None to always full-fetch this view.
WATERMARK_COLUMN: str | None = "ModifiedDate"
