"""공유 지리 계산 유틸리티 — Haversine, NN 휴리스틱, 이동시간 조회."""
from __future__ import annotations

import math

_EARTH_R_KM = 6371.0
_SPEED_KM_PER_MIN = 22.0 / 60.0  # 22 km/h 유효 속도


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이의 Haversine 직선 거리(km)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_R_KM * math.asin(math.sqrt(a))


def build_dist_cache(pois: list) -> dict[tuple[int, int], float]:
    """POI 리스트의 모든 (i, j) 쌍 Haversine 거리(km)를 한 번에 계산해 반환.

    이 캐시를 nn_heuristic_km / get_travel_min 에 넘기면 중복 계산을 방지한다.
    """
    n = len(pois)
    cache: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                cache[(i, j)] = haversine_km(
                    pois[i].lat, pois[i].lng, pois[j].lat, pois[j].lng
                )
    return cache


def nn_heuristic_km(
    pois: list,
    dist_cache: dict[tuple[int, int], float] | None = None,
) -> float:
    """최근접 이웃 휴리스틱으로 추정한 최소 순회 거리(km).

    dist_cache 를 넘기면 Haversine 재계산 없이 조회한다.
    """
    if len(pois) <= 1:
        return 0.0
    visited = {0}
    current = 0
    total = 0.0
    while len(visited) < len(pois):
        best_d = float("inf")
        best_j = -1
        for j in range(len(pois)):
            if j not in visited:
                d = (
                    dist_cache[(current, j)]
                    if dist_cache is not None
                    else haversine_km(
                        pois[current].lat, pois[current].lng,
                        pois[j].lat, pois[j].lng,
                    )
                )
                if d < best_d:
                    best_d, best_j = d, j
        if best_j == -1:
            break
        total += best_d
        visited.add(best_j)
        current = best_j
    return total


def get_travel_min(
    matrix: dict,
    i: int,
    j: int,
    origin,
    dest,
    dist_cache: dict[tuple[int, int], float] | None = None,
) -> float:
    """matrix[i][j]['travel_min'] 조회, 없으면 Haversine 폴백(분).

    dist_cache 를 넘기면 폴백 시 재계산 없이 조회한다.
    """
    entry = (matrix.get(i) or {}).get(j)
    if entry and "travel_min" in entry:
        return float(entry["travel_min"])
    if dist_cache is not None and (i, j) in dist_cache:
        return dist_cache[(i, j)] / _SPEED_KM_PER_MIN
    return haversine_km(origin.lat, origin.lng, dest.lat, dest.lng) / _SPEED_KM_PER_MIN
