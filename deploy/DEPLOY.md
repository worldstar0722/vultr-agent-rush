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

Live AI is optional and **unverified until you see a real success in the app**. Put secrets only in `.env` on the server (never in cloud-init, git or the browser).
```bash
ssh root@<SERVER_IP>
cd /opt/gradecase && nano .env
```
1. Set `VULTR_INFERENCE_API_KEY`, then discover the model ids your key can use: `docker compose run --rm app python -m app.tools models` (prints ids only). Set one as `LLM_MODEL`.
2. Review the caps in `.env.example` and keep or lower them: `AI_LIFETIME_MAX_CALLS` (default 50 attempts, ever), `AI_MAX_PROMPT_BYTES` (32768), `LLM_MAX_TOKENS` (2048), `LLM_REASONING_MAX_TOKENS` (128), `LLM_MAX_RETRIES` (0), `AI_CLIENT_HOURLY_LIMIT` (6). Values above the hard ceilings are clamped.
3. `docker compose up -d`, then check `curl -s http://localhost/api/ai/status`: expect `mode: configured`, your model, and `last_success_at: null`.
4. Run **one** analysis from the UI (Decision screen, Run analysis). `/api/ai/status` should now show `last_success_at` and `calls_used: 1`. If the call fails, the UI shows a redacted reason and a labelled rules-only draft; the attempt still counts.

If a call ever fails or times out the app keeps working with the rules-only view.

**The lifetime budget lives in the `gradecase_data` volume.** "Reset demo data" does not clear it and neither does a restart. `docker compose down -v` deletes the volume and therefore resets the counters and the attempt log: do not run it on a deployment with live AI. The only supported reset, after you have approved more spend, is:
```bash
docker compose exec app python -m app.tools reset-ai-budget --i-understand-this-reauthorises-spend
```
(The attempt log is kept.) There is no Docker socket mount, no code execution and no sandbox in this app.

## 5. Redeploy after code changes
```bash
cd /opt/gradecase && git pull && docker compose up -d --build
```
Data lives in the `gradecase_data` Docker volume and survives restarts and rebuilds. To wipe it: use the "Reset demo data" link in the UI, or `docker compose down -v` (also deletes the Caddy certificate volume).

## 6. HTTPS (optional)
Create a DNS **A record** to the server IP, set `DOMAIN=your.domain` in `.env`, run `docker compose up -d`. Ports 80 and 443 must be open. Without `DOMAIN`, the app is served over plain HTTP on the server IP.

## Troubleshooting
- Page does not load: firewall group missing port 80, or `docker compose ps` shows a service down; `docker compose logs -f app`.
- `/api/models` returns 502: wrong key or URL; the response gives a short redacted reason (never the key or provider text).
- Analysis returns 429: `ai_budget_exhausted` (lifetime cap reached: rules-only drafts still work) or `ai_client_throttled` (wait for `Retry-After`).
- Uploads: PDF/DOCX/text are parsed on the server and need the image's new dependencies (`pdfplumber`, `python-docx`); a rebuild (`docker compose up -d --build`) installs them.
- Data missing after redeploy: make sure you did not run `docker compose down -v`.
