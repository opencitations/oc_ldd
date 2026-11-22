# OpenCitations LDD Service

[...]


## Configuration

### Environment Variables

The service requires the following environment variables. These values take precedence over the ones defined in `conf.json`:

- `BASE_URL`: Base URL for the service
- `SPARQL_ENDPOINT_INDEX`: URL for the internal Index SPARQL endpoint
- `SPARQL_ENDPOINT_META`: URL for the internal Meta SPARQL endpoint
- `LOG_DIR`: Directory path where log files will be stored
- `SYNC_ENABLED`: Enable/disable static files synchronization (default: false)
- `INDEX_BASE_URL`: Base URL used to construct redirect links for resources served by the application

For instance:

```env
# API Configuration
BASE_URL=api.opencitations.net
LOG_DIR=/home/dir/log/
SPARQL_ENDPOINT_INDEX=http://qlever-service.default.svc.cluster.local:7011  
SPARQL_ENDPOINT_META=http://virtuoso-service.default.svc.cluster.local:8890/sparql
SYNC_ENABLED=true
INDEX_BASE_URL=https://w3id.org/oc
```

> **Note**: When running with Docker, environment variables always override the corresponding values in `conf.json`. If an environment variable is not set, the application will fall back to the values defined in `conf.json`.

### Static Files Synchronization

The application can synchronize static files from a GitHub repository. This configuration is managed in `conf.json`:

```json
{
  "oc_services_templates": "https://github.com/opencitations/oc_services_templates",
  "sync": {
    "folders": [
      "static",
      "html-template/common"
    ],
    "files": [
      "test.txt"
    ]
  }
}
```

- `oc_services_templates`: The GitHub repository URL to sync files from
- `sync.folders`: List of folders to synchronize
- `sync.files`: List of individual files to synchronize

When static sync is enabled (via `--sync-static` or `SYNC_ENABLED=true`), the application will:
1. Clone the specified repository
2. Copy the specified folders and files
3. Keep the local static files up to date

> **Note**: Make sure the specified folders and files exist in the source repository.

## Running Options

### Local Development

For local development and testing, the application uses the built-in web.py HTTP server. Dependencies are managed with [uv](https://docs.astral.sh/uv/) through `pyproject.toml` and `uv.lock`:

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run with default settings
uv run python ldd_oc.py

# Run with static sync enabled
uv run python ldd_oc.py --sync-static

# Run on custom port
uv run python ldd_oc.py --port 8085

# Run with both options
uv run python ldd_oc.py --sync-static --port 8085
```

The application supports the following command line arguments:

- `--sync-static`: Synchronize static files at startup and enable periodic sync (every 30 minutes)
- `--port PORT`: Specify the port to run the application on (default: 8080)

To add or upgrade a dependency, use `uv add <package>` (or `uv lock --upgrade-package <package>`) and commit both `pyproject.toml` and `uv.lock`.

### Production Deployment (Docker)

When running in Docker/Kubernetes, the application uses **Gunicorn** as the WSGI HTTP server for better performance and concurrency handling:

- **Server**: Gunicorn with gevent workers
- **Workers**: 4 concurrent worker processes
- **Worker Type**: gevent (async) for handling simultaneous requests
- **Timeout**: 1200 seconds (to handle long-running SPARQL queries)
- **Connections per worker**: 400 simultaneous connections

The Docker image installs the exact versions pinned in `uv.lock` (`uv sync --locked`), so the build fails if the lockfile is out of sync with `pyproject.toml`.

The Docker image version is read from `pyproject.toml` (single source of truth). To publish a new image on DockerHub, update the `version` field in `pyproject.toml` and push to `main` — the GitHub Actions workflow will build and push the new tag automatically, skipping the build if that version already exists.

```bash
VERSION=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)

docker build -t opencitations/oc_ldd:$VERSION .
docker run -p 8080:8080 \
  -e SPARQL_ENDPOINT_INDEX=http://qlever:7011 \
  -e SPARQL_ENDPOINT_META=http://virtuoso:8890/sparql \
  opencitations/oc_ldd:$VERSION
```

The Docker container automatically uses Gunicorn and is configured with static sync enabled by default. The default values of the environment variables are defined in the `Dockerfile` and can be overridden at runtime.

> **Note**: The application code automatically detects the execution environment. When run with `uv run python ldd_oc.py`, it uses the built-in web.py server. When run with Gunicorn (as in Docker), it uses the WSGI interface.

You can customize the Gunicorn server configuration by modifying the `gunicorn.conf.py` file.
