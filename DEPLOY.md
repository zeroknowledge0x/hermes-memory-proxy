# Deploy — Hermes Memory Proxy

How to run the proxy in production on Linux, Windows (WSL2), and via Docker.
The proxy is a long-running process — it must stay up for Hermes to use memory.

## Linux (systemd)

Install the unit (see `examples/memory-proxy.service`):

```bash
cp examples/memory-proxy.service /etc/systemd/system/memory-proxy.service
# edit the WorkingDirectory / Environment=FILE= paths to match your install
systemctl daemon-reload
systemctl enable --now memory-proxy
systemctl status memory-proxy   # active (running)
```

The proxy auto-restarts on crash via `Restart=always`. Logs: `journalctl -u memory-proxy`.

## Windows (WSL2) — important caveats

WSL2 **auto-suspends when idle**, which kills Postgres + the proxy. Three options:

### Option A — run Postgres natively on Windows (recommended for desktop)
Install Postgres 16 + pgvector as a Windows service (it does not auto-stop).
Point `DATABASE_URL` at `127.0.0.1:5432` (NOT `localhost` — on Windows `localhost`
can resolve to IPv6 `::1` while PG listens on IPv4, causing `ConnectionRefusedError`).
Run the proxy with a **Scheduled Task** trigger "At startup" + "Every 5 minutes"
(recreate if missed) running a small launcher that starts WSL + the proxy.

### Option B — keep everything in WSL2
Prevent auto-suspend with a keepalive (run inside WSL):
```bash
# /etc/systemd/system/wsl-keepalive.service  (or a cron @reboot `sleep infinity`)
[Unit] After=network.target
[Service] ExecStart=/bin/sh -c 'while true; do sleep 60; done'
[Install] WantedBy=multi-user.target
```
Plus a Windows Scheduled Task that boots WSL (`wsl -u root service memory-proxy start`)
every 5 minutes so the proxy comes back after a suspend.

### Option C — Docker Desktop
Docker Desktop on Windows does NOT auto-stop. Use `docker compose up -d` for the
full stack (db + proxy); migrations auto-apply on first boot. The container
restart policy (`restart: unless-stopped`) keeps it alive.

## Auto-restart guarantees (all platforms)

- **Never** let the Hermes gateway own the proxy process — if the gateway
  restarts, it will kill a proxy it spawned. Run the proxy as its own service
  (systemd / Scheduled Task / Docker restart policy) so it survives gateway restarts.
- The repo does NOT auto-restart the gateway for you. Set up the service above once.

## Database bootstrap

First-time setup (applies all migrations + grants sequence privileges):

```bash
# migrations only (role already exists):
DATABASE_URL=postgresql://proxy:proxy@127.0.0.1:5432/memory_proxy \
  bash scripts/bootstrap_db.sh

# fresh DB — also create the role + grant:
DB_ADMIN_URL=postgresql://postgres@127.0.0.1:5432/memory_proxy \
  DB_USER=proxy DB_PASSWORD=proxy \
  bash scripts/bootstrap_db.sh
```

Without the sequence grant, `/v1/consolidate` and `/v1/reflect` fail with
`permission denied for sequence events_id_seq`.

## Health check

```bash
curl http://127.0.0.1:8899/health   # -> {"status":"ok"}
```
