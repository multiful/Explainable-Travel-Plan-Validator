"""Hard Fail 탐지기 (운영시간 충돌·이동 불가·일정 시간 초과)."""
from __future__ import annotations

from src.data.models import HardFail, ItineraryPlan, POI
from src.utils.geo import build_dist_cache, get_travel_min

DEFAULT_START_MINUTES: int = 9 * 60  # 09:00

HARD_FAIL_TYPES = {
    "OPERATING_HOURS_CONFLICT": "도착 예상 시간이 POI 운영시간 외",
    "TRAVEL_TIME_IMPOSSIBLE":   "이동시간이 이용 가능한 시간 창을 초과",
    "SCHEDULE_INFEASIBLE":      "전체 일정이 시간 내 수행 불가능",
}


class HardFailDetector:
    """여행 일정의 Hard Fail 조건을 탐지한다.

    External I/O 없음. matrix: dict[int, dict[int, dict]] 인덱스 기반.
    matrix[i][j] = {"travel_min": float, "distance_km": float, ...}
    origin_poi: 전날 숙소처럼 POI 목록 이전에 위치한 출발점. 첫 번째 이동 거리 계산에 사용된다.
    """

    def detect(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
        start_minutes: int = DEFAULT_START_MINUTES,
        origin_poi: POI | None = None,
    ) -> list[HardFail]:
        """Hard Fail 목록 반환. 없으면 빈 리스트."""
        # origin_poi 가 있으면 pois 앞에 가상 출발 인덱스(-1)로 붙여 처리
        effective_pois = pois if origin_poi is None else [origin_poi] + list(pois)
        offset = 0 if origin_poi is None else 1  # 실제 POI 인덱스 오프셋

        dist_cache = build_dist_cache(effective_pois)
        fails: list[HardFail] = []
        fails.extend(self._check_operating_hours(effective_pois, matrix, start_minutes, offset, dist_cache))
        fails.extend(self._check_travel_impossible(effective_pois, matrix, start_minutes, offset, dist_cache))
        fails.extend(self._check_schedule_infeasible(effective_pois, matrix, offset, dist_cache))
        return fails

    def _check_operating_hours(
        self,
        pois: list[POI],
        matrix: dict,
        start_minutes: int,
        offset: int,
        dist_cache: dict,
    ) -> list[HardFail]:
        """각 POI 도착 예상 시간이 운영시간 밖이면 Hard Fail."""
        fails: list[HardFail] = []
        current_time = float(start_minutes)

        for i, poi in enumerate(pois):
            if i < offset:
                # origin_poi: 출발점만 기록, 검사 생략
                current_time += poi.duration_min
                continue

            open_min = self._time_to_min(poi.open_start)
            close_min = self._time_to_min(poi.open_end)
            is_fallback = poi.open_start == "00:00" and poi.open_end == "23:59"

            arrive = (
                current_time
                if i == offset  # 첫 실제 POI (origin_poi 없으면 i==0)
                else current_time + get_travel_min(matrix, i - 1, i, pois[i - 1], poi, dist_cache)
            )

            if not is_fallback:
                if arrive < open_min:
                    fails.append(HardFail(
                        fail_type="OPERATING_HOURS_CONFLICT",
                        message=(
                            f"'{poi.name}' 도착 예정 {self._min_to_time(arrive)}, "
                            f"운영 시작 {poi.open_start} — 아직 문을 열지 않았습니다."
                        ),
                        evidence=f"도착 {self._min_to_time(arrive)} < 운영시작 {poi.open_start}",
                        confidence="Medium",
                        poi_name=poi.name,
                    ))
                elif arrive > close_min:
                    fails.append(HardFail(
                        fail_type="OPERATING_HOURS_CONFLICT",
                        message=(
                            f"'{poi.name}' 도착 예정 {self._min_to_time(arrive)}, "
                            f"운영 종료 {poi.open_end} — 이미 문을 닫았습니다."
                        ),
                        evidence=f"도착 {self._min_to_time(arrive)} > 운영종료 {poi.open_end}",
                        confidence="Medium",
                        poi_name=poi.name,
                    ))

            effective_arrive = max(arrive, open_min)
            current_time = effective_arrive + poi.duration_min

        return fails

    def _check_travel_impossible(
        self,
        pois: list[POI],
        matrix: dict,
        start_minutes: int,
        offset: int,
        dist_cache: dict,
    ) -> list[HardFail]:
        """이동시간이 이용 가능한 시간 창을 초과하면 Hard Fail."""
        fails: list[HardFail] = []
        current_time = float(start_minutes)

        for i, poi in enumerate(pois):
            open_min = self._time_to_min(poi.open_start)

            if i <= offset:
                effective_arrive = max(current_time, open_min)
                current_time = effective_arrive + poi.duration_min
                continue

            prev = pois[i - 1]
            travel_min = get_travel_min(matrix, i - 1, i, prev, poi, dist_cache)
            close_min = self._time_to_min(poi.open_end)
            is_fallback = poi.open_start == "00:00" and poi.open_end == "23:59"
            available_window = close_min - current_time

            if not is_fallback and travel_min > available_window:
                fails.append(HardFail(
                    fail_type="TRAVEL_TIME_IMPOSSIBLE",
                    message=(
                        f"'{prev.name}'→'{poi.name}' 이동 시간 {travel_min:.0f}분이 "
                        f"가용 시간 창 {available_window:.0f}분을 초과합니다."
                    ),
                    evidence=(
                        f"이동 {travel_min:.0f}분 > 가용 창 {available_window:.0f}분 "
                        f"(출발 {self._min_to_time(current_time)}, '{poi.name}' 종료 {poi.open_end})"
                    ),
                    confidence="High",
                    poi_name=poi.name,
                ))

            arrive = current_time + travel_min
            effective_arrive = max(arrive, open_min)
            current_time = effective_arrive + poi.duration_min

        return fails

    def _check_schedule_infeasible(
        self,
        pois: list[POI],
        matrix: dict,
        offset: int,
        dist_cache: dict,
    ) -> list[HardFail]:
        """실제 POI 들의 총 체류+이동 시간이 24시간 초과 시 Hard Fail."""
        real_pois = pois[offset:]
        total_dwell = sum(p.duration_min for p in real_pois)
        total_travel_min = 0.0
        for i in range(offset + 1, len(pois)):
            total_travel_min += get_travel_min(matrix, i - 1, i, pois[i - 1], pois[i], dist_cache)

        total_min = total_dwell + total_travel_min
        if total_min > 24 * 60:
            return [HardFail(
                fail_type="SCHEDULE_INFEASIBLE",
                message=(
                    f"총 일정 소요 시간 {total_min:.0f}분 ({total_min / 60:.1f}시간)이 "
                    f"24시간을 초과합니다."
                ),
                evidence=(
                    f"체류 {total_dwell}분 + 이동 {total_travel_min:.0f}분 "
                    f"= {total_min:.0f}분 > 1440분"
                ),
                confidence="High",
            )]
        return []

    @staticmethod
    def _time_to_min(hhmm: str) -> int:
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m

    @staticmethod
    def _min_to_time(minutes: float) -> str:
        m = int(minutes)
        return f"{m // 60:02d}:{m % 60:02d}"
