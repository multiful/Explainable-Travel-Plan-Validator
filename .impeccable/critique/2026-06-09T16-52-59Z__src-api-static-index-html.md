---
target: src/api/static/index.html
total_score: 31
p0_count: 0
p1_count: 1
timestamp: 2026-06-09T16-52-59Z
slug: src-api-static-index-html
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | 5단계 로딩 표시 추가됨 — 단계 전환이 실제 서버 진행과 무관한 타이머 기반 |
| 2 | Match System / Real World | 4 | 용어 전면 한국어화; _enumLabel 폴백으로 enum 키 노출 차단 |
| 3 | User Control and Freedom | 3 | 날 삭제 undo 없음 |
| 4 | Consistency and Standards | 3 | role="button" div vs button 혼용; 모달 패턴 3종 |
| 5 | Error Prevention | 3 | 제출 전 사전 검증 없음 |
| 6 | Recognition Rather Than Recall | 3 | 드래그 핸들 18% opacity; 메모 버튼 무라벨 |
| 7 | Flexibility and Efficiency | 3 | |
| 8 | Aesthetic and Minimalist Design | 3 | 게이지 제거 및 verdict-first로 개선; rcard-critical 계층 분리. Step 2 사이드바 밀도 미해결 |
| 9 | Error Recovery | 3 | |
| 10 | Help and Documentation | 3 | verdict-first로 핵심 결과 accordion 앞 노출; 점수 기준 설명 아직 없음 |
| **Total** | | **31/40** | **Good (+3 from 28)** |

## Anti-Patterns Verdict

게이지 제거 효과: 원형 게이지는 사라졌다. 점수 카드가 더 이상 hero-metric template처럼 보이지 않는다. 판정 텍스트("이 일정, 좋아요!")가 1.65rem 굵은 활자로 먼저 나타나는 구조는 product register에 적합하다.

새로 발견된 자체 도입 문제: 뱃지와 .score-verdict 텍스트가 동일한 문자열 (verdict 변수) 을 표시. "이 일정, 좋아요!"가 소형 뱃지와 1.65rem 대형 텍스트에 동시 노출 — 계층 없는 반복.

## Overall Impression

3점 상승 (28→31). 게이지 제거와 rcard-critical 도입으로 결과 페이지 시각 계층이 실질적으로 개선됐다. 이제 CRITICAL 발견 결과와 PASS 결과가 처음 보는 순간부터 다르게 느껴진다. 남은 핵심 문제: 점수 카드 메시지 중복, Step 2 사이드바 밀도, 로딩 마지막 단계 정지.

## What's Working

1. 판정 텍스트가 점수보다 앞에 나온다. "이 일정, 좋아요!"가 숫자보다 먼저 읽힘.
2. rcard-critical 빨간 테두리+헤더로 CRITICAL 카드가 9개 동일-weight 카드에서 분리됨.
3. 로딩 단계 "(1/5) 운영시간·좌표 확인 중" 이 정적 스피너보다 신뢰감 있음.

## Priority Issues

**[P1] 점수 카드 메시지 중복 (self-introduced)**
뱃지와 verdict div에 동일 문자열 2회. 뱃지를 "통과 ✓"/"검토 필요"/"재구성 필요"로 축약해 계층 분리.
Suggested: /impeccable clarify — score card badge vs verdict text

**[P2] 로딩 마지막 단계에서 멈춤**
4.2s 타이머가 (5/5)에 도달 후 정지. 30초 이상 API 대기 시 마지막 단계에서 15초+ 고정 — 원래 정적 스피너 문제 재발.
Fix: 마지막 단계 텍스트에 "…" 순환 애니메이션 추가.
Suggested: /impeccable harden — validation loading last-step idle

**[P2] Step 2 사이드바 옵션 과밀 (미해결)**
290px 패널 헤더에 14+ 컨트롤 동시 노출.
Suggested: /impeccable distill Step 2 sidebar

## Persona Red Flags

**Jordan (첫 사용자)**: "이 일정, 좋아요!" 뱃지+verdict 동시 노출이 오류처럼 느껴짐. 로딩 단계는 이해하기 쉬워졌음.
**Casey (모바일)**: 마지막 로딩 단계 고정 시 앱 전환 후 완료/실패 구분 불가. rcard-critical 모바일에서 잘 작동함.
**Yuna (어르신 동반)**: BF 접근성 정보 + PHYSICAL_STRAIN 어느 날짜인지 미해결.

## Minor Observations

- 히어로 섹션 4중 시각 레이어 여전히 과잉
- 월간 혼잡도 차트 타이틀이 낮은 혼잡도에도 경고 컬러 사용
- rcard-critical border !important가 dark mode의 rcard 일괄 override와 충돌 가능성

## Questions to Consider

- "뱃지를 '통과 ✓'/'검토'/'재구성'으로 축약하고 verdict div를 유일한 주요 메시지로 두면?"
- "로딩 마지막 단계에 점 애니메이션 5줄로 '처리 중' 신호 유지?"
- "Yuna 페르소나의 BF 접근성 정보를 결과 상단 카드로 꺼내면 차별화 기능이 보인다"
