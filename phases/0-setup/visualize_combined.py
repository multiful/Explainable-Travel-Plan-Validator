"""
트리플 + 구석구석 비교 시각화
Figure 1: 트리플 단독 품질 리포트 (triple_quality_report.png)
Figure 2: 두 데이터셋 비교 (comparison_report.png)
"""
import json
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path
from collections import Counter

matplotlib.rcParams['font.family'] = ['Malgun Gothic', 'AppleGothic', 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False

BASE    = Path(__file__).resolve().parent
gg_raw  = json.loads((BASE / "analysis_result.json").read_text(encoding="utf-8"))
tri_raw = json.loads((BASE / "triple_analysis_result.json").read_text(encoding="utf-8"))

gg_entries  = gg_raw["entries"]
tri_entries = tri_raw["entries"]

C_OK   = "#4CAF50"
C_WARN = "#FF9800"
C_CRIT = "#F44336"
C_BG   = "#FAFAFA"
C_GG   = "#1565C0"
C_TRI  = "#7B1FA2"

gg_tr   = [e["travel_ratio"] for e in gg_entries  if e["travel_ratio"] is not None]
tri_tr  = [e["travel_ratio"] for e in tri_entries if e["travel_ratio"] is not None]
gg_dist  = [e["max_dist_km"] for e in gg_entries  if e["max_dist_km"] > 0]
tri_dist = [e["max_dist_km"] for e in tri_entries if e["max_dist_km"] > 0]
gg_dur   = [e["total_hr"] for e in gg_entries  if e["total_sec"] > 0]
tri_dur  = [e["total_hr"] for e in tri_entries if e["total_sec"] > 0]

gg_warn  = sum(1 for v in gg_tr  if 0.20 <= v < 0.40)
gg_crit  = sum(1 for v in gg_tr  if v >= 0.40)
gg_norm  = len(gg_tr) - gg_warn - gg_crit
tri_warn = sum(1 for v in tri_tr if 0.20 <= v < 0.40)
tri_crit = sum(1 for v in tri_tr if v >= 0.40)
tri_norm = len(tri_tr) - tri_warn - tri_crit

city_total = Counter(e["city"] for e in tri_entries)
city_valid = Counter(e["city"] for e in tri_entries if e["travel_ratio"] is not None)

gg_geo_pct  = 95.6
tri_geo_pct = tri_raw["summary"]["geo_coverage_pct"]
tri_valid_day_pct = round(len(tri_tr) / tri_raw["summary"]["total_days"] * 100, 1)


# ══════════════════════════════════════════════════════════════════════════════
# Figure 1: 트리플 단독 품질 리포트
# ══════════════════════════════════════════════════════════════════════════════
fig1, axes1 = plt.subplots(2, 2, figsize=(14, 10))
fig1.patch.set_facecolor(C_BG)
fig1.suptitle(
    f"트리플 앱 추천 경로 품질 분석 — 대한민국 38개 일정 ({tri_raw['summary']['total_days']} day)",
    fontsize=15, fontweight="bold", y=0.98
)

# Chart 1-1: Travel Ratio 분포
ax = axes1[0, 0]
ax.set_facecolor(C_BG)
bins = np.arange(0, 0.70, 0.04)
colors = [C_OK if b < 0.20 else (C_WARN if b < 0.40 else C_CRIT) for b in bins[:-1]]
n, _, patches = ax.hist(tri_tr, bins=bins, edgecolor="white", linewidth=0.8)
for patch, color in zip(patches, colors):
    patch.set_facecolor(color)
ax.axvline(0.20, color=C_WARN, linestyle="--", linewidth=1.5, label="경고 기준 (20%)")
ax.axvline(0.40, color=C_CRIT, linestyle="--", linewidth=1.5, label="위험 기준 (40%)")
ax.set_xlabel("이동 비율 (travel_ratio)", fontsize=11)
ax.set_ylabel("일정 수 (day)", fontsize=11)
ax.set_title(
    f"① 이동 비율 분포 (유효 {len(tri_tr)}/{tri_raw['summary']['total_days']}일)\n"
    "상업 앱 추천도 경고·위험 일정 존재 — 검증 레이어 필요",
    fontsize=10, fontweight="bold"
)
ax.legend(fontsize=9)
norm_pct = round(tri_norm / len(tri_tr) * 100, 1)
warn_pct = round(tri_warn / len(tri_tr) * 100, 1)
crit_pct = round(tri_crit / len(tri_tr) * 100, 1)
max_n = max(n) if max(n) > 0 else 1
ax.text(0.42, max_n * 0.75,
    f"정상  {tri_norm}건 ({norm_pct}%)\n경고  {tri_warn}건 ({warn_pct}%)\n위험  {tri_crit}건 ({crit_pct}%)",
    fontsize=9, bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

# Chart 1-2: 도시별 travel_ratio 가용률
ax = axes1[0, 1]
ax.set_facecolor(C_BG)
cities = list(city_total.keys())
totals = [city_total[c] for c in cities]
valids = [city_valid.get(c, 0) for c in cities]
ratios = [v/t*100 for v, t in zip(valids, totals)]
bar_colors = [C_OK if r >= 80 else (C_WARN if r >= 50 else C_CRIT) for r in ratios]
ax.bar(range(len(cities)), ratios, color=bar_colors, edgecolor="white", alpha=0.85)
ax.axhline(80, color=C_OK, linestyle="--", linewidth=1.2, alpha=0.7, label="80% 기준선")
ax.set_xticks(range(len(cities)))
ax.set_xticklabels([c.replace("_", "\n") for c in cities], fontsize=8)
ax.set_ylabel("travel_ratio 산출 가능 비율 (%)", fontsize=10)
ax.set_ylim(0, 110)
ax.set_title("② 도시별 데이터 가용성\nKakao Local API 추가로 평균 96.6% 달성", fontsize=10, fontweight="bold")
ax.legend(fontsize=9)
for i, r in enumerate(ratios):
    ax.text(i, r + 2, f"{r:.0f}%", ha="center", fontsize=7.5, fontweight="bold")

# Chart 1-3: 동행자 유형 파이차트
ax = axes1[1, 0]
ax.set_facecolor(C_BG)
comp_raw = [e.get("companion", "기타") for e in tri_raw["entries"]]
comp_counts = Counter(comp_raw)
labels_c, sizes_c = [], []
for k, v in sorted(comp_counts.items(), key=lambda x: -x[1])[:7]:
    labels_c.append(k if len(k) <= 10 else k[:10])
    sizes_c.append(v)
wedges, texts, autotexts = ax.pie(
    sizes_c, labels=labels_c, autopct="%1.0f%%",
    startangle=90, pctdistance=0.75, textprops=dict(fontsize=8)
)
for at in autotexts:
    at.set_fontweight("bold")
ax.set_title("③ 동행자 유형 분포\n다양한 동행 패턴 포함", fontsize=10, fontweight="bold")

# Chart 1-4: 기간별 travel_ratio 박스플롯
ax = axes1[1, 1]
ax.set_facecolor(C_BG)
dur_map = {}
for e in tri_entries:
    d = e.get("duration", "기타")
    if e["travel_ratio"] is not None:
        dur_map.setdefault(d, []).append(e["travel_ratio"])

dur_labels = ["당일치기", "1박 2일", "2박 3일", "3박 이상"]
box_data = [dur_map.get(d, [0]) for d in dur_labels]
bp = ax.boxplot([d for d in box_data if d],
                tick_labels=[l for l, d in zip(dur_labels, box_data) if d],
                patch_artist=True,
                medianprops=dict(color="black", linewidth=2),
                flierprops=dict(marker="o", markersize=4, alpha=0.5))
box_colors_list = [C_WARN, C_OK, C_OK, C_CRIT]
for i, (patch, color) in enumerate(zip(bp["boxes"], box_colors_list)):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)
ax.axhline(0.20, color=C_WARN, linestyle="--", linewidth=1.5, alpha=0.8, label="경고 (20%)")
ax.axhline(0.40, color=C_CRIT, linestyle="--", linewidth=1.5, alpha=0.8, label="위험 (40%)")
ax.set_ylabel("이동 비율", fontsize=11)
ax.set_title("④ 여행 기간별 이동 비율\n장기 여행일수록 분산 증가", fontsize=10, fontweight="bold")
ax.legend(fontsize=9)

plt.tight_layout(rect=[0, 0, 1, 0.96])
out1 = BASE / "triple_quality_report.png"
plt.savefig(out1, dpi=150, bbox_inches="tight", facecolor=C_BG)
plt.close()
print(f"저장: {out1}")


# ══════════════════════════════════════════════════════════════════════════════
# Figure 2: 구석구석 vs 트리플 비교
# ══════════════════════════════════════════════════════════════════════════════
fig2, axes2 = plt.subplots(2, 2, figsize=(14, 10))
fig2.patch.set_facecolor(C_BG)
fig2.suptitle(
    "구석구석 vs 트리플 앱 — 한국 추천 경로 품질 비교",
    fontsize=15, fontweight="bold", y=0.98
)

# Chart 2-1: Travel Ratio 히스토그램 비교
ax = axes2[0, 0]
ax.set_facecolor(C_BG)
bins = np.arange(0, 0.90, 0.05)
ax.hist(gg_tr,  bins=bins, alpha=0.7, color=C_GG,  edgecolor="white", label=f"구석구석 (n={len(gg_tr)})")
ax.hist(tri_tr, bins=bins, alpha=0.7, color=C_TRI, edgecolor="white", label=f"트리플 (n={len(tri_tr)})")
ax.axvline(0.20, color=C_WARN, linestyle="--", linewidth=1.5, label="경고 (20%)")
ax.axvline(0.40, color=C_CRIT, linestyle="--", linewidth=1.5, label="위험 (40%)")
ax.axvline(np.mean(gg_tr),  color=C_GG,  linestyle=":",  linewidth=2, label=f"구석구석 평균 {np.mean(gg_tr):.3f}")
ax.axvline(np.mean(tri_tr), color=C_TRI, linestyle=":",  linewidth=2, label=f"트리플 평균 {np.mean(tri_tr):.3f}")
ax.set_xlabel("이동 비율", fontsize=11)
ax.set_ylabel("일정 수 (day)", fontsize=11)
ax.set_title("① 이동 비율 분포 비교\n두 서비스 모두 경고·위험 일정 존재", fontsize=10, fontweight="bold")
ax.legend(fontsize=7.5, loc="upper right")

# Chart 2-2: 품질 지표 막대 비교
ax = axes2[0, 1]
ax.set_facecolor(C_BG)
metrics = ["경고(≥20%)\n비율", "위험(≥40%)\n비율", "백트래킹\n발생률", "12h 초과\n일정 비율"]
gg_vals = [
    gg_warn / len(gg_tr) * 100,
    gg_crit / len(gg_tr) * 100,
    44.6,
    9 / 101 * 100,
]
tri_vals = [
    tri_warn / len(tri_tr) * 100,
    tri_crit / len(tri_tr) * 100,
    tri_raw["backtrack_pct"],
    tri_raw["over_12h_days"] / tri_raw["summary"]["total_days"] * 100,
]
x = np.arange(len(metrics))
w = 0.35
ax.bar(x - w/2, gg_vals,  w, label="구석구석", color=C_GG,  alpha=0.8)
ax.bar(x + w/2, tri_vals, w, label="트리플",    color=C_TRI, alpha=0.8)
for xi, (v1, v2) in enumerate(zip(gg_vals, tri_vals)):
    ax.text(xi - w/2, v1 + 0.5, f"{v1:.1f}%", ha="center", fontsize=8.5, color=C_GG, fontweight="bold")
    ax.text(xi + w/2, v2 + 0.5, f"{v2:.1f}%", ha="center", fontsize=8.5, color=C_TRI, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(metrics, fontsize=9)
ax.set_ylabel("비율 (%)", fontsize=11)
ax.set_title("② 품질 지표 비교\n구석구석이 모든 지표에서 더 많은 문제 보임", fontsize=10, fontweight="bold")
ax.legend(fontsize=9)

# Chart 2-3: 지리 분산 박스플롯
ax = axes2[1, 0]
ax.set_facecolor(C_BG)
dist_clip = 200
gg_dist_c  = [min(d, dist_clip) for d in gg_dist]
tri_dist_c = [min(d, dist_clip) for d in tri_dist]
bp = ax.boxplot([gg_dist_c, tri_dist_c],
                tick_labels=["구석구석", "트리플"],
                patch_artist=True,
                medianprops=dict(color="black", linewidth=2),
                flierprops=dict(marker="o", markersize=4, alpha=0.5))
bp["boxes"][0].set_facecolor(C_GG);  bp["boxes"][0].set_alpha(0.7)
bp["boxes"][1].set_facecolor(C_TRI); bp["boxes"][1].set_alpha(0.7)
ax.axhline(50, color="gray", linestyle=":", linewidth=1.5, label="광역 이탈 기준 (50km)")
ax.set_ylabel("하루 최대 직선거리 (km)", fontsize=11)
ax.set_title(
    f"③ 지리 분산 비교 (clip {dist_clip}km)\n"
    f"구석구석 평균 {np.mean(gg_dist):.0f}km vs 트리플 {np.mean(tri_dist):.1f}km",
    fontsize=10, fontweight="bold"
)
ax.legend(fontsize=9)

# Chart 2-4: 종합 비교 테이블
ax = axes2[1, 1]
ax.set_facecolor(C_BG)
ax.axis("off")
table_data = [
    ["지표", "구석구석", "트리플"],
    ["분석 데이터", "50개 경로 / 101일", f"38개 경로 / {tri_raw['summary']['total_days']}일"],
    ["geo 커버리지", f"{gg_geo_pct}%", f"{tri_geo_pct}%"],
    ["tr 산출 가능", f"101일 (100%)", f"{len(tri_tr)}일 ({tri_valid_day_pct}%)"],
    ["이동 비율 평균", f"{np.mean(gg_tr):.3f}", f"{np.mean(tri_tr):.3f}"],
    ["이동 비율 최대", f"{max(gg_tr):.3f}", f"{max(tri_tr):.3f}"],
    ["경고(≥20%)", f"{gg_warn}건 ({gg_warn/len(gg_tr)*100:.1f}%)", f"{tri_warn}건 ({tri_warn/len(tri_tr)*100:.1f}%)"],
    ["위험(≥40%)", f"{gg_crit}건 ({gg_crit/len(gg_tr)*100:.1f}%)", f"{tri_crit}건 ({tri_crit/len(tri_tr)*100:.1f}%)"],
    ["평균 지리 분산", f"{np.mean(gg_dist):.1f}km", f"{np.mean(tri_dist):.1f}km"],
    ["백트래킹", "44.6%", f"{tri_raw['backtrack_pct']}%"],
    ["12h 초과 일정", f"{9}건 (8.9%)", f"{tri_raw['over_12h_days']}건 ({tri_raw['over_12h_days']/tri_raw['summary']['total_days']*100:.1f}%)"],
]
colors_table = [["#1565C0", "#1565C0", "#7B1FA2"]] + [["#FAFAFA", "#BBDEFB", "#E1BEE7"]] * (len(table_data) - 1)
tbl = ax.table(cellText=table_data, loc="center", cellLoc="center", cellColours=colors_table)
tbl.auto_set_font_size(False)
tbl.set_fontsize(8.5)
tbl.scale(1, 1.5)
for (row, col), cell in tbl.get_celld().items():
    if row == 0:
        cell.set_text_props(color="white", fontweight="bold")
    elif col == 0:
        cell.set_text_props(fontweight="bold")
ax.set_title("④ 종합 비교 요약", fontsize=11, fontweight="bold", pad=120)

plt.tight_layout(rect=[0, 0, 1, 0.96])
out2 = BASE / "comparison_report.png"
plt.savefig(out2, dpi=150, bbox_inches="tight", facecolor=C_BG)
plt.close()
print(f"저장: {out2}")
print("시각화 완료")
