<!-- updated: 2026-09-12 | hash: d99f30a1 | summary: gun/ 폴더 — 새로 추가하거나 수정한 문서들의 인덱스 -->
# `gun/` 폴더 — 신규·수정 문서 인덱스

> 본 폴더는 프로젝트의 **신규 추가** 또는 **기존 문서 수정** 산출물을 모은다.
> 원본 `docs/` 폴더의 PRD/ARCHITECTURE/ADR/ENHANCEMENT_PLAN은 변경하지 않고,
> 그에 대한 **갱신·보완·결정사항**은 모두 여기에 기록한다.

## 문서 목록

| 파일 | 목적 | 영향 받는 원본 문서 |
|---|---|---|
| `README.md` | 본 인덱스 | — |
| `DESIGN_RECONCILIATION.md` | PRD ↔ ENHANCEMENT_PLAN ↔ 실제 코드 간 3대 충돌(점수체계 교체 / 누락 Warning 2건 / Neo4j 연기) 명문화 | `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/ENHANCEMENT_PLAN.md`, `docs/ADR.md` |

## 사용 규칙

1. **문서 수정**: 원본을 직접 고치지 말고, 이 폴더에 보강 문서를 추가한다.
2. **메타 헤더**: 모든 `.md` 첫 줄에 `<!-- updated: YYYY-MM-DD | hash: 8hex | summary: ... -->` 형식 유지 (CLAUDE.md 규약).
3. **상호 참조**: 본 폴더 문서가 원본을 갱신할 때, 어느 섹션을 대체/보강하는지 명시한다.

## 적용 우선순위 (READ ORDER)

원본 → 본 폴더 순으로 읽으면 의도가 명확해진다:

```
1. docs/PRD.md            (제품 비전 + MVP 정의)
2. docs/ARCHITECTURE.md   (시스템 흐름 + Neo4j 설계)
3. docs/ENHANCEMENT_PLAN.md   (6대 패널티 — VRPTW + 3 scoring 모듈)
4. gun/docs/DESIGN_RECONCILIATION.md   ⭐ (위 3개의 충돌 해소 + 미반영 항목 결정)
```
