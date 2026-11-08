# GradeCase Rebuild Specification
## For Claude Code — implement exactly as written

---

## PRODUCT CONTEXT (from team plan document)

GradeCase is a case desk for academic grading exceptions. The core insight:
"정보는 있는데, 사건은 없다" — Canvas has submission history, rubrics, status changes, and Inbox.
But when a student asks "I submitted on time but it shows late", the TA must manually cross-reference
multiple records across channels. GradeCase connects these into one case with evidence, rules, and an approval trail.

Key principle: **AI explains, humans decide.** The AI classifies, summarizes, and drafts.
But times, scores, and deductions are computed by code (never by the AI). Policy exceptions
require professor approval. The system never auto-corrects grades or sends messages.

5 recurring TA pain points (from real IS 3060 observations):
1. Submission attempt conflicts (on-time first attempt, late resubmission)
2. Score vs rubric mismatches (rubric saved but grade box different)
3. Duplicate inquiries across Canvas Inbox + email + submission comments
4. Score/posting status confusion (graded ≠ posted, auto-zeros after deadline change)
5. Evidence in unexpected places (screenshots, links, comments instead of file uploads)

The hackathon demo scene: Student says "I submitted on time but it's marked late."
GradeCase shows two attempts side by side with the policy, creates a review item,
and the TA escalates to professor or closes with an evidence-backed reply.

## PROBLEM STATEMENT
The current app looks like a basic CRUD prototype. Competitors have AI agents doing visible, measurable work in real-time. GradeCase must show the AI **working**, not just display results.

## PITCH (one line)
"GradeCase: an AI agent that reads your grading evidence, catches errors humans miss, and drafts replies — with every claim verified against the records before a human sees it."

---

## PART 1: VISUAL DESIGN SYSTEM

### Color Tokens (CSS custom properties)
```
--bg: #ffffff
--bg-subtle: #f8fafc
--bg-muted: #f1f5f9
--surface: #ffffff
--border: #e2e8f0
--border-strong: #cbd5e1

--text: #0f172a
--text-secondary: #475569
--text-muted: #94a3b8

--brand: #1e40af (deep blue)
--brand-light: #3b82f6
--brand-bg: #eff6ff
--brand-border: #bfdbfe

--success: #059669
--success-bg: #ecfdf5
--warning: #d97706
--warning-bg: #fffbeb
--danger: #dc2626
--danger-bg: #fef2f2

--sidebar-bg: #0f172a
--sidebar-text: #e2e8f0
--sidebar-muted: #64748b
--sidebar-active-bg: rgba(59,130,246,0.15)
--sidebar-active-border: #3b82f6
```

### Typography
```
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif
--font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace

Font sizes: 11px (label), 13px (body small), 14px (body), 16px (h3), 18px (h2), 24px (h1), 32px (page title)
Font weights: 400 (body), 500 (medium), 600 (semibold), 700 (bold)
Line heights: 1.4 (headings), 1.6 (body)
Letter spacing: -0.02em (h1), -0.01em (h2), 0.05em (uppercase labels)
```

### Load Inter and JetBrains Mono from Google Fonts in index.html <head>

### Spacing Scale
4, 8, 12, 16, 20, 24, 32, 40, 48, 64

### Border Radius
4px (small/badges), 8px (inputs/cards), 12px (large cards), 16px (modals)

### Shadows
```
--shadow-xs: 0 1px 2px rgba(0,0,0,0.04)
--shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)
--shadow-md: 0 4px 6px rgba(0,0,0,0.04), 0 2px 4px rgba(0,0,0,0.04)
--shadow-lg: 0 10px 15px rgba(0,0,0,0.06), 0 4px 6px rgba(0,0,0,0.04)
```

---

## PART 2: LAYOUT STRUCTURE

### Sidebar (220px fixed, dark)
```
┌──────────────────────┐
│ [logo] GradeCase     │  ← 36px round brand-color icon + wordmark
│ Academic case desk   │
│                      │
│ ▸ Dashboard          │  ← NEW page
│ ▸ Case Queue         │  
│ ▸ Board              │
│ ▸ Calendar           │
│ ─────────────────    │
│ ▸ New case           │  ← upload/manual
│                      │
│                      │
│                      │
│ ┌──────────────────┐ │
│ │ TA ◉  Professor  │ │  ← compact toggle, 28px height
│ └──────────────────┘ │
│                      │
│ ┌──────────────────┐ │  ← AI status card
│ │ ● Connected      │ │
│ │ qwen3.8-flash    │ │
│ │ 190/200 calls    │ │
│ │ ████████░░ 95%   │ │  ← visual progress bar
│ └──────────────────┘ │
└──────────────────────┘
```

Active nav item: left 3px brand-color border + subtle brand-bg

### Main Content Area
- Max-width: 1100px
- Padding: 32px
- Top bar: breadcrumb left, workspace badge right (no full-width bar — just text)

### Mobile (≤ 768px)
- Sidebar becomes 56px horizontal top bar with icon-only nav
- Hamburger menu reveals full sidebar as overlay

---

## PART 3: DASHBOARD PAGE (NEW — #/dashboard, default landing page)

This is the first thing users see. It must feel like an analytics dashboard.

### Layout: 2x2 grid of stat cards + 2 full-width sections below

```
┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│   5             │   3             │   1             │   ~12 min       │
│   Total cases   │   Need action   │   Closed today  │   Avg AI time   │
│   ↑2 this week  │                 │                 │   saved/case    │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┘

┌──────────────────────────────────┬──────────────────────────────────────┐
│   Cases by Status                │   AI Performance                     │
│   ██████████ New         5       │   Calls: 10/200 (5%)                 │
│   ░░░░░░░░░░ TA Review   0      │   Accepted: 8  Rejected: 2           │
│   ░░░░░░░░░░ Awaiting    0      │   Avg latency: 2.3s                  │
│   ░░░░░░░░░░ Closed      0      │   Guardrail catches: 3               │
│                                  │   ████████░░ 80% acceptance          │
└──────────────────────────────────┴──────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│   Recent Activity                                                       │
│   ● CASE-A analysis completed — AI draft accepted (2.4s)    2 min ago  │
│   ● CASE-B escalated to professor by TA Chen                5 min ago  │
│   ● CASE-C analysis rejected — guardrails caught POL-LATE   8 min ago  │
│   ● New case created from uploaded PDF                      12 min ago  │
└─────────────────────────────────────────────────────────────────────────┘
```

Stat cards: big number (32px bold), label below (13px muted), subtle trend indicator.
Charts: pure CSS bars (no chart library). Horizontal bars with percentage labels.
Activity feed: timeline dots with colored status, relative timestamps.

Data sources: all from existing GET /api/cases and GET /api/ai/status endpoints.

---

## PART 4: AI WORKFLOW VISUALIZATION (the differentiator)

When user clicks "Run analysis" on a case, show a **real-time animated pipeline** instead of just loading then showing results.

### Visual: vertical pipeline with 6 steps
```
  ┌─ ✓ Load evidence ──────── 11 records, 0ms ─────────── done
  │
  ├─ ✓ Compute rules ──────── 2 warnings, 1 gate ──────── done
  │
  ├─ ◉ Call AI model ──────── qwen3.8-flash-next ──────── 2.4s
  │     └─ Vultr Serverless Inference
  │        Prompt: 2,298 tokens → Completion: 904 tokens
  │
  ├─ ✓ Validate claims ────── All citations verified ───── done
  │     └─ 7 verified, 2 unverified, 0 rejected
  │
  ├─ ✓ Prepare draft ──────── From validated AI reply ──── done
  │
  └─ ◌ Await human ─────────── TA must review and decide
```

### Animation behavior:
1. Each step starts gray with a spinning icon
2. When the API responds, steps animate in sequence (200ms each) from top to bottom
3. Completed steps get green checkmark, failed steps get red X
4. The model call step shows a pulsing dot while "in progress"
5. Token counts and latency appear as the step completes
6. Final step stays amber (pending human)

### Implementation:
- The analysis API already returns `stages` array with key, status, detail, duration_ms
- Parse this array and render each stage with its real data
- Use CSS transitions and keyframe animations (no JS animation library)
- Show this pipeline prominently on the Evidence page after analysis runs

---

## PART 5: AI TRANSPARENCY PANEL

On the Evidence page, after analysis, show a card titled "What the AI found" with:

### Section 1: Classification
```
AI classified this as: Late flag  ←→  Rules agree: Late flag  ✓ Match
```

### Section 2: Verified vs Unverified statements (existing, but better styled)
```
✓ VERIFIED (7 statements)
  "The HW3 deadline is 23:59 on Nov 5" ← DL-A
  "Attempt 1 submitted at 22:40, 79 min before deadline" ← ATT-A1
  ...

⚠ UNVERIFIED (2 statements)  
  "Student claims they submitted on time" ← MSG-A1 (student claim, not record)
  ...
```

Each statement as a row with green/amber left border, evidence chip on the right.

### Section 3: Guardrail Results (NEW — makes the safety visible)
```
GUARDRAIL CHECK                              RESULT
─────────────────────────────────────────────────────
Citation check: all IDs exist?               ✓ Pass
Time check: AI times match records?          ✓ Pass  
Number check: scores match computed?         ✓ Pass
Commitment check: no grade promises?         ✓ Pass
                                      4/4 passed
```

If any guardrail FAILED (like CASE-C where AI cited non-existent POL-LATE-v2):
```
Citation check: all IDs exist?     ✗ FAILED
  AI cited "POL-LATE-v2" — this policy does not exist in the records.
  → AI reply REJECTED. Rules-only draft shown instead.
```

This is the **money shot** for the hackathon — showing the AI being caught and corrected.

---

## PART 6: EVIDENCE PAGE REDESIGN

### Two-column layout
Left (65%): evidence sections stacked vertically
Right (35%): sticky "What needs a decision" panel

### Evidence sections as distinct cards:
1. **Summary card** (accent left border): "What the records show" — 2-3 sentence AI summary
2. **AI Analysis card** (if analysis ran): classification, pipeline visualization, guardrail results
3. **Messages card**: inbound (gray bg) and outbound (blue-tint bg) messages with proper formatting
4. **Timeline card**: submission vs deadline with visual timeline (dots + connecting line + timestamps in monospace)
5. **Score card**: stat blocks (rubric total, entered, deduction, expected) as big-number cards in a row, with colored bar charts for scenarios
6. **Policy card**: expandable full policy text
7. **Audit trail**: collapsible, shows all records with timestamps

### Timeline visual (more polished):
```
     22:40  ●── Attempt 1 [ATT-A1]  ON TIME
     Nov 5      79 min before deadline
               hw3_v1.pdf
               │
     23:59  ■── Deadline [DL-A]
     Nov 5      ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
               │
     00:10  ●── Attempt 2 [ATT-A2]  LATE
     Nov 6      11 min after deadline
               hw3_v2.pdf  ← graded
```

● = circle for attempts (green/red fill), ■ = square for deadline (dark), dashed line after deadline

---

## PART 7: DECISION PAGE POLISH

### Numbered step flow (1→2→3→4) with visual step indicators
Each step is a card. Active step has brand-color left border. Completed steps show checkmark.

### Step 3 (Review reply): 
- Draft textarea with clean border
- "Draft only — not sent" badge prominently shown
- Below textarea: "Verified facts (7)" and "Unverified (2)" as expandable sections with colored left borders
- "Save edits" and "Regenerate" as secondary buttons

### Step 4 (Record decision):
- Primary action button: large, brand-color, with arrow icon
- Other actions: smaller, outlined buttons in a row
- Disabled buttons: grayed out with tooltip explaining why
- Decision log at bottom: timeline entries with role, action, timestamp

---

## PART 8: BOARD (KANBAN) POLISH

### 5 equal columns with min-width
- Column header: status name + count badge (brand-color circle with white text)
- Cards: white bg, 1px border, 8px radius, 3px left border colored by issue type
  - Late flag: blue left border
  - Score gap: amber left border  
  - Missing submission: red left border
- Card content: title (14px semibold), case ID + student (12px mono muted), assignment, owner, age
- "Move to" as a small icon button (⋮) in top-right corner of card, not a big dropdown
- Drag handle: subtle dots icon on left edge, visible on hover

---

## PART 9: CALENDAR POLISH

### Monthly grid
- Day cells: min-height 80px, subtle border
- Today: blue circle on date number
- Events shown as small colored pills inside cells:
  - Green pill: case resolved
  - Amber pill: case pending
  - Red pill: overdue
- Click a day → detail panel below shows cases for that day
- Month navigation: clean prev/next arrows with month/year centered

---

## PART 10: INTAKE (NEW CASE) PAGE

### Two modes: Upload file / Manual entry (tabs)

### Upload mode:
```
┌─────────────────────────────────────────────┐
│                                             │
│     📄                                      │
│     Drop a screenshot, PDF, or document     │
│     PNG, JPG, PDF, DOCX, CSV — up to 5 MB  │
│                                             │
│     [Browse files]                          │
│                                             │
└─────────────────────────────────────────────┘
```
- Drop zone: dashed 2px border, rounded corners, centered content
- On hover/drag: border becomes brand-color, bg becomes brand-bg
- After file selected: show file name, size, type chip
- "Extract with AI" button → shows extraction progress
- Results fill the form below for review before creating

### Manual entry mode:
Clean form with: Student ID, Course, Assignment, Issue type dropdown, Message textarea

---

## PART 11: RESPONSIVE (CRITICAL)

### Must be embedded as <style> in index.html <head> to avoid the CSS parser bug

```css
@media (max-width: 768px) {
  .app {
    display: flex !important;
    flex-direction: column !important;
  }
  .rail {
    position: static !important;
    height: auto !important;
    width: 100% !important;
    flex-direction: row !important;
    align-items: center !important;
    padding: 8px 12px !important;
    gap: 4px !important;
  }
  .rail .brand-sub,
  .rail .rail-foot,
  .rail .ai-badge { display: none !important; }
  .rail #nav { display: flex !important; gap: 2px !important; }
  .rail #nav a { padding: 6px 8px !important; font-size: 12px !important; }
  #view { padding: 16px !important; }
  .cols { display: block !important; }
  .board-cols { flex-direction: column !important; }
}
```

---

## PART 12: IMPLEMENTATION NOTES

1. Load fonts in index.html: `<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">`
2. All chart/graph visuals: pure CSS (width percentages, colored divs). No chart.js, no d3.
3. Animations: CSS @keyframes only. No JS animation libraries.
4. Dashboard data: computed client-side from GET /api/cases and GET /api/ai/status responses.
5. Activity feed on dashboard: computed from case decisions and analysis runs in the case data.
6. All existing functionality must keep working (analysis, decisions, intake, duplicates, reset).
7. The workflow pipeline visualization reads from the existing `stages` field in the analysis API response.
8. Push to same branch (claude/ecstatic-newton-ck2lvo). Do NOT merge to main.
