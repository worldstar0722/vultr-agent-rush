# Submission checklist

Deadline: **Nov 8, afternoon MST** (verify the exact time on the lablab.ai event page).

## Required deliverables
- [ ] Public GitHub repo (check in an incognito window); PR merged to `main`, then set `BRANCH=main` in `deploy/cloud-init.yaml`
- [ ] README explains the Vultr architecture, trust boundaries, demo script, limitations
- [ ] Deployment on a Vultr VM documented and tested once from scratch (`deploy/DEPLOY.md`)
- [ ] Public demo URL (open from a phone on mobile data); `/health` returns ok
- [ ] Demo video (2-3 min, follow the README demo script, record from the deployed app)
- [ ] Slides
- [ ] Team and project description entered on lablab.ai
- [ ] No secrets in the repo (`.env` is gitignored; no key in cloud-init)

## Track 2 requirements
- [ ] Multi-step enterprise workflow: queue, evidence, decision, closing
- [ ] Backend on a Vultr VM
- [ ] Human approval step visible (professor approval for Case A)
- [ ] Vultr Serverless Inference is optional. **Only claim live inference after** `/api/ai/status` shows `last_success_at` on the deployed VM (a real run, not a stub). Until then say "mock AI" or "integration implemented, live verification pending".
- [ ] Live verification done by the operator: first analysis run; a screenshot upload; a PDF/DOCX upload; the 429 budget response; restart keeps the counters (do NOT use `down -v`)
- [ ] Budget: `AI_LIFETIME_MAX_CALLS` and the per-call caps reviewed and still within the authorised total spend

## Honesty check (say these out loud in the video)
- [ ] Synthetic data only; no Canvas integration; no messages are sent; no grade is changed
- [ ] Demo role switch is not access control
- [ ] FERPA / institutional review is required before any real data

## Judging criteria
| Criterion | Evidence to show |
|---|---|
| Application of Technology | Code-computed evidence vs AI drafting split; guardrails (fake citation removed, `9+1=11` flagged); SQLite on a Docker volume surviving restart; Vultr VM + firewall; optional Serverless Inference |
| Presentation | Case A walkthrough in 2-3 minutes; clear role switch; readable UI; rehearsed demo |
| Business Value | Real pain: duplicated replies, scattered evidence, untracked exception decisions. TODO: numbers (time per case, cases per term) with sources or labelled estimates |
| Originality | Case-management layer on top of the LMS instead of another grading chatbot; AI cannot approve or change anything; professor-only exceptions |

## Final hour
- [ ] Fresh clone + `docker compose up -d --build` works on a clean VM
- [ ] `docker compose restart` keeps decisions (volume check); "Reset demo data" before recording
- [ ] Demo URL still up; firewall exposes only 22/80/443
- [ ] Submit early
