# Custom Action API image (always-on FastAPI service).
# Build from the REPO ROOT so both the API package and src/ are in context:
#   docker build -f allenco_custom_action/Dockerfile -t allenco-custom-action .
#   az acr build  -r <acr> -f allenco_custom_action/Dockerfile -t custom-action:latest .
# The indexer has its own Dockerfile at the repo root.

FROM python:3.12-slim

# Install Microsoft ODBC Driver 18 for SQL Server (required by pyodbc).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft-prod.gpg] \
        https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so this layer is cached on code-only changes.
COPY allenco_custom_action/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code: the API package + the shared src/ (the API reaches src/notifications
# via the sys.path shim in notifications_setup.py, which resolves ../src).
COPY src/ ./src/
COPY allenco_custom_action/ ./allenco_custom_action/

# Logs land here when DEBUG_FILES=true; mount a volume to persist them.
RUN mkdir -p /app/logs

# Run as non-root.
RUN useradd --no-create-home --shell /bin/false apiuser \
    && chown -R apiuser /app/logs
USER apiuser

# Flat imports (from db import ..., from settings import ...) resolve from here.
WORKDIR /app/allenco_custom_action

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
