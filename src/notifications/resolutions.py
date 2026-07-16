"""Maps each ErrorType to a recommended resolution step for the operations team.

Keeping the hints in one table makes them easy to review and tune. Callers can
always override by passing an explicit ``recommended_resolution`` to ErrorEvent.
"""

from notifications.events import ErrorType

_RESOLUTIONS: dict[ErrorType, str] = {
    ErrorType.DB_CONNECTION: (
        "Verify DB connectivity; confirm DB_SERVER, "
        "DB_USER, and DB_PASSWORD. The SQL Server may be cold-starting — retry shortly."
    ),
    ErrorType.GLEAN_PREREQS: (
        "Set GLEAN_DATASOURCE, GLEAN_INSTANCE, and GLEAN_INDEXING_API_KEY in .env, "
        "or set GLEAN_ENABLE_INDEXING=false to run in export-only mode."
    ),
    ErrorType.USER_INDEXING: (
        "Check the Glean Indexing API key and its permissions, then rerun. "
        "Document indexing still ran for this cycle."
    ),
    ErrorType.DOCUMENT_INDEXING: (
        "Check Glean Indexing API status/quota and the upload payload, then rerun the connector."
    ),
    ErrorType.API_STARTUP: (
        "Custom Action API failed to start. Confirm CUSTOM_ACTION_API_KEY and the DB_* "
        "variables are set, and that the SQL Server is reachable."
    ),
    ErrorType.API_REQUEST: (
        "A Custom Action API request failed against SQL Server. Verify DB connectivity "
        "and that the SQL Server is reachable; check the API logs for the failing query."
    ),
    ErrorType.UNEXPECTED: (
        "Review the connector logs (logs/error/ or scheduler.log) for the traceback "
        "and escalate to the engineering team if the cause is unclear."
    ),
}


def resolution_for(error_type: ErrorType) -> str:
    """Return the recommended resolution for an error type.

    Falls back to the UNEXPECTED guidance for any unmapped type.
    """
    return _RESOLUTIONS.get(error_type, _RESOLUTIONS[ErrorType.UNEXPECTED])
