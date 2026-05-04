<!-- updated: 2026-05-04 | hash: 053976e0 | summary: 자차 이동 가정 명문화, 구현현황 전면 갱신(RepairEngine·CUMULATIVE_FATIGUE·per-day 경고), 데이터 자산 현황 재정리 -->

0. 실증 분석 근거 — "왜 이 시스템이 필요한가"

  두 데이터셋(총 194일)을 직접 분석해 검증 레이어의 필요성을 수치로 증명했다.

  [분석 대상]
  ┌──────────────────┬─────────────────────────────┬──────────┬────────────┐
  │ 데이터셋         │ 출처                        │ 경로 수  │ 분석 일정일│
  ├──────────────────┼─────────────────────────────┼──────────┼────────────┤
  │ 대한민국 구석구석 │ 한국관광공사 공식 추천       │ 50개     │ 101일      │
  │ 트리플 앱        │ 상업 여행 앱 (한국 경로 한정) │ 38개     │ 93일 (유효 89일) │
  └──────────────────┴─────────────────────────────┴──────────┴────────────┘

  [핵심 비교 지표]
  ┌──────────────────────────────┬────────────┬──────────────────────┐
  │ 지표                         │ 구석구석   │ 트리플 (유효일 기준) │
  ├──────────────────────────────┼────────────┼──────────────────────┤
  │ 이동 비율 평균                │ 0.157      │ 0.143                │
  │ 이동 과다 경고 비율 (≥20%)   │ 16.8%      │ 9.0%                 │
  │ 위험 비율 (≥40%)             │ 11.9%      │ 3.4%                 │
  │ 최악 사례 Travel Ratio       │ 0.86       │ 0.607                │
  │ 백트래킹 발생률               │ 44.6%      │ 32.3%                │
  │ VRPTW 개선 가능 케이스        │ 55.4%      │ 43.0%                │
  │ 지오코딩 성공률               │ 95.6%      │ 96.6%                │
  │ 평균 지리 분산                │ 36.3km     │ 21.5km               │
  │ 12h 초과 과밀 일정            │ 8.9%       │ —                    │
  └──────────────────────────────┴────────────┴──────────────────────┘

  [핵심 인사이트]
  - 공식 추천임에도 구석구석 16.8%가 경고, 11.9%가 위험 수준 → 검증 레이어 필요성 입증
  - 두 데이터셋 모두 40~55%의 일정이 VRPTW 순서 최적화 여지를 가짐
  - Travel Ratio 임계값은 1차 초기값(규칙 기반)이며, TourAPI 벌크 데이터 확보 후 재calibration 예정
  - "검증 가능성"이 추천 품질의 또 다른 축 — 구석구석이 트리플 대비 2배 비효율

1. 프로젝트 비전
  "우리는 여행을 추천하지 않는다. 그 일정이 실패할지, 성공할지를 증명한다."
  사용자가 수립한 여행 일정의 실행 가능성(Feasibility), 효율성(Efficiency), 목적 적합성(Purpose Fit)을
  데이터와 규칙 기반으로 검증하고, AI(LLM)를 통해 설명 가능한(Explainable) 피드백을 제공하는
  QA 레이어 시스템입니다.

  [확정 입력 스키마]
  필수: days (일별 장소 목록, 일별 1~8개) · party_size (1/2/3/4/5인 이상) ·
        party_type (혼자/친구/연인/가족/아기동반/어르신동반) · date (YYYY-MM-DD 시작일)
  선택: visit_order (미입력 시 리스트 순서 자동) · travel_type (cultural/nature/shopping/food/adventure)
  제외: 체류시간(dwell_db 자동 추정) · 이동수단(자차 고정 — Haversine × 22km/h 유효속도)
  ※ 이동수단 가정: 사용자는 자차(승용차)로만 이동한다. 22km/h는 시내 교통 지체·주차 포함
     유효 평균속도. 향후 Kakao Mobility B2B 연동 시 실도로 소요시간으로 교체 예정(정밀도 향상).

  [출력 구조]
  - 종합 Risk Score (0~100) + PASS/FAIL (기준: 60점)
  - 데이터 신뢰도 점수 (0~100) — Risk Score와 별도 출력
    예시: "종합 Risk Score: 68 / 100 | 데이터 신뢰도: 72 / 100 (운영시간 2건 누락 [Medium], 이동시간 1건 haversine [Low])"
  - 레이어별 하위 점수 (CRITICAL/WARNING 건수 + 패널티 breakdown)
  - 4단계 설명 (Fact · Rule · Risk · Suggestion) — 모든 패널티 항목에 적용
  - 개선 제안 (repair_suggestions — Minimal Interference 3단계 결정론적 교정 결과)
  - bonus_breakdown (웰니스/무장애 가산점 세부 항목)

2. 핵심 기능 및 구현 전략

  ① 일정 검증 (Validation) — 일자별(per-day) 수행

   - Hard Fail (Critical): 운영시간 충돌, 이동 불가 등 물리적으로 실행 불가능한 요소 탐지.
     `src/validation/hard_fail.py` — HardFailDetector
     이동 시간 = Haversine(A, B) / (22km/h) — 자차 기준 유효속도. 체류시간 = dwell_db 자동 추정.

   - Soft Warning: 동선 비효율·일정 과밀·체력 부담 등 품질 저하 요소 탐지.
     `src/validation/warning.py` — WarningDetector (6가지 유형, party_type별 임계 적용)

     ┌──────────────────┬──────────────────────────────────────────────────────────┐
     │ 경고 유형         │ 탐지 조건                                                │
     ├──────────────────┼──────────────────────────────────────────────────────────┤
     │ DENSE_SCHEDULE   │ 하루 총 시간(이동+체류) > party_type별 피로 한계 (1일 기준)│
     │ INEFFICIENT_ROUTE│ 실제 이동거리 > NN 휴리스틱 최적 경로 대비 30% 초과       │
     │ PHYSICAL_STRAIN  │ 총 이동거리 > party_type별 체력 한계 km                   │
     │ PURPOSE_MISMATCH │ 여행 테마 ↔ POI 구성 코사인 유사도 < 0.5 (전체 일정 기준) │
     │ AREA_REVISIT     │ 동일 카테고리 장소 3회 이상 연속 배치                      │
     │ CUMULATIVE_FATIGUE│ 다일 누적 피로: 3일 연속 75%+ 강도 OR 전날 85%+ → 다음날 60%+│
     └──────────────────┴──────────────────────────────────────────────────────────┘

     호출 방식: DENSE/INEFFICIENT/STRAIN/AREA_REVISIT은 일자별 독립 호출 (하루 기준 임계 적용)
               PURPOSE_MISMATCH는 전체 일정 POI로 1회 호출 (여행 전체 테마 판단)
               CUMULATIVE_FATIGUE는 파이프라인 후처리에서 per_day_pois 전체를 분석

   - 피로도 임계값 (`src/data/party_config.py`):
       혼자/친구/연인 = 12h, 가족 = 10h, 아기동반/어르신동반 = 8h (1일 기준)

  ② 점수 산정 (Scoring)

   - 5개 지표 가중합 → base_score, 이후 패널티·보너스 적용.
     `src/validation/scoring.py` — ScoreCalculator

     ┌──────────────────┬────────┬──────────────────────────────────────────────────┐
     │ 지표              │ 가중치 │ 계산 방식                                        │
     ├──────────────────┼────────┼──────────────────────────────────────────────────┤
     │ efficiency       │  0.30  │ nn_heuristic_km / actual_km (NN 최적 대비 효율)   │
     │ feasibility      │  0.25  │ hard×0.5 + temporal×0.3 + human×0.2              │
     │                  │        │ temporal threshold = fatigue_hours × 60 × num_days│
     │ purpose_fit      │  0.20  │ 1 − cosine_distance(intent_vector, activity_vector)│
     │ flow             │        │ 1 − (backtrack×0.65 + revisit_area×0.35)          │
     │                  │  0.15  │                                                   │
     │ area_intensity   │  0.10  │ 1 − dominant_category_ratio                      │
     └──────────────────┴────────┴──────────────────────────────────────────────────┘

     최종 점수 공식:
       adjusted = base_score − cluster_penalty − travel_ratio_penalty − theme_penalty + bonus
       → clamp(0, 100), Hard Fail 존재 시 ≤ 59

   - cluster_dispersion 패널티 (`src/scoring/cluster_dispersion.py`): 위반 합산 캡 −20
       M1. sigungu_switches: 같은 day 시군구 전환 ≥3회 −5 / ≥4회 −10
       M2. max_pairwise_distance_km: 하루 최대 직선거리 ≥30km −5 / ≥50km −10 / ≥100km −20
       M3. area_backtrack_count: 시군구 비연속 재진입 1회 −5 / 2회+ −10 (O(n))
       M4. geo_cluster_backtrack: DBSCAN(eps=2km) 지리 클러스터 비연속 재진입
           net = max(0, M4_count − M3_count) 로 M3 중복 패널티 제외

   - travel_ratio 패널티 (`src/scoring/travel_ratio.py`): 자차 기준 기간별 임계

     ┌──────────┬───────────────────────────────┬────────────┐
     │ 기간     │ 경고 구간                     │ 패널티     │
     ├──────────┼───────────────────────────────┼────────────┤
     │ 당일여행 │ 0.20~0.30 / 0.30~0.40 / 0.40+ │ -5/-10/-20 │
     │ 1박 2일  │ 0.12~0.18 / 0.18~0.25 / 0.25+ │ -5/-10/-20 │
     │ 2박 3일  │ 0.35~0.50 / 0.50~0.60 / 0.60+ │ -5/-10/-20 │
     └──────────┴───────────────────────────────┴────────────┘
     ※ 합성 일정 10,000개 생성 후 자차 기준 재calibration 예정 (W4)

   - theme_alignment 패널티 (`src/scoring/theme_alignment.py`):
       Claude API로 테마↔POI 구성 의미적 일치도 판정 (0.0~1.0).
       ≥0.8 → 0 / 0.6~0.8 → −5 / 0.4~0.6 → −10 / <0.4 → −20

   - BonusEngine (`src/scoring/bonus_engine.py`): 웰니스·무장애 가산점, 상한 +20점
       웰니스 방문: +3점/장소 (전 party_type)
       무장애 방문: +5점/장소 (아기동반·어르신동반·가족만)
       무장애 API ✅ 10,010건 수신 완료 / 웰니스 API ❌ 공공데이터포털 신청 필요
       (미등록 시 웰니스 0점 graceful 동작)

  ③ 설명 엔진 + 교정 (Explain & Repair)

   - ExplainEngine (`src/explain/`): Claude API로 구조화 JSON → 자연어 4단계 보고서 생성.
     [Fact → Rule → Risk → Suggestion] 모든 패널티·경고 항목에 적용.

   - RepairEngine (`src/explain/repair.py`): Hard Fail 발생 시 LLM 호출 전 결정론적 교정 시도.
     '장소 대체(substitution)'는 금지 — 사용자가 선택한 POI 목록을 보존하며 제약 조건만 최적화.

     교정 3단계 (순서대로 시도, 앞 단계 성공 시 다음 단계 스킵):
       1. Re-ordering  : 순열 전수 탐색(n ≤ 7, 최대 5,040회) → Hard Fail 없는 방문 순서 탐색
       2. Stay-time Tuning: dwell_db 최소값(원래의 50%, 절대 20분)까지 5분 단위 감소 시뮬레이션
       3. Outlier Deletion: savings = (before→i + i→after) − bypass 최대 장소가 1순위 삭제 후보
          "최소 삭제 → 최대 이동 절감" — 지리적 이상치를 수학적으로 식별

     3단계 후에도 미해결 시 LLM이 Fact 기반 삭제 제안 생성.
     결과: ValidationResult.repair → API repair_suggestions 필드로 전달.

   - 파이프라인 오케스트레이터 (`src/explain/pipeline.py`):
     ValidatorPipeline.run() 실행 순서:
       1→ HardFail 탐지 (per-day)
       2→ Warning 탐지 (per-day + 전체 PURPOSE_MISMATCH + CUMULATIVE_FATIGUE 후처리)
       3→ ScoreCalculator → base_score
       4→ ClusterDispersion 패널티
       5→ TravelRatio 패널티
       6→ ThemeAlignment 패널티 (travel_type 제공 시)
       7→ BonusEngine 가산점
       8→ 최종 점수 조립
       9→ generate_rewards
      10→ RepairEngine (Hard Fail 있을 때만)

3. 데이터 활용 구조

  ① 이동 시간 계산 — 자차 기준 (`src/utils/geo.py`)
   travel_min = haversine_km(A, B) / (22 / 60)
   22km/h = 시내 신호·교통·주차 지체 포함 유효 평균속도 (자차 단일 이동수단 가정).
   향후 Kakao Mobility B2B 연동으로 실도로 소요시간 교체 예정 (현재 구조는 유지).

  ② 좌표·메타데이터 조회 (`src/api/router.py`)
   이름 정규화 (`_normalize()`):
     1. 괄호 내용 제거: "한강공원(뚝섬지구)" → "한강공원"
     2. 지점명 분리: "스타벅스 강남점" → "스타벅스"
     3. 특수문자·공백 제거, 소문자화

   좌표 조회 우선순위:
     1차: data/pois.csv (TourAPI 원본, 20,168건)
     2차: data/naver/naver_metadata.json (보조, 1,000건)
     보정: _COORD_CATALOG (수동 큐레이션 86건 — pois.csv 오류 보정용)
     폴백: 서울 시청 (37.5665, 126.9780) — 신뢰도 Low

   데이터 신뢰도 3단계:
     High   — pois.csv 좌표 매칭 성공 + TourAPI 운영시간 정상 제공
     Medium — naver_metadata 보조 매칭 또는 dwell_db 추정값 적용
     Low    — 서울 중심 폴백 또는 운영시간 기본값 적용

  ③ 로컬 지식 베이스 (Knowledge Base)
   - Dwell DB (`src/data/dwell_db.py`): POI 카테고리별·개별 POI별 권장 체류 시간.
     5단계 폴백: 수동 오버라이드 → lclsSystm 3-depth → 1-depth → contentTypeId → 기본값.
     권장 범위 50% 미만 입력 시 WARNING. 수동 큐레이션 50개+ 핵심 POI 포함.

   - Hours DB (`src/data/hours_db.py`): POI 운영시간 룩업.
     TourAPI detailIntro2 데이터 기반 (W2 완료 후 operating_hours.csv로 교체 예정).

   - Naver 블로그 KB: 1,000개 POI 규칙 기반 메타데이터.
     필드: waiting / crowd_level / reservation_required / parking / price_level /
            sentiment(부정 신호 ≥2회만 수집) / summary_text(RAG용, 현재 미활성).

   - Congestion Stats (`data/congestion_stats.csv`): 4,174 장소 월별 방문객 통계.
     혼잡 계수(0.0~1.0) 테이블화 → congestion_engine.py로 성수기 판정.
     서울 소재 POI는 서울 도시데이터 API(실시간) 우선, 나머지는 통계 기반 폴백.

4. 설계 철학

  ① 수학적 교정 도구 (Constraint-based Repair, NOT a Recommender)
   - "우리는 새로운 장소를 추천하지 않는다. 사용자의 선택을 제약 조건 내에 맞춘다."
   - 장소 대체(substitution)는 금지. 순서·시간·삭제 세 가지 축으로만 교정.
   - RepairEngine은 LLM 없이 결정론적 알고리즘으로 먼저 교정을 시도한다.

  ② 기회비용 중심의 벤치마킹 (Benchmarking Opportunity Cost)
   - AI는 판단하지 않는다: "이 순서를 유지하기 위해 최적 경로 대비 40분이 추가 소요됩니다"
     라는 데이터 증거를 제시한다. 판단은 사용자의 몫이다.

  ③ 최소 간섭 수정 원칙 (Minimal Interference)
   - 우선순위: 재배치(Re-ordering) → 체류 조정(Stay-time Tuning) → 삭제(Deletion)
   - 삭제 기준: 이동 거리 절감 최대 장소(지리적 이상치) — "최소 삭제, 최대 효율"

  ④ LLM 역할 분리
   - 수치 계산(이동 시간·체류시간·Efficiency Gap·교정)은 결정론적 규칙 엔진 전담.
   - Claude API는 규칙 엔진 산출 JSON을 자연어 보고서로 변환하는 역할만 수행.
   - 예외: ThemeAlignmentJudge — 테마↔장소 의미적 일치도는 규칙으로 정량화 불가,
     LLM이 직접 판정하는 유일한 예외. 판정 근거는 프롬프트에 명시적으로 주입.

5. 서비스 포지셔닝

  ┌──────┬──────────────────────────────┬──────────────────────────────────────────┐
  │ 구분 │ 대상                         │ 가치                                     │
  ├──────┼──────────────────────────────┼──────────────────────────────────────────┤
  │ B2G  │ 지자체 · 한국관광공사         │ 공식 추천 코스 품질 점검 자동화           │
  │      │                              │ → 구석구석 16.8% 경고 사례 사전 차단     │
  ├──────┼──────────────────────────────┼──────────────────────────────────────────┤
  │ B2B  │ 여행 앱 · 플랫폼              │ AI 생성 일정 배포 전 QA 게이트            │
  │      │                              │ → final_score < 60 시 일정 재생성 트리거 │
  ├──────┼──────────────────────────────┼──────────────────────────────────────────┤
  │ B2C  │ 개인 여행자                   │ 직접 만든 일정의 실행 가능성 사전 검증   │
  │      │                              │ → 근거 기반 개선 제안 즉시 제공           │
  └──────┴──────────────────────────────┴──────────────────────────────────────────┘

6. 구현 현황

  ┌────┬─────────────────────────────────────────┬─────────────────────────────┬────────┐
  │ #  │ 요구사항                                │ 모듈                        │ 상태   │
  ├────┼─────────────────────────────────────────┼─────────────────────────────┼────────┤
  │ ①  │ 영업시간 준수 (Time Window)              │ validation/hard_fail.py     │ ✅ 완료│
  │ ②  │ 이동 시간 계산 (자차 Haversine × 22km/h)│ utils/geo.py                │ ✅ 완료│
  │    │  Kakao Mobility는 고도화 예정            │                             │       │
  │ ③  │ 체류시간 추정 (dwell_db)                 │ data/dwell_db.py            │ ✅ 완료│
  │ ④  │ 이동 vs 관광 시간 비율 (travel_ratio)   │ scoring/travel_ratio.py     │ ✅ 완료│
  │ ⑤  │ 경로 밀집도 + 백트래킹 (M1-M4)          │ scoring/cluster_dispersion  │ ✅ 완료│
  │ ⑥  │ 테마 일치성 (LLM)                       │ scoring/theme_alignment.py  │ ✅ 완료│
  │ ⑦  │ 혼잡도 — 서울 실시간                    │ data/seoul_citydata_client  │ ✅ 완료│
  │ ⑧  │ 혼잡도 — 전국 계절성                    │ scoring/congestion_engine   │ ✅ 완료│
  │ ⑨  │ 웰니스·무장애 가산점                    │ scoring/bonus_engine.py     │ ✅ 완료│
  │ ⑩  │ FastAPI /validate + /places 엔드포인트  │ api/main.py · router.py     │ ✅ 완료│
  │ ⑪  │ 브라우저 검증 UI (장소 DB + 결과 시각화)│ api/static/index.html       │ ✅ 완료│
  │ ⑫  │ Minimal Interference RepairEngine       │ explain/repair.py           │ ✅ 완료│
  │    │  (재배치 → 체류조정 → 이상치삭제 3단계) │                             │       │
  │ ⑬  │ 누적 피로도 경고 (CUMULATIVE_FATIGUE)   │ validation/warning.py       │ ✅ 완료│
  │    │  per-day Warning 탐지 + cross-day 분석  │ explain/pipeline.py         │       │
  └────┴─────────────────────────────────────────┴─────────────────────────────┴────────┘

7. 성공 지표

  ┌──────────────────────┬────────────────┬──────────────────────────────────┐
  │ 지표                 │ 목표           │ 측정 방법                        │
  ├──────────────────────┼────────────────┼──────────────────────────────────┤
  │ Hard Fail 탐지 정확도 │ ≥ 90%          │ Synthetic test (의도적 Hard Fail)│
  │ API 응답 시간         │ < 10초 (warm)  │ time curl 측정                   │
  │ Warning 탐지 정확도  │ ≥ 75%          │ 수동 라벨링 20개 일정 기준       │
  │ 테스트 커버리지       │ ≥ 80% (src/)   │ pytest --cov=src                 │
  │ 전체 파이프라인 성공률│ ≥ 95%          │ 10개 일정 반복 실행              │
  └──────────────────────┴────────────────┴──────────────────────────────────┘

8. 데이터 자산 현황 및 고도화 계획

  목표: "외부 API 의존을 끊고, 측정 가능한 자체 데이터 자산을 갖춘 검증 엔진으로 진화"

  [현재 데이터 자산 — 2026-05-04]
  ┌────────────────────────────┬─────────────────────────────────────────────────────┐
  │ 파일                       │ 내용                                                │
  ├────────────────────────────┼─────────────────────────────────────────────────────┤
  │ data/pois.csv              │ TourAPI 수집 20,168 POI (좌표·카테고리·주소) ← 1차  │
  │ data/congestion_stats.csv  │ 4,174 장소 혼잡도 통계 (월별 방문객·congestion_score)│
  │ data/naver/                │ 1,000 POI Naver 메타 (웨이팅·예약·주차·블로그 요약) │
  │ data/wellness_places.json  │ 무장애 10,010건 수집 완료 / 웰니스 미수집           │
  └────────────────────────────┴─────────────────────────────────────────────────────┘

  [좌표 커버리지 — congestion_stats 4,174개 기준]
  - pois.csv 매칭: 2,484개 (+naver 보조 86개 = 2,570개, 61.6%)
  - 미매칭 1,604개 (38.4%) → 서울 중심 폴백, 신뢰도 Low
  - 개선 완료: _normalize() 강화로 괄호 내용·지점명 분리 → 커버리지 추가 개선 예상

  [현재 한계 → 해결 방식]
  ┌──────────────────────────────┬──────────────────────────────────────────────────┐
  │ 현재 한계                    │ 해결 방식                                        │
  ├──────────────────────────────┼──────────────────────────────────────────────────┤
  │ pois.csv 20,168건 (목표 26만)│ W1 부분 완료. 잔여 ~24만건 추가 수집 예정       │
  │ 운영시간 결측 빈번             │ detailIntro2 enrich → operating_hours.csv (W2)  │
  │ congestion 미매칭 38.4%       │ 이름 정규화 개선(일부 완료) + Kakao 재매칭 (W3)  │
  │ Travel Ratio 임계값 표본 빈약 │ 합성 일정 10,000개로 자차 기준 재산출 (W4)       │
  │ 합성 평가 수단 부재            │ 26만 POI → 비효율 일정 의도 생성 → 탐지율 측정 │
  └──────────────────────────────┴──────────────────────────────────────────────────┘

  [마일스톤]
  ✅ W0: 프로토타입 Web UI + API 서버 (FastAPI /validate, /places) + RepairEngine
  🟡 W1: TourAPI 벌크 수집 → pois.csv (20,168 완료 / 목표 26만)
  ⬜ W2: detailIntro2 enrich → operating_hours.csv
  🟡 W3: 미매칭 이름 보정 (괄호·지점명 분리 완료 / Kakao Entity Resolution 미적용)
  ⬜ W4: 합성 일정 생성기 + Travel Ratio 임계값 자차 기준 재calibration
  ⬜ W5: synthetic_eval — 탐지율(precision/recall) 측정
  ⬜ W6: LLM 프롬프트 v2 (cat1/cat2/cat3 한글명 통합)
