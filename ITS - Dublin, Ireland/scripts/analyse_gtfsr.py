"""Turn collected GTFS-R data (collect_gtfsr.py v2) into report evidence.

Run:  conda run -n it python "Research/scripts/analyse_gtfsr.py"            (from the "Ass 1" folder)
      ... --data-dir <folder> --out-dir <folder>   to use other folders

Method
  - The feed lists, for each active trip, the stops the bus has passed where its delay changed
    (a trail of breakpoints). The last value reported for a (trip, date, stop) is taken as the
    observed delay there, and carried forward to the stops between breakpoints, as GTFS-Realtime
    intends. Stops before the first or after the last breakpoint are not counted.
  - Only tracked buses count (trip updates with a vehicle ID).
  - Punctuality uses the NTA rule: on time = no more than 1 min early and no more than
    5 min 59 s late (NTA PSO Performance Report 2024, p. 10).
  - Excess Wait Time (EWT) on high-frequency route-directions (>= 5 buses/h, 10:00-15:00):
    AWT = sum(h^2) / (2 * sum(h)); EWT = AWT_actual - AWT_scheduled, per route/stop/day,
    07:00-19:00, over the buses observed (missing buses are not included).
  - Coverage uses complete service days only: scheduled trips that appeared in the feed, that
    were tracked by a vehicle, and that were marked CANCELED.

Outputs (Research/figures/): fig4_live_delay_by_hour.png, fig4_data.csv, gtfsr_route_summary.csv,
gtfsr_summary.json
"""
import argparse, json, re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]   # the "ITS - Dublin, Ireland" folder
GTFS = ROOT / "GTFS_Dublin_Bus"
OUT = ROOT / "figures"
TZ = "Europe/Dublin"
LOCAL_TZ = "Pacific/Auckland"   # the collector log is written in the machine's local time
BLUE, INK, INK_2, MUTED, GRID, AXIS = "#2a78d6", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
plt.rcParams.update({"font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 9,
                     "axes.edgecolor": AXIS, "xtick.color": MUTED, "ytick.color": MUTED,
                     "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2})


def secs(col):
    hms = col.str.split(":", expand=True).astype(int)
    return hms[0] * 3600 + hms[1] * 60 + hms[2]


def awt(times: np.ndarray) -> tuple[float, float]:
    h = np.diff(np.sort(times))
    return (float((h ** 2).sum()), float(h.sum())) if len(h) else (0.0, 0.0)


def active_services(date: str, cal: pd.DataFrame, cal_dates: pd.DataFrame) -> set:
    dow = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][pd.Timestamp(date).dayofweek]
    on = set(cal[(cal["start_date"] <= date) & (cal["end_date"] >= date) & (cal[dow] == "1")]["service_id"])
    ex = cal_dates[cal_dates["date"] == date]
    return (on | set(ex[ex["exception_type"] == "1"]["service_id"])) - set(ex[ex["exception_type"] == "2"]["service_id"])


def load(pattern: str, data_dir: Path) -> pd.DataFrame:
    files = sorted(data_dir.glob(pattern))
    if not files:
        raise SystemExit(f"no {pattern} in {data_dir}")
    return pd.concat((pd.read_csv(f, dtype={"trip_id": str, "start_date": str, "stop_id": str, "vehicle_id": str})
                      for f in files), ignore_index=True)


POLL_OK = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO poll ok: "
                     r"(\d+) Dublin Bus trips, (\d+) new/changed stop delays")


def poll_log(data_dir: Path) -> pd.DataFrame:
    """Polls actually attempted, from collector.log (written in the machine's local time)."""
    log = data_dir / "collector.log"
    if not log.exists():
        return pd.DataFrame(columns=["poll", "trips", "changes"])
    rows = [(m.group(1), int(m.group(2)), int(m.group(3)))
            for m in map(POLL_OK.match, log.read_text(errors="replace").splitlines()) if m]
    d = pd.DataFrame(rows, columns=["ts", "trips", "changes"])
    d["poll"] = (pd.to_datetime(d["ts"]).dt.tz_localize(LOCAL_TZ, ambiguous=True, nonexistent="shift_forward")
                 .dt.tz_convert(TZ))
    return d.drop(columns="ts")


def poll_times(data_dir: Path, stu: pd.DataFrame, trips_rt: pd.DataFrame) -> pd.DatetimeIndex:
    """Union of polls recorded in the log and polls evidenced by written rows."""
    from_rows = pd.to_datetime(pd.concat([stu["poll_ts"], trips_rt["poll_ts"]]).unique(),
                               unit="s", utc=True).tz_convert(TZ)
    logged = poll_log(data_dir)["poll"]
    if logged.empty:
        return from_rows
    return pd.DatetimeIndex(from_rows).union(pd.DatetimeIndex(logged)).round("min").unique()


def feed_degradation(data_dir: Path, quiet_share: float = 0.2) -> list[dict]:
    """Dublin clock hours where the feed stopped publishing delay updates while polling continued.

    A "quiet" poll is a successful poll that returned no new or changed stop delay. The feed keeps
    serving a fresh header timestamp throughout, so a degradation is invisible unless successive
    payloads are compared. Reported as a publisher-side data-quality event, not missing collection.
    """
    d = poll_log(data_dir)
    if d.empty:
        return []
    d = d.set_index("poll").sort_index()
    g = d.resample("h").agg(polls=("changes", "size"), quiet=("changes", lambda s: int((s == 0).sum())),
                            updates=("changes", "sum"), trips_med=("trips", "median"))
    g = g[g["polls"] > 0]
    out = []
    for ts, r in g[g["quiet"] / g["polls"] >= quiet_share].iterrows():
        out.append({"hour": ts.strftime("%Y-%m-%d %H:00 %Z"), "polls": int(r["polls"]),
                    "quiet_polls": int(r["quiet"]), "delay_updates": int(r["updates"]),
                    "trips_in_feed_median": int(r["trips_med"])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--out-dir", default=str(OUT), help="where figures/CSVs/JSON are written")
    args = ap.parse_args()
    data, out = Path(args.data_dir), Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stu, trips_rt = load("stu_*.csv.gz", data), load("trips_*.csv.gz", data)

    # ---- which service days were polled right through (>= 40 polls in every hour 05:00-23:59)
    # Count polls ATTEMPTED, from the collector log, not polls that happened to write rows: the
    # collector only writes new/changed values, so a stretch where the feed republishes identical
    # data leaves no trace in the CSVs even though polling never stopped (see feed_degraded_hours).
    polls = poll_times(data, stu, trips_rt)
    per_hour_polls = pd.Series(1, index=polls).groupby([polls.strftime("%Y%m%d"), polls.hour]).size()
    complete = [d for d in per_hour_polls.index.get_level_values(0).unique()
                if all(per_hour_polls.get((d, h), 0) >= 40 for h in range(5, 24))]
    degraded = feed_degradation(data)

    # ---- static schedule
    trips = pd.read_csv(GTFS / "trips.txt", dtype=str).merge(
        pd.read_csv(GTFS / "routes.txt", dtype=str)[["route_id", "route_short_name"]], on="route_id")
    cal = pd.read_csv(GTFS / "calendar.txt", dtype=str)
    cal_dates = pd.read_csv(GTFS / "calendar_dates.txt", dtype=str)
    st = pd.read_csv(GTFS / "stop_times.txt", usecols=["trip_id", "stop_sequence", "stop_id", "departure_time"],
                     dtype={"trip_id": str, "stop_id": str})
    st["sched_s"] = secs(st["departure_time"])

    # ---- observed delay at each breakpoint: last value reported, tracked buses only
    stu["delay"] = stu["dep_delay"].fillna(stu["arr_delay"])
    bp = (stu[stu["vehicle_id"].notna()].dropna(subset=["stop_sequence", "delay"])
             .sort_values("poll_ts").groupby(["trip_id", "start_date", "stop_sequence"], as_index=False).last())
    bp["stop_sequence"] = bp["stop_sequence"].astype(int)

    # ---- carry each delay forward to the following stops, up to the last breakpoint
    span = bp.groupby(["trip_id", "start_date"])["stop_sequence"].agg(first="min", last="max").reset_index()
    obs = span.merge(st[["trip_id", "stop_sequence", "stop_id", "sched_s"]], on="trip_id")
    obs = obs[obs["stop_sequence"].between(obs["first"], obs["last"])]
    obs = obs.merge(bp[["trip_id", "start_date", "stop_sequence", "delay"]],
                    on=["trip_id", "start_date", "stop_sequence"], how="left")
    obs = obs.sort_values(["trip_id", "start_date", "stop_sequence"])
    obs["delay"] = obs.groupby(["trip_id", "start_date"])["delay"].ffill()
    obs = obs.merge(trips[["trip_id", "route_short_name", "direction_id"]], on="trip_id")
    obs = obs[obs["delay"].between(-3600, 3 * 3600)]                 # drop obviously broken values
    obs["hour"] = obs["sched_s"] // 3600                             # service-day hour; 24-28 = after midnight
    obs["on_time"] = obs["delay"].between(-60, 359)
    obs["delay_min"] = obs["delay"] / 60

    # ---- report on fully polled service days only, and drop hours the feed under-published:
    # a partial day is a night-service-only sample, and a degraded hour is a thin, late-filled one.
    if complete:
        obs = obs[obs["start_date"].isin(complete)]
    sched_clock = (pd.to_datetime(obs["start_date"], format="%Y%m%d").dt.tz_localize(TZ, nonexistent="shift_forward",
                                                                                    ambiguous=True)
                   + pd.to_timedelta(obs["sched_s"], unit="s"))
    for h in degraded:
        bad = pd.Timestamp(h["hour"].rsplit(" ", 1)[0], tz=TZ)
        obs = obs[~sched_clock.between(bad, bad + pd.Timedelta(hours=1), inclusive="left").reindex(obs.index, fill_value=False)]
    if obs.empty:
        raise SystemExit("no observations left after restricting to complete, undegraded hours")

    # ---- route frequency class from the static weekday timetable (10:00-15:00 at origin)
    first = st[st["stop_sequence"] == st.groupby("trip_id")["stop_sequence"].transform("min")]
    wk = first.merge(trips[trips["service_id"] == "190"][["trip_id", "route_short_name", "direction_id"]], on="trip_id")
    per_hour = wk[wk["sched_s"].between(10 * 3600, 15 * 3600 - 1)].groupby(["route_short_name", "direction_id"]).size() / 5
    high_freq = set(per_hour[per_hour >= 5].index)
    obs["high_freq"] = [(r, d) in high_freq for r, d in zip(obs["route_short_name"], obs["direction_id"])]

    # ---- EWT on high-frequency route-directions, per stop and day, 07:00-19:00
    hf = obs[obs["high_freq"] & obs["sched_s"].between(7 * 3600, 19 * 3600)]
    num_a = den_a = num_s = den_s = 0.0
    for _, grp in hf.groupby(["route_short_name", "direction_id", "stop_id", "start_date"]):
        if len(grp) < 6:
            continue
        a2, a1 = awt((grp["sched_s"] + grp["delay"]).to_numpy())
        s2, s1 = awt(grp["sched_s"].to_numpy())
        num_a, den_a, num_s, den_s = num_a + a2, den_a + a1, num_s + s2, den_s + s1
    ewt_min = ((num_a / (2 * den_a)) - (num_s / (2 * den_s))) / 60 if den_a and den_s else None

    # ---- trip coverage on those complete service days
    cov = []
    for d in complete:
        sched = set(trips[trips["service_id"].isin(active_services(d, cal, cal_dates))]["trip_id"])
        seen = trips_rt[trips_rt["start_date"] == d]
        cov.append({"date": d, "scheduled": len(sched), "appeared": len(set(seen["trip_id"]) & sched),
                    "tracked": len(set(seen.loc[seen["vehicle_id"].notna(), "trip_id"]) & sched),
                    "cancelled": len(set(seen.loc[seen["trip_rel"].astype(str).str.upper().str.contains("CANCEL"),
                                                  "trip_id"]) & sched)})
    cov = pd.DataFrame(cov, columns=["date", "scheduled", "appeared", "tracked", "cancelled"])
    pct = lambda col: round(float(cov[col].sum() / cov["scheduled"].sum() * 100), 1) if len(cov) else None

    # ---- outputs
    by_hour = obs.groupby("hour")["delay_min"].describe(percentiles=[0.1, 0.5, 0.9])
    by_hour["on_time_pct"] = obs.groupby("hour")["on_time"].mean() * 100
    by_hour = by_hour[(by_hour["count"] >= 200) & (by_hour.index >= 4) & (by_hour.index <= 28)]
    if len(by_hour):   # reindex so an excluded hour leaves a visible break, not a bridged line
        by_hour = by_hour.reindex(range(int(by_hour.index.min()), int(by_hour.index.max()) + 1))
    by_hour.round(2).to_csv(out / "fig4_data.csv")

    routes_out = (obs.groupby("route_short_name")
                     .agg(stop_observations=("delay", "size"), trips=("trip_id", "nunique"),
                          median_delay_min=("delay_min", "median"), p90_delay_min=("delay_min", lambda s: s.quantile(0.9)),
                          on_time_pct=("on_time", "mean"))
                     .query("trips >= 20").sort_values("median_delay_min", ascending=False))
    routes_out["on_time_pct"] *= 100
    routes_out.round(2).to_csv(out / "gtfsr_route_summary.csv")

    dates = sorted(obs["start_date"].unique())
    low = obs[~obs["high_freq"]]
    summary = {
        "service_dates_observed": f"{dates[0]}-{dates[-1]}" if dates else None,
        "complete_service_days": complete,
        "tracked_trips_observed": int(obs.groupby(["trip_id", "start_date"]).ngroups),
        "stop_observations": int(len(obs)),
        "on_time_pct_all_routes": round(float(obs["on_time"].mean() * 100), 1),
        "on_time_pct_low_frequency_routes": round(float(low["on_time"].mean() * 100), 1) if len(low) else None,
        "median_delay_min": round(float(obs["delay_min"].median()), 2),
        "p90_delay_min": round(float(obs["delay_min"].quantile(0.9)), 2),
        "ewt_high_frequency_min": None if ewt_min is None else round(float(ewt_min), 2),
        "trips_appeared_pct": pct("appeared"), "trips_tracked_pct": pct("tracked"), "trips_cancelled_pct": pct("cancelled"),
        "worst_routes_by_median_delay": routes_out.head(5).round(1).reset_index().to_dict("records"),
        "feed_degraded_hours": degraded,
        "note": "Observed delays at stops the bus passed (feed breakpoints), carried forward between breakpoints.",
    }
    (out / "gtfsr_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if by_hour.empty:
        print("not enough observations per hour for Figure 4 yet")
        return

    fig, ax = plt.subplots(figsize=(6.5, 3.3), dpi=300)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.70, bottom=0.17)
    x = by_hour.index.to_numpy()
    ax.fill_between(x, by_hour["10%"], by_hour["90%"], color=BLUE, alpha=0.12, linewidth=0, label="10th–90th percentile")
    ax.plot(x, by_hour["50%"], color=BLUE, linewidth=1.5, label="Median")
    ax.axhline(0, color=AXIS, linewidth=0.75)
    ticks = [t for t in (6, 9, 12, 15, 18, 21, 24, 27) if x.min() - 1 <= t <= x.max() + 1]
    ax.set_xticks(ticks, [f"{t % 24:02d}:00" for t in ticks])
    ax.grid(axis="y", color=GRID, linewidth=0.75)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(loc="lower left", bbox_to_anchor=(-0.01, 1.0), ncol=2, frameon=False, fontsize=8, labelcolor=INK_2)
    d0, d1 = (pd.Timestamp(d).strftime("%-d %b %Y") for d in (dates[0], dates[-1]))
    when = d0 if d0 == d1 else f"{d0} to {d1}"
    fig.text(0.012, 0.975, f"Buses ran on time at {summary['on_time_pct_all_routes']:.0f}% of observed stops",
             ha="left", va="top", fontsize=11.5, fontweight="bold", color=INK)
    fig.text(0.012, 0.915, f"Dublin Bus lateness in minutes by scheduled hour, {when}.\n"
             "On time = no more than 1 min early or 5 min 59 s late (NTA rule).", ha="left", va="top", fontsize=8.8,
             color=INK_2, linespacing=1.35)
    fig.text(0.012, 0.02, "Source: NTA GTFS-Realtime TripUpdates (CC BY 4.0), polled every minute.",
             ha="left", va="bottom", fontsize=7, color=MUTED)
    fig.savefig(out / "fig4_live_delay_by_hour.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
