# Deploy to a Vultr VM

Console wording changes; anything marked **(verify in console)** must be checked in the Vultr UI. We do not state prices or plan names here: pick the smallest option that fits and check cost in the console.

## 1. Create the firewall group
1. Console -> Firewall -> add a firewall group **(verify in console)**.
2. Add inbound rules for TCP **22** (SSH; ideally limited to your IP), **80** and **443**. Everything else stays closed.

## 2. Create the instance
1. Console -> Deploy a new instance (cloud compute) **(verify in console)**.
2. Image: **Ubuntu 24.04**. Location and size: your choice, **(verify in console)** CPU/RAM/cost. Docker + the sandbox are fine on a small size for a demo.
3. Add your SSH key.
4. Paste the contents of [`cloud-init.yaml`](cloud-init.yaml) into the cloud-init / user-data field **(verify field name in console)**.
5. Attach the firewall group from step 1, then deploy.

cloud-init installs Docker, clones the repo to `/opt/agent-rush`, copies `.env.example` to `.env` and starts the stack. It takes a few minutes; watch with `tail -f /var/log/cloud-init-output.log`.

## 3. Configure
```bash
ssh root@<SERVER_IP>
cd /opt/agent-rush
nano .env
```
Set at least:
- `VULTR_INFERENCE_API_KEY` (from the Vultr console **(verify where Serverless Inference keys are created)**)
- `LLM_MODEL` - run `curl -s localhost/api/models` first to see real model ids
- `PRODUCT_NAME`, `PRODUCT_TAGLINE`
- `DOMAIN` (optional, see below)
- `SANDBOX_ENABLED=true` only for Track 1 and only after uncommenting the docker socket lines in `docker-compose.yml` (read the security note there)

## 4. (Re)deploy
```bash
cd /opt/agent-rush
git pull
docker compose up -d --build
```
Check: `curl http://<SERVER_IP>/health` should return `{"status":"ok"}`, then open `http://<SERVER_IP>/`.
Logs: `docker compose logs -f app`.

## 5. HTTPS (optional)
1. Create a DNS **A record** for your domain pointing to the server IP.
2. Set `DOMAIN=your.domain` in `.env`, run `docker compose up -d`.
3. Caddy obtains a certificate automatically (ports 80 and 443 must be open).

Without `DOMAIN` the app is served over plain HTTP on the server IP, which is fine for a hackathon demo.

## Troubleshooting
- Page does not load: firewall group missing port 80, or `docker compose ps` shows a service down.
- `/api/models` returns 502: wrong key or base URL; the error text is included in the response.
- Sandbox shows `mock` in the page header: `SANDBOX_ENABLED` is not true, or the app cannot reach Docker (socket not mounted).
- Timeline freezes behind a proxy: SSE needs unbuffered proxying; the provided Caddyfile already sets `flush_interval -1`.
