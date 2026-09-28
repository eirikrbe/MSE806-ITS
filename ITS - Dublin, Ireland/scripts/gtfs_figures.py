"""Report figures from the NTA Dublin Bus GTFS feed (static schedule).

Run:  conda run -n it python "Research/scripts/gtfs_figures.py"   (from the "Ass 1" folder)

Outputs (Research/figures/):
  fig1_speed_by_hour.png        scheduled average speed by departure hour
  fig2_buses_in_service.png     trips in progress through the day
  fig3_peak_vs_early.png        08:00 vs 06:00 running time, same route + stop pattern
  fig*_data.csv                 the numbers behind each chart (table view)
  gtfs_summary.json             headline figures quoted in the research pack

Notes on the feed (checked 21 Sep 2026):
  - service_id 190 = Mon-Thu, 128 = Fri (an exact copy of 190), 191 = Sat, 192 = Sun.
  - service_id 66 only holds the overnight trips of Sat 19 Sep 2026, the day before
    the feed starts, so it is ignored.
  - stop_times has no shape_dist_traveled, so trip length comes from shapes.txt (metres).
"""
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]          # the "ITS - Dublin, Ireland" folder
GTFS = ROOT / "GTFS_Dublin_Bus"
OUT = ROOT / "figures"
OUT.mkdir(parents=True, exist_ok=True)
WEEKDAY = "190"                                     # Mon-Thu timetable

# ---- palette & chrome (dataviz reference palette, light mode, white page) ----
BLUE = "#2a78d6"            # categorical slot 1 (single series)
BLUE_LIGHT = "#86b6ef"      # blue step 250  (ordinal light end, validated >= 2:1 on white)
BLUE_DARK = "#1c5cab"       # blue step 550
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#ffffff"
SOURCE = "Source: NTA GTFS schedule for Dublin Bus (feed valid from 20 Sep 2026), Monday–Thursday timetable."

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 9, "axes.edgecolor": AXIS, "axes.linewidth": 0.75,
    "axes.labelcolor": INK_2, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


def secs(col: pd.Series) -> pd.Series:
    hms = col.str.split(":", expand=True).astype(int)
    return hms[0] * 3600 + hms[1] * 60 + hms[2]


def hhmm(s: float) -> str:
    s = int(s) % 86400
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"


def frame(ax, title, subtitle, fig, source=SOURCE):
    """Headline title, subtitle and source line; recessive solid hairline grid."""
    fig.text(0.012, 0.975, title, ha="left", va="top", fontsize=11.5, fontweight="bold", color=INK)
    fig.text(0.012, 0.905, subtitle, ha="left", va="top", fontsize=8.8, color=INK_2)
    fig.text(0.012, 0.02, source, ha="left", va="bottom", fontsize=7, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.75, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", length=3, color=AXIS)


# ---------------------------------------------------------------- load feed
trips = pd.read_csv(GTFS / "trips.txt", dtype=str)
routes = pd.read_csv(GTFS / "routes.txt", dtype=str)[["route_id", "route_short_name"]]
shapes = pd.read_csv(GTFS / "shapes.txt", usecols=["shape_id", "shape_dist_traveled"], dtype={"shape_id": str})
st = pd.read_csv(GTFS / "stop_times.txt", usecols=["trip_id", "arrival_time", "departure_time", "stop_sequence"],
                 dtype={"trip_id": str, "arrival_time": str, "departure_time": str})

st = st.sort_values(["trip_id", "stop_sequence"])
first = st.groupby("trip_id").first()
last = st.groupby("trip_id").last()
span = pd.DataFrame({"start": secs(first["departure_time"]), "end": secs(last["arrival_time"]),
                     "n_stops": st.groupby("trip_id").size()})
shape_km = shapes.groupby("shape_id")["shape_dist_traveled"].max() / 1000

T = (trips.merge(routes, on="route_id").join(span, on="trip_id")
          .assign(km=lambda d: d["shape_id"].map(shape_km)))
T["minutes"] = (T["end"] - T["start"]) / 60
wk = T[T["service_id"] == WEEKDAY].copy()
wk["hour"] = wk["start"] // 3600

# ---------------------------------------------------------------- headline numbers
delta = np.zeros(60 * 50, dtype=int)
np.add.at(delta, (wk["start"] // 60).to_numpy(), 1)
np.add.at(delta, np.maximum(wk["end"] // 60, wk["start"] // 60 + 1).to_numpy(), -1)
running = np.cumsum(delta)
am = int(np.argmax(running[7 * 60:10 * 60])) + 7 * 60
pm = int(np.argmax(running[15 * 60:19 * 60])) + 15 * 60
night_routes = sorted(wk.loc[wk["start"].between(25 * 3600, 29 * 3600 - 1), "route_short_name"].unique())

summary = {
    "feed_valid_from": "2026-09-20",
    "weekday_trips": int(len(wk)),
    "weekday_routes": int(wk["route_short_name"].nunique()),
    "stops_in_feed": int(pd.read_csv(GTFS / "stops.txt", usecols=["stop_id"]).shape[0]),
    "weekday_in_service_km": round(float(wk["km"].sum())),
    "weekday_bus_hours": round(float(wk["minutes"].sum() / 60)),
    "peak_trips_in_progress_am": {"time": hhmm(am * 60), "buses": int(running[am])},
    "peak_trips_in_progress_pm": {"time": hhmm(pm * 60), "buses": int(running[pm])},
    "routes_with_01_05_departures": night_routes,
    "median_stop_spacing_m": round(float(np.median(wk["km"] * 1000 / (wk["n_stops"] - 1)))),
    "median_trip_km": round(float(wk["km"].median()), 1),
    "median_trip_minutes": round(float(wk["minutes"].median())),
}

# ---------------------------------------------------------------- Fig 1: speed by hour
by_h = (wk.groupby("hour").agg(departures=("trip_id", "size"), km=("km", "sum"), minutes=("minutes", "sum")))
by_h["speed_kmh"] = by_h["km"] / (by_h["minutes"] / 60)
by_h = by_h[by_h["departures"] >= 30]                     # drop thin hours (04:00, 05:00 next day)
by_h.round(2).to_csv(OUT / "fig1_data.csv")
summary["speed_kmh_by_hour"] = {hhmm(h * 3600): round(float(v), 1) for h, v in by_h["speed_kmh"].items()}

fig, ax = plt.subplots(figsize=(6.5, 3.3), dpi=300)
fig.subplots_adjust(left=0.07, right=0.97, top=0.78, bottom=0.17)
x, y = by_h.index.to_numpy(), by_h["speed_kmh"].to_numpy()
ax.plot(x, y, color=BLUE, linewidth=1.5, solid_joinstyle="round", solid_capstyle="round")
slow = int(by_h["speed_kmh"].idxmin())
labels = {5: "above", 8: "below", slow: "below", 22: "below"}
for h, pos in labels.items():
    v = float(by_h.loc[h, "speed_kmh"])
    ax.plot(h, v, "o", markersize=6.5, color=BLUE, markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=3)
    ax.annotate(f"{hhmm(h * 3600)}  {v:.1f} km/h", (h, v), xytext=(0, 9 if pos == "above" else -14),
                textcoords="offset points", ha="center", fontsize=8, color=INK)
ticks = [6, 9, 12, 15, 18, 21, 24, 27]
ax.set_xticks(ticks, [hhmm(t * 3600) for t in ticks])
ax.set_xlim(x.min() - 0.6, x.max() + 0.6)
ax.set_ylim(0, 30)
ax.set_yticks([0, 10, 20, 30], ["0", "10", "20", "30"])
frame(ax, "Timetabled bus speeds fall by about a third in the peaks",
      "Average scheduled speed (km/h) of Dublin Bus trips by hour of departure: in-service distance ÷ scheduled time", fig)
fig.savefig(OUT / "fig1_speed_by_hour.png")
plt.close(fig)

# ---------------------------------------------------------------- Fig 2: buses in service
minutes = np.arange(4 * 60, 30 * 60 + 1)
pd.DataFrame({"time": [hhmm(m * 60) for m in minutes], "trips_in_progress": running[minutes]}) \
  .iloc[::5].to_csv(OUT / "fig2_data.csv", index=False)

fig, ax = plt.subplots(figsize=(6.5, 3.3), dpi=300)
fig.subplots_adjust(left=0.07, right=0.97, top=0.78, bottom=0.17)
ax.fill_between(minutes / 60, running[minutes], color=BLUE, alpha=0.10, linewidth=0)
ax.plot(minutes / 60, running[minutes], color=BLUE, linewidth=1.5)
for m, txt in ((am, "morning peak"), (pm, "evening peak")):
    ax.plot(m / 60, running[m], "o", markersize=6.5, color=BLUE, markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=3)
    ax.annotate(f"{hhmm(m * 60)}  {running[m]} buses ({txt})", (m / 60, running[m]), xytext=(0, 8),
                textcoords="offset points", ha="center", fontsize=8, color=INK)
night = int(np.median(running[26 * 60:28 * 60]))
ax.text(29.8, night + 135, f"~{night} buses overnight\n{len(night_routes)} routes run 24 hours", ha="right", va="bottom",
        fontsize=8, color=INK, linespacing=1.3)
ticks = [6, 9, 12, 15, 18, 21, 24, 27, 30]
ax.set_xticks(ticks, [hhmm(t * 3600) for t in ticks])
ax.set_xlim(4, 30)
ax.set_ylim(0, 1000)
ax.set_yticks([0, 250, 500, 750, 1000], ["0", "250", "500", "750", "1,000"])
frame(ax, f"About {round(running[pm], -1):.0f} buses are running at the evening peak",
      "Dublin Bus trips in progress by time of day (excludes layover and depot running)", fig)
fig.savefig(OUT / "fig2_buses_in_service.png")
plt.close(fig)

# ---------------------------------------------------------------- Fig 3: peak vs early running time
wk["bucket"] = wk["hour"].map({6: "early", 8: "am"})
g = (wk.dropna(subset=["bucket"])
       .groupby(["route_short_name", "direction_id", "shape_id", "bucket"])["minutes"]
       .agg(["median", "size"]).unstack("bucket"))
g = g[(g[("size", "early")] >= 2) & (g[("size", "am")] >= 2)]
cmp = pd.DataFrame({"early_min": g[("median", "early")], "am_min": g[("median", "am")]})
cmp["increase_pct"] = (cmp["am_min"] / cmp["early_min"] - 1) * 100
cmp = cmp.reset_index()
cmp["km"] = cmp["shape_id"].map(shape_km).round(1)
heads = wk.groupby("shape_id")["trip_headsign"].agg(lambda s: s.mode().iat[0])
cmp["to"] = cmp["shape_id"].map(heads)
cmp.sort_values("increase_pct", ascending=False).round(1).to_csv(OUT / "fig3_data.csv", index=False)
summary["peak_vs_early"] = {
    "patterns_compared": int(len(cmp)),
    "median_increase_pct": round(float(cmp["increase_pct"].median()), 1),
    "share_25pct_or_more": round(float((cmp["increase_pct"] >= 25).mean() * 100)),
    "rule": "median scheduled running time of 08:00-08:59 vs 06:00-06:59 departures, same route + shape, >= 2 trips each",
}

top = cmp.sort_values("increase_pct", ascending=False).head(10).iloc[::-1]
fig, ax = plt.subplots(figsize=(6.5, 4.2), dpi=300)
fig.subplots_adjust(left=0.36, right=0.9, top=0.76, bottom=0.17)
yy = np.arange(len(top))
ax.hlines(yy, top["early_min"], top["am_min"], color=AXIS, linewidth=1.5, zorder=1)
ax.plot(top["early_min"], yy, "o", markersize=7, color=BLUE_LIGHT, markeredgecolor=SURFACE, markeredgewidth=1.5,
        zorder=2, label="Departing 06:00–06:59")
ax.plot(top["am_min"], yy, "o", markersize=7, color=BLUE_DARK, markeredgecolor=SURFACE, markeredgewidth=1.5,
        zorder=3, label="Departing 08:00–08:59")
for yi, (_, r) in zip(yy, top.iterrows()):
    ax.annotate(f"+{r['increase_pct']:.0f}%", (r["am_min"], yi), xytext=(7, 0), textcoords="offset points",
                va="center", fontsize=8, color=INK)
ax.set_yticks(yy, [f"{r.route_short_name} to {r.to} ({r.km:.0f} km)" for r in top.itertuples()], fontsize=8)
ax.set_xlim(0, max(100, float(top["am_min"].max()) * 1.12))
ax.set_xlabel("Scheduled running time (minutes)", fontsize=8, color=INK_2)
ax.grid(axis="x", color=GRID, linewidth=0.75)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.tick_params(axis="y", length=0)
ax.legend(loc="lower left", bbox_to_anchor=(-0.02, 1.0), ncol=2, frameon=False, fontsize=8, handletextpad=0.3,
          columnspacing=1.6, labelcolor=INK_2)
fig.text(0.012, 0.975, f"Morning-peak trips are timetabled up to {top['increase_pct'].max():.0f}% longer than at 06:00",
         ha="left", va="top", fontsize=11.5, fontweight="bold", color=INK)
fig.text(0.012, 0.92, f"Median scheduled running time for the same route and stop pattern: the 10 largest increases\n"
         f"among {len(cmp)} comparable patterns (median increase across all {len(cmp)}: +{cmp['increase_pct'].median():.0f}%)",
         ha="left", va="top", fontsize=8.8, color=INK_2)
fig.text(0.012, 0.012, SOURCE, ha="left", va="bottom", fontsize=7, color=MUTED)
fig.savefig(OUT / "fig3_peak_vs_early.png")
plt.close(fig)

(OUT / "gtfs_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
