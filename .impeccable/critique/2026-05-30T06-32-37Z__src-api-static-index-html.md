---
target: src/api/static/index.html
total_score: 28
p0_count: 0
p1_count: 2
timestamp: 2026-05-30T06-32-37Z
slug: src-api-static-index-html
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Load-more has no per-request spinner; search mode transitions are invisible |
| 2 | Match System / Real World | 3 | Language is warm and natural; "검증" is mildly technical but not egregious |
| 3 | User Control and Freedom | 3 | No undo for slot deletion; loading saved plan silently overwrites unsaved work |
| 4 | Consistency and Standards | 3 | "내 일정" means two different things (mobile tab vs. header button) |
| 5 | Error Prevention | 3 | Loading saved plan can destroy unsaved work without warning |
| 6 | Recognition Rather Than Recall | 3 | Radar labels and score thresholds lack contextual explanation on mobile |
| 7 | Flexibility and Efficiency | 2 | No copy-across-days, no bulk add, one keyboard shortcut only |
| 8 | Aesthetic and Minimalist Design | 3 | Step 3 has 12+ peer-weight sections with no reading order signal |
| 9 | Help Users Recover from Errors | 3 | API errors navigate to Step 3 without auto-returning to the plan |
| 10 | Help and Documentation | 2 | No pre-validation preview; no mobile tooltips; save feature undiscoverable |
| **Total** | | **28/40** | **Good** |

## Anti-Patterns Verdict

Passes product slop test. Orange + navy + mint palette avoids travel-app blue-sky reflex. Copy is genuinely Korean. No banned patterns detected. Two mild concerns: category color-coding is a common travel-app pattern; plans panel list rows have generic SaaS feel without brand voice.

Deterministic scan: detect.mjs bundled binary unavailable — manual fallback. No side-stripe borders, gradient text, or hero metrics in current code. window.confirm() in deletePlan() is inconsistent with app's custom UX pattern.

## Priority Issues

**[P1] "내 일정" naming collision** — Mobile tab (day builder) and header button (saved plans) share the same label. Vocabulary collision. Fix: rename saved plans entry point to "저장함" or "여행 기록"; rename mobile tab to "일정표".

**[P1] Loading saved plan silently destroys unsaved current work** — loadPlanIntoBuilder() replaces days/cfg without warning when _currentPlanId === null and plan has content. Fix: inline warning in plans panel before overwriting.

**[P2] Step 3 result page has no reading order signal** — 12+ sections with equal visual weight. Hard fails should precede or be elevated above the score when they exist. Fix: sticky summary strip on mobile, desktop two-column layout.

**[P2] No pre-validation preview** — First-timers validate into the unknown. Fix: one-line preview near the validate button explaining what the output is and how long it takes.

**[P3] "저장" button scope is ambiguous** — Same word as auto-save behavior; different meaning. Fix: rename to "목록에 저장" or "이름 붙여 저장".

## Persona Red Flags

**Jordan (First-Timer)**: Region grid doesn't signal single-select mode. Date picker affordance is weak (div styled as display element). AI explanation accordion uses internal language ("판단 기준", "이동시간 행렬 분석") that breaks the honest-friend voice.

**Casey (Mobile)**: Result page provides no section navigation on mobile — 800+ pixels of scroll with no jump-to. Cookie bar appears abruptly at 1200ms after page load.

**보경 (Family Planner)**: Per-leg travel time not shown, only day totals. "무장애" badge doesn't expand to specific accessibility features.

## Minor Observations

- window.confirm() in deletePlan() breaks app's inline UX pattern
- pr-del "삭제" lacks a trash icon to reinforce destructive action
- 검증 준비 완료 strip logic should also check no-day-has-only-empty-slots
- cookie-bar 1200ms delay feels abrupt; 400ms smoother
- hero-how describes steps, not value — a stronger hook would emphasize the outcome
