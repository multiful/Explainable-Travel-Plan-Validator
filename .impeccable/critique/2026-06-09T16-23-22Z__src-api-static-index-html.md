---
target: src/api/static/index.html
total_score: 28
p0_count: 0
p1_count: 2
timestamp: 2026-06-09T16-23-22Z
slug: src-api-static-index-html
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | 15-30s LLM call shows static spinner — no pipeline progress |
| 2 | Match System / Real World | 3 | "VRPTW", "CRITICAL", "Risk Score" are system terms, not traveler language |
| 3 | User Control and Freedom | 3 | Removing a day (with all its places) is one-step, no undo |
| 4 | Consistency and Standards | 3 | Some interactive elements are buttons, others are role="button" divs; three different modal patterns |
| 5 | Error Prevention | 3 | No pre-flight warnings before 30s validation; empty slots pass submission |
| 6 | Recognition Rather Than Recall | 3 | Drag handle at 18% opacity; note button unlabeled; drag affordance invisible |
| 7 | Flexibility and Efficiency | 3 | "/" shortcut good; no keyboard shortcut to submit or navigate steps |
| 8 | Aesthetic and Minimalist Design | 2 | Step 2 sidebar: 14+ controls in header. Step 3: 9+ equally-weighted cards |
| 9 | Error Recovery | 3 | Network errors show generic box with no retry; accordion requires manual expansion per-finding |
| 10 | Help and Documentation | 2 | No tooltip for Risk Score meaning; scoring criteria buried; VRPTW unexplained |
| **Total** | | **28/40** | **Good** |

## Anti-Patterns Verdict

Mostly not AI-generated — one clear exception: the Step 3 score card is the hero-metric template (big number in circular gauge + PASS/FAIL badge + sub-score grid). This is the single element that reads as SaaS boilerplate. Hero section layers four visual treatments (gradient, radial glow, grid overlay, frosted badges) that compound to read as generative overreach.

## Overall Impression

Qtrip has a genuine design identity. Step 1 is excellent — focused, warm, well-sequenced. Step 3 breaks down: 9+ equal-weight cards where the most critical finding (trip is physically impossible) competes with the POI table. The score gauge is a missed opportunity. The biggest lever: redesign the result hierarchy so the critical finding leads.

## What's Working

1. Step 1 form architecture — one decision per card, progressive disclosure, good defaults
2. Korean copy voice — authentic, specific, honest ("솔직하게 짚어드려요")
3. Repair engine UI — three-tier repair with route comparison grid is outstanding

## Priority Issues

**[P1] Score card is the hero-metric template (banned pattern)**
Circular gauge + big number + supporting mini-cards. Replace with verdict-first layout: lead with the most critical finding, score as secondary context.
Suggested: /impeccable shape score card redesign

**[P1] Step 3 result hierarchy is flat**
9+ cards at identical elevation. CRITICAL issues don't visually dominate. Users scroll past equal-weight cards to find what broke.
Suggested: /impeccable layout Step 3 result page

**[P2] Step 2 sidebar: Wall of Options**
14+ interactive elements in a 290px header. Primary action (search) buried under filters.
Suggested: /impeccable distill Step 2 sidebar search panel

**[P2] No intermediate progress during 15-30s validation**
Static spinner for 30 seconds feels broken. No pipeline step indicator.
Suggested: /impeccable harden validation loading state

**[P3] Result page jargon: VRPTW, CRITICAL, Risk Score**
System terms in user-facing results. Replace with plain Korean equivalents.
Suggested: /impeccable clarify result page labels

## Persona Red Flags

**Jordan (First-Timer)**: Category pill filtering changes list silently; drag affordance invisible (18% opacity handle); "REVIEW" badge in English confuses Korean-first user; LLM accordion requires N individual taps to read all advice.

**Casey (Mobile)**: Builder becomes unusable when mobile keyboard is open (height: 70vh - keyboard). Suggestion dropdown hidden behind keyboard. Validation during app-switch returns to spinner with no completion state. Step 3 scrolls 2000px+ with 9+ full-width stacked cards.

**Yuna (어르신 trip planner)**: BF certification buried in penalty/bonus table — not surfaced as a meaningful accessibility signal. No BF-specific filter discovery path. PHYSICAL_STRAIN warning doesn't identify which day/transition is the problem.

## Minor Observations

- `.s1-hero::after` grid-line overlay reads as decorative noise over copy on mobile
- Sub-score labels in English (efficiency, feasibility, purpose_fit) break language consistency
- Monthly congestion chart title uses warning color (`--st-warn-fg`) regardless of actual congestion level
- "hero-step" numbered steps don't test well at narrow mobile widths

## Questions to Consider

- If the score card showed the most concrete problem first instead of the number — would users trust the product more?
- The place DB has 11 filter categories. How many do 80% of users actually use?
- What would the result page look like if hard fails occupied full width at top, everything else collapsed below?
