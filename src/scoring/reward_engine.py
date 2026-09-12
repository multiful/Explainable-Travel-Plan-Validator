"""긍정 강화 메시지 생성 엔진 (Positive Reinforcement).

validate() 파이프라인에서 점수·통계를 받아 칭찬 메시지 list[str]을 반환.
Hard Fail이 있으면 빈 리스트 반환 (칭찬 불필요).

임계값:
  - flow ≥ 0.80        → 동선 흐름 우수
  - efficiency ≥ 0.80  → 이동 효율 우수
  - travel_ratio ≤ 0.25 → 이동시간 비율 낮음 (전체의 25% 이하)
  - purpose_fit ≥ 0.80  → 여행 테마 일치
  - n_warnings == 0     → 경고 없음
"""

from __future__ import annotations

from src.data.models import Scores

FLOW_EXCELLENT: float = 0.80
EFFICIENCY_EXCELLENT: float = 0.80
PURPOSE_FIT_EXCELLENT: float = 0.80
TRAVEL_RATIO_LOW: float = 0.25
CLUSTER_PENALTY_NONE: int = 0


def generate_rewards(
    scores: Scores,
    n_hard_fails: int,
    n_warnings: int,
    overall_travel_ratio: float,
    cluster_penalty: int,
) -> list[str]:
    """점수와 통계 기반으로 긍정 강화 메시지 생성.

    Returns:
        긍정 강화 메시지 리스트. Hard Fail 존재 시 빈 리스트.
    """
    if n_hard_fails > 0:
        return []

    messages: list[str] = []

    if scores.flow >= FLOW_EXCELLENT:
        messages.append(
            "동선 흐름이 매우 자연스럽습니다. 불필요한 되돌아감 없이 효율적인 순서로 구성되어 있어요."
        )

    if scores.efficiency >= EFFICIENCY_EXCELLENT:
        messages.append(
            "이동 경로가 최적에 가깝게 설계되었습니다. 최단 경로 대비 낭비 없는 동선이에요."
        )

    if overall_travel_ratio <= TRAVEL_RATIO_LOW:
        messages.append(
            f"전체 일정 중 이동에 쓰는 시간이 {overall_travel_ratio * 100:.0f}%로 낮습니다. "
            "여행지에서 보내는 시간이 충분해요."
        )

    if scores.purpose_fit >= PURPOSE_FIT_EXCELLENT:
        messages.append("선택하신 장소들이 여행 목적에 잘 맞습니다. 테마에 집중된 알찬 일정이에요.")

    if n_warnings == 0:
        messages.append(
            "일정에서 특별한 주의사항이 발견되지 않았습니다. 전반적으로 균형 잡힌 계획이에요."
        )

    if cluster_penalty == CLUSTER_PENALTY_NONE:
        messages.append(
            "하루 동선이 지리적으로 잘 집중되어 있습니다. 불필요한 이동 없이 근처 명소들을 효율적으로 묶었어요."
        )

    return messages
