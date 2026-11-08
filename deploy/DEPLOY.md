# Deploy GradeCase to a Vultr VM

Console wording changes; anything marked **(verify in console)** must be checked in the Vultr UI. We do not state prices or plan names here: pick the smallest option that fits and check cost in the console. GradeCase uses synthetic data only; do not load real student records.

## 1. Create the firewall group
1. Console -> Firewall -> add a firewall group **(verify in console)**.
2. Inbound rules for TCP **22** (ideally limited to your IP), **80** and **443**. Everything else stays closed.

## 2. Create the instance
1. Console -> deploy a new cloud compute instance **(verify in console)**.
2. Image: **Ubuntu 24.04**. Location and size: your choice; **(verify in console)** CPU/RAM/cost. A small size is enough for a demo.
3. Add your SSH key.
4. Paste [`cloud-init.yaml`](cloud-init.yaml) into the cloud-init / user-data field **(verify field name in console)**.
   - It clones branch `BRANCH` (currently `claude/ecstatic-newton-ck2lvo`). **After the PR is merged, change `BRANCH` to `main`.**
5. Attach the firewall group and deploy.

cloud-init installs Docker, clones the repo to `/opt/gradecase`, copies `.env.example` to `.env`, and runs `docker compose up -d --build`. Watch progress with `tail -f /var/log/cloud-init-output.log`.

## 3. Check it
```bash
curl http://<SERVER_IP>/health
```
Expected: `{"status":"ok"}`. Then open `http://<SERVER_IP>/`. The app starts in mock-AI mode with seeded synthetic cases; no key is required.

## 4. Optional: turn on Vultr Serverless Inference
```bash
ssh root@<SERVER_IP>
cd /opt/gradecase && nano .env
```
Set `VULTR_INFERENCE_API_KEY` (create it in the Vultr console **(verify where)**), restart, and list real model ids:
```bash
docker compose up -d && curl -s http://localhost/api/models
```
Put one id into `LLM_MODEL`, then `docker compose up -d` again. If the call ever fails or times out, the UI shows "AI unavailable, rules-only view" and keeps working.

## 5. Redeploy after code changes
```bash
cd /opt/gradecase && git pull && docker compose up -d --build
```
Data lives in the `gradecase_data` Docker volume and survives restarts and rebuilds. To wipe it: use the "Reset demo data" link in the UI, or `docker compose down -v` (also deletes the Caddy certificate volume).

## 6. HTTPS (optional)
Create a DNS **A record** to the server IP, set `DOMAIN=your.domain` in `.env`, run `docker compose up -d`. Ports 80 and 443 must be open. Without `DOMAIN`, the app is served over plain HTTP on the server IP.

## Troubleshooting
- Page does not load: firewall group missing port 80, or `docker compose ps` shows a service down; `docker compose logs -f app`.
- `/api/models` returns 502: wrong key or base URL; the error text is in the response body.
- Data missing after redeploy: make sure you did not run `docker compose down -v`.
