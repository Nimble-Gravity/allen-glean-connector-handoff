FROM python:3.12-slim

# Install Microsoft ODBC Driver 18 for SQL Server (required by pyodbc)
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

# Install runtime dependencies first so this layer is cached on code-only changes.
# Keep these in sync with pyproject.toml [project.dependencies].
RUN pip install --no-cache-dir \
    "python-dotenv>=1.0.0" \
    "glean-api-client>=0.11.27" \
    "psutil>=7.2.2" \
    "pyodbc>=5.0.0" \
    "pandas>=2.0" \
    "azure-storage-blob>=12.19" \
    "azure-identity>=1.15"

# Install the package itself (no-deps: deps already installed above)
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .

# Writable dirs for the non-root user: logs (DEBUG_FILES=true) and the dry-run
# JSON dump (.outputs, GLEAN_ENABLE_INDEXING=false). WORKDIR is /app, so the app's
# CWD-based paths resolve here. Owned by the runtime user so writes succeed.
RUN mkdir -p /app/logs /app/.outputs
VOLUME ["/app/logs"]

# Run as non-root
RUN useradd --no-create-home --shell /bin/false connector \
    && chown -R connector /app/logs /app/.outputs
USER connector

# The connector is a one-shot job; scheduling is handled externally
# (host cron, systemd timer, or AWS ECS Scheduled Tasks).
CMD ["python", "-m", "main"]
