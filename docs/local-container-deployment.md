# Local and Container Deployment

Status: **The final image and Compose files are implemented, statically validated, and locally
verified through build, API/UI startup, both health endpoints, UI-to-API connectivity, API restart
recovery, and teardown.** This is a local
assessment stack, not a production deployment specification or a guarantee for every host.

## Services

The stack uses one `python:3.12-slim` application image:

| Service | Container command | Host URL | Health endpoint |
|---|---|---|---|
| `api` | `uvicorn enterprise_ai.main:app --factory --host 0.0.0.0 --port 8000` | `http://127.0.0.1:8000` | `/health/ready` |
| `ui` | `streamlit run frontend/streamlit_app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true --browser.gatherUsageStats=false` | `http://127.0.0.1:8501` | `/_stcore/health` |

The UI calls `http://api:8000` over the internal Compose network. Host ports bind only to
`127.0.0.1`. The UI waits for the API health check. Both services run as the image's non-root
`app` user with a read-only root filesystem, all Linux capabilities dropped,
`no-new-privileges`, and a small non-executable `/tmp`.

If default host ports are occupied, set `API_PUBLISHED_PORT` and `UI_PUBLISHED_PORT` before
Compose startup. These change only loopback host publication; container ports and
`FRONTEND_API_BASE_URL=http://api:8000` remain unchanged.

The image copies only packaging metadata, backend/ingestion packages, frontend runtime files, and
the committed synthetic corpus/retrieval artifacts. `.dockerignore` excludes Git state, local
environments, credentials, caches, tests, documentation, logs, and generated test artifacts.

## Mode 1: infrastructure smoke

This mode verifies only image construction, API/UI process startup, and health. Authentication is
disabled, so the Streamlit login cannot start an interactive chat. Fake LLM, local sparse
retrieval, and disabled Pinecone/LangSmith are explicit defaults.

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
python scripts/container_smoke.py
docker compose ps
docker compose logs --no-color
docker compose down --remove-orphans
```

Always run `docker compose down --remove-orphans` after the check, including after a failure.

## Mode 2: authenticated local runtime

Create an ignored local `.env.demo`. The script prompts securely for three passwords, generates a
random signing secret and Argon2id hashes, refuses to overwrite by default, and never prints the
secret, hashes, or passwords:

```powershell
python scripts/create_demo_env.py --llm-provider ollama
```

Use `--force` only when intentionally replacing the local file. On platforms that support POSIX
permissions the script applies mode `0600`; Windows users should also verify the file ACL. The
file is excluded by both `.gitignore` and `.dockerignore`.

`--force` prompts for and replaces all three configured passwords, their hashes, and the JWT signing
secret; it never reads or migrates the existing file.

Start the authenticated stack:

```powershell
docker compose --env-file .env.demo config --quiet
docker compose --env-file .env.demo build
docker compose --env-file .env.demo up -d
python scripts/container_smoke.py
docker compose --env-file .env.demo ps
```

Open `http://127.0.0.1:8501` and use the locally chosen passwords for `demo-viewer`,
`demo-analyst`, or `demo-admin`. Stop and remove the stack afterward:

```powershell
docker compose --env-file .env.demo down --remove-orphans
Remove-Item -LiteralPath .env.demo
```

The Compose interpolation passes only the explicitly named authentication and optional-provider
settings. It does not mount the environment file into either container.

## Native startup

From an activated Python 3.12 environment with `pip install -e ".[dev]"`:

```powershell
python scripts/create_demo_env.py --llm-provider ollama
python -m enterprise_ai.llm.cli check-ollama

Get-Content .env.demo | ForEach-Object {
    if ($_ -and -not $_.StartsWith('#')) {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

uvicorn enterprise_ai.main:app --factory --host 127.0.0.1 --port 8000
```

In a second activated terminal, load the same environment file and run:

```powershell
$env:FRONTEND_API_BASE_URL='http://127.0.0.1:8000'
streamlit run frontend/streamlit_app.py --server.address=127.0.0.1 --server.port=8501
```

Do not use Uvicorn reload mode during repeatable verification. Remove the process environment or
close the terminals after the session, then delete `.env.demo`.

Native startup uses `OLLAMA_BASE_URL=http://127.0.0.1:11434`. When the API runs in Compose, its
documented default is `http://host.docker.internal:11434`; the Linux host-gateway alias is declared
in Compose. API/UI host ports remain loopback-only. Ollama is a host dependency: the application
image and Compose stack do not install Ollama, start it, pull a model, or copy model weights.

## Provider modes

Local Qwen/Ollama is the primary authenticated local mode. Fake is the CI and
infrastructure-smoke default. `RETRIEVAL_MODE=sparse` is the credential-free retrieval default.
Pinecone-backed FastAPI chat requires `PINECONE_ENABLED=true`,
`RETRIEVAL_MODE=pinecone_hybrid`, a private key, and a verified index/namespace. OpenAI and
LangSmith likewise activate only through explicit runtime settings and credentials. The MCP path
remains the implemented local
in-process/official-SDK boundary; this stack intentionally has no remote MCP container or OAuth
configuration.

## Troubleshooting

- `docker compose config --quiet` fails: verify Compose v2 and YAML syntax before building.
- API unhealthy: inspect `docker compose logs --no-color api`; confirm the committed
  `data/processed` artifacts are present in the build context.
- UI unhealthy: inspect `docker compose logs --no-color ui`; confirm API is healthy first.
- Login endpoint missing: authentication is disabled; use authenticated mode with `.env.demo`.
- Configuration rejects authentication: all three password hashes and a signing secret are
  mandatory when `AUTH_ENABLED=true`.
- Cloud provider unavailable: leave Pinecone/LangSmith disabled and use `LLM_PROVIDER=fake` with
  `RETRIEVAL_MODE=sparse`.
- Port already in use: stop the conflicting local process; do not expose Compose on a broader host
  interface as a workaround.

## Session reset and cleanup

- Use **New conversation** to clear the current chat and activity state; a browser refresh preserves
  the active server-side session.
- Log out before changing roles so the next request receives a freshly issued role-bound token.
- Stop native API/UI processes or run the matching Compose teardown command after verification.
- Close terminals that loaded `.env.demo`, then delete the ignored file when it is no longer needed.
- Remove temporary `PINECONE_*`, `LANGSMITH_*`, `OPENAI_*`, and provider-selection variables from
  the process environment, and revoke temporary cloud credentials.

Process-local memory, checkpoints, rate limits, and MCP state reset on container restart. No
durable replay, distributed state, enterprise IdP, remote MCP OAuth, or production secrets
management is claimed.

## CI trade-off

CI validates repository-relative documentation links and `docker compose config --quiet`. The
exact image lifecycle has also passed locally. A full Compose CI job remains intentionally omitted:
the image build downloads Python packages and already encountered a recoverable package-index DNS
failure during local verification, so making that network-sensitive duplicate path an authoritative
gate would add avoidable flakiness. The existing CI installs and tests the Python package; the local
commands above are the container-specific runtime proof.
