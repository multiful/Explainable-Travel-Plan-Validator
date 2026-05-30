---
target: src/api/static/index.html
total_score: 31
p0_count: 0
p1_count: 0
timestamp: 2026-05-30T06-43-35Z
slug: src-api-static-index-html
---
## Design Health Score

| # | Heuristic | Prev | Now | Key Finding |
|---|-----------|------|-----|-------------|
| 1 | Visibility of System Status | 3 | 3 | Load-more still no per-request spinner; search mode transitions invisible |
| 2 | Match Between System and Real World | 3 | 3 | Language warm and natural throughout |
| 3 | User Control and Freedom | 3 | 3 | Overwrite warning fixed; slot deletion still unguarded |
| 4 | Consistency and Standards | 3 | 4 | Naming collision resolved; window.confirm gone; 목록에 저장 self-consistent |
| 5 | Error Prevention | 3 | 3 | Plan-load data loss protected; day/slot deletion still unguarded |
| 6 | Recognition Rather Than Recall | 3 | 3 | Clearer button labels; mobile radar tooltips still absent |
| 7 | Flexibility and Efficiency | 2 | 2 | No new accelerators; no copy-across-days or bulk add |
| 8 | Aesthetic and Minimalist Design | 3 | 3 | Hard fails surface first; mobile section nav reduces scroll confusion |
| 9 | Help Users Recover from Errors | 3 | 4 | API errors auto-return to Step 2; plan preserved |
| 10 | Help and Documentation | 2 | 3 | Pre-validation preview added; 목록에 저장 self-documents |
| **Total** | | **28/40** | **31/40** | **+3. Good, mid-band.** |

## Anti-Patterns Verdict

No regressions. All banned patterns absent. Inline overwrite warning and delete confirmation respect the no-modal rule. Mobile section nav is functional, not decorative. New minor asymmetry: pr-load is text-only while pr-del is icon-only — inconsistent visual vocabulary in the plans panel.

## Priority Issues

**[P2] H7 — No power-user path for multi-day planning** — No copy-day, no bulk-add, no place queue. Fix: duplicate day button, or batch-add queue in sidebar.

**[P2] H1 — Load-more search transitions are silent** — No indicator during server fetch. User can't distinguish "loading" from "broken." Fix: inline spinner on the load-more button.

**[P2] H5 — Day and slot deletion still unguarded** — 날 빼기 removes a full day instantly. Slot × is also immediate. Fix: inline confirm for day deletion when ≥1 filled slot; toast-undo for slot removal.

**[P3] Plans panel pr-load/pr-del asymmetry** — Text "불러오기" beside icon-only trash. Fix: both text or both icon with aria-labels.

**[P3] Mobile radar labels hover-only** — .tip tooltips triggered by mouseover; no touch fallback. Fix: tap-to-expand inline explanation.

## Persona Red Flags

**Jordan**: AI explanation accordion still uses "판단 기준" and "이동시간 행렬 분석" — internal language breaking honest-friend voice.

**Casey**: Builder footer with open save-name-row may stack 4 rows tall on narrow mobile (375px). Validate button may be pushed far down.

## Minor Observations

- _hardFailsDone flag pattern is correct but fragile; refactoring to a pre-built HTML variable would be safer.
- Mobile section nav href anchors rely on scroll-behavior:smooth being applied to the result container. Confirm.
- confirmSavePlan() handles empty-name Enter correctly via toast fallback.
