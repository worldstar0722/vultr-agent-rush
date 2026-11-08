# GradeCase product plan

> **Status: stub.** The full team plan document was announced for this commit but its text was not included in the request. This file therefore holds only the product context that already appears in [REBUILD_SPEC.md](REBUILD_SPEC.md). Replace it with the team's plan.

## What it is

A case desk for academic grading exceptions. Canvas holds submission history, rubrics, status changes and an inbox, but when a student writes "I submitted on time but it shows late" the TA must cross-reference several records across channels by hand. GradeCase connects them into one case with evidence, rules and an approval trail.

## Principle

**AI explains, humans decide.** The AI classifies, summarizes and drafts. Times, scores and deductions are computed by code. Policy exceptions require professor approval. The system never auto-corrects grades or sends messages.

## Recurring TA pain points (observed in IS 3060)

1. Submission attempt conflicts (on-time first attempt, late resubmission)
2. Score vs rubric mismatches (rubric saved, grade box different)
3. Duplicate inquiries across Canvas Inbox, email and submission comments
4. Score/posting status confusion (graded is not posted; auto-zeros after a deadline change)
5. Evidence in unexpected places (screenshots, links, comments instead of file uploads)

## Demo scene

A student says "I submitted on time but it's marked late." GradeCase shows the two attempts beside the policy, creates a review item, and the TA escalates to the professor or closes with an evidence-backed reply.
