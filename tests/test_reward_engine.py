"""RewardEngine 유닛 테스트."""

from __future__ import annotations

from src.data.models import Scores
from src.scoring.reward_engine import generate_rewards


def _scores(**kwargs) -> Scores:
    defaults = dict(efficiency=0.5, feasibility=0.9, purpose_fit=0.5, flow=0.5, area_intensity=0.5)
    defaults.update(kwargs)
    return Scores(**defaults)


class TestGenerateRewards:
    def test_hard_fail_returns_empty(self):
        rewards = generate_rewards(
            scores=_scores(flow=0.9, efficiency=0.9, purpose_fit=0.9),
            n_hard_fails=1,
            n_warnings=0,
            overall_travel_ratio=0.10,
            cluster_penalty=0,
        )
        assert rewards == []

    def test_excellent_flow_generates_message(self):
        rewards = generate_rewards(
            scores=_scores(flow=0.85),
            n_hard_fails=0,
            n_warnings=1,
            overall_travel_ratio=0.50,
            cluster_penalty=5,
        )
        assert any("동선" in r for r in rewards)

    def test_excellent_efficiency_generates_message(self):
        rewards = generate_rewards(
            scores=_scores(efficiency=0.90),
            n_hard_fails=0,
            n_warnings=1,
            overall_travel_ratio=0.50,
            cluster_penalty=5,
        )
        assert any("이동 경로" in r or "효율" in r for r in rewards)

    def test_low_travel_ratio_generates_message(self):
        rewards = generate_rewards(
            scores=_scores(),
            n_hard_fails=0,
            n_warnings=1,
            overall_travel_ratio=0.20,
            cluster_penalty=5,
        )
        assert any("이동" in r and "%" in r for r in rewards)

    def test_excellent_purpose_fit_generates_message(self):
        rewards = generate_rewards(
            scores=_scores(purpose_fit=0.85),
            n_hard_fails=0,
            n_warnings=0,
            overall_travel_ratio=0.50,
            cluster_penalty=5,
        )
        assert any("테마" in r or "목적" in r for r in rewards)

    def test_no_warnings_generates_message(self):
        rewards = generate_rewards(
            scores=_scores(),
            n_hard_fails=0,
            n_warnings=0,
            overall_travel_ratio=0.50,
            cluster_penalty=5,
        )
        assert any("주의사항" in r for r in rewards)

    def test_zero_cluster_penalty_generates_message(self):
        rewards = generate_rewards(
            scores=_scores(),
            n_hard_fails=0,
            n_warnings=1,
            overall_travel_ratio=0.50,
            cluster_penalty=0,
        )
        assert any("동선" in r or "지리" in r for r in rewards)

    def test_perfect_plan_all_messages(self):
        rewards = generate_rewards(
            scores=_scores(flow=0.9, efficiency=0.9, purpose_fit=0.9),
            n_hard_fails=0,
            n_warnings=0,
            overall_travel_ratio=0.15,
            cluster_penalty=0,
        )
        assert len(rewards) >= 5

    def test_mediocre_plan_few_messages(self):
        rewards = generate_rewards(
            scores=_scores(flow=0.5, efficiency=0.5, purpose_fit=0.5),
            n_hard_fails=0,
            n_warnings=2,
            overall_travel_ratio=0.60,
            cluster_penalty=10,
        )
        assert len(rewards) == 0
