# Submission checklist

Deadline: **Nov 8, afternoon MST** (verify exact time on the lablab.ai event page). Tick items as you go.

## Required deliverables

- [ ] **Public GitHub repo** (check it is public in an incognito window)
- [ ] README explains the **Vultr architecture** (diagram is in README; update it if the design changes)
- [ ] README documents **deployment on a Vultr VM** (`deploy/DEPLOY.md` works from scratch - test it once)
- [ ] **Public demo URL** on the Vultr VM (open it from your phone on mobile data)
- [ ] **Demo video** uploaded, link in README
- [ ] **Slides** done, link in README
- [ ] Team members and project description entered on the lablab.ai submission form
- [ ] No secrets in the repo (`git log -p | grep -i key`; `.env` is gitignored)

## Track requirements

Track 1 - Blast Radius Zero
- [ ] Uses Vultr Serverless Inference (real key, `LLM_MODEL` set from `/api/models`)
- [ ] `SANDBOX_ENABLED=true` on the VM and the real Docker sandbox works (`docker pull` done)
- [ ] Demo shows one clear **containment moment** (red `blocked` event)

Track 2 - Powering the Future of Work
- [ ] Multi-step enterprise workflow, backend on a Vultr VM
- [ ] Human approval step visible in the demo
- [ ] (Optional) Serverless Inference used

## Judging criteria -> what to show

| Criterion | What judges look for | Our evidence (TODO) |
|---|---|---|
| Application of Technology | Real use of Vultr (VM, Serverless Inference), solid agent design | Architecture diagram; model chosen from `/api/models`; plan/act/verify timeline |
| Presentation | Clear story, working live demo, polished video/slides | 2-3 min video script; rehearsed demo; one-line pitch |
| Business Value | A real user with a real problem; why it's worth paying for | Target user, pain, cost/time saved (TODO: numbers with sources) |
| Originality | Something fresh, not a generic chatbot | What is different about our tools / safety story (TODO) |

## Final hour

- [ ] Fresh clone + `docker compose up -d --build` works on a clean VM
- [ ] Demo URL still up; firewall only exposes 22/80/443
- [ ] Record the video from the *deployed* app, not localhost
- [ ] Submit early; do not wait for the last minute
