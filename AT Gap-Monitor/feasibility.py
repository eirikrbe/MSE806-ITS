#!/usr/bin/env python3
"""Feasibility test for the AT Gap Monitor: is there enough bunching to be worth monitoring?

    python feasibility.py timetable   how many frequent bus routes the timetable has
    python feasibility.py observed    bunching and gaps in the data collected so far

Needs data/gtfs/gtfs.zip (AT's timetable) and, for 'observed', the snapshots
saved by collector.py in data/raw/ and its log in data/polls.csv.
"""

import argparse
import datetime as dt
import gzip
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
TZ = "Pacific/Auckland"
CBD_LAT, CBD_LON = (-36.860, -36.840), (174.750, 174.780)  # city centre, roughly Victoria Park to the Domain
FREQUENT_S = 15 * 60   # AT's frequent network: a bus at least every 15 minutes
BUNCH, GAP = 0.5, 1.5  # alert thresholds, as multiples of the timetabled headway
MIN_STOPS = 3          # a pair of buses counts as one episode once flagged at this many stops
DAYS = (("Saturday", dt.date(2026, 10, 31)), ("Weekday", dt.date(2026, 11, 3)))
KEYS = ["route_short_name", "direction_id", "stop_id"]


def to_seconds(hms):
    """GTFS 'HH:MM:SS' (hours can pass 24) to seconds after midnight."""
    parts = hms.str.split(":", expand=True)
    return pd.to_numeric(parts[0]) * 3600 + pd.to_numeric(parts[1]) * 60 + pd.to_numeric(parts[2])


def clock(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


class Timetable:
    """The parts of AT's GTFS timetable this test needs."""

    def __init__(self, path=DATA / "gtfs" / "gtfs.zip"):
        with zipfile.ZipFile(path) as z:
            def read(name, **kwargs):
                return pd.read_csv(z.open(name), dtype=str, **kwargs)
            routes = read("routes.txt")
            self.trips = read("trips.txt").merge(
                routes[["route_id", "route_short_name", "route_type"]], on="route_id")
            self.calendar = read("calendar.txt")
            self.calendar_dates = read("calendar_dates.txt")
            self.stops = read("stops.txt", usecols=["stop_id", "stop_name", "stop_lat", "stop_lon"])
            stop_times = read("stop_times.txt", usecols=["trip_id", "departure_time", "stop_id", "stop_sequence"])
        self.stops[["stop_lat", "stop_lon"]] = self.stops[["stop_lat", "stop_lon"]].astype(float)
        stop_times["stop_sequence"] = stop_times.stop_sequence.astype(int)
        stop_times["sched_s"] = to_seconds(stop_times.departure_time)
        self.stop_times = stop_times.drop(columns="departure_time").dropna(subset=["sched_s"])

    def services_on(self, day):
        ds, weekday = day.strftime("%Y%m%d"), day.strftime("%A").lower()
        c, x = self.calendar, self.calendar_dates
        active = set(c.service_id[(c.start_date <= ds) & (c.end_date >= ds) & (c[weekday] == "1")])
        x = x[x.date == ds]
        return (active | set(x.service_id[x.exception_type == "1"])) - set(x.service_id[x.exception_type == "2"])

    def bus_trips_on(self, day):
        t = self.trips
        return t[t.service_id.isin(self.services_on(day)) & (t.route_type == "3")]

    def bus_stop_times_on(self, day):
        """Every scheduled bus departure that day, with epoch timestamps."""
        trips = self.bus_trips_on(day)[["trip_id", "route_short_name", "direction_id"]]
        st = self.stop_times.merge(trips, on="trip_id").sort_values(["trip_id", "stop_sequence"])
        st["sched_ts"] = pd.Timestamp(day, tz=TZ).timestamp() + st.sched_s
        # Nobody boards at a trip's last stop, and on loop routes (INN, AIR) it is also the
        # first stop: counting it would pair one bus's arrival with the next one's departure.
        last = st.groupby("trip_id").stop_sequence.transform("max")
        st["boarding"] = (st.stop_sequence < last) & ~st.duplicated(["trip_id", "stop_id"])
        # Each bus's own timetabled headway: how long after the previous bus it is due at that
        # stop. Some timetables alternate (route 39 runs 15, 19, 15, 15...), so a stop average won't do.
        on = st[st.boarding].sort_values("sched_ts")
        st["sched_headway"] = on.groupby(KEYS).sched_ts.diff()
        return st


def timetable(_args):
    tt = Timetable()
    s = tt.stops
    cbd_stops = set(s.stop_id[s.stop_lat.between(*CBD_LAT) & s.stop_lon.between(*CBD_LON)])
    cbd_trips = set(tt.stop_times.trip_id[tt.stop_times.stop_id.isin(cbd_stops)])
    st = tt.stop_times
    first = st.loc[st.groupby("trip_id").stop_sequence.idxmin(), ["trip_id", "sched_s"]]

    headways, headsigns = {}, None
    for label, day in DAYS:
        trips = tt.bus_trips_on(day).merge(first, on="trip_id")
        trips = trips[trips.sched_s.between(7 * 3600, 19 * 3600, inclusive="left")]
        per_direction = 720 / trips.groupby(["route_short_name", "direction_id"]).size()
        headways[label] = per_direction.groupby(level="route_short_name").min()  # the busier direction
        if label == "Weekday" and "trip_headsign" in trips:
            headsigns = trips.groupby("route_short_name").trip_headsign.agg(
                lambda h: " / ".join(h.value_counts().index[:2]))

    table = pd.DataFrame(headways)  # minutes between buses, 7am-7pm
    serves_cbd = tt.trips.assign(cbd=tt.trips.trip_id.isin(cbd_trips)).groupby("route_short_name").cbd.any()
    table["CBD"] = serves_cbd.reindex(table.index).fillna(False).map({True: "yes", False: ""})
    if headsigns is not None:
        table["towards"] = headsigns.reindex(table.index).fillna("")

    print("Average minutes between buses, 7am-7pm, in each route's busier direction\n")
    for label, _ in DAYS:
        h = table[label].dropna()
        frequent = h[h <= 15].index
        print(f"{label}: {len(h)} bus routes running; {len(frequent)} every 15 min or better "
              f"({(table.loc[frequent, 'CBD'] == 'yes').sum()} of them reach the CBD); "
              f"{(h <= 10).sum()} every 10 min or better")
    shown = table[table[[label for label, _ in DAYS]].min(axis=1) <= 15].sort_values("Weekday")
    print(f"\nFrequent routes:\n{shown.round(1).to_string()}")
    table.round(1).to_csv(DATA / "route_frequency.csv")


def load_snapshots(raw_dir):
    """One row per trip per snapshot, with the stop event AT reported for it (if any)."""
    rows = []
    for path in sorted(raw_dir.glob("*/*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            response = json.load(f)["response"]
        feed_ts = response["header"]["timestamp"]
        for entity in response["entity"]:
            update = entity.get("trip_update")
            if not update:
                continue
            trip = update.get("trip") or {}
            stu = update.get("stop_time_update") or {}
            if isinstance(stu, list):  # the GTFS-RT spec allows a list; AT sends one object
                stu = stu[-1] if stu else {}
            # Use the departure if it has happened, else the arrival; skip predictions of the future.
            times = [(stu.get(k) or {}).get("time") for k in ("departure", "arrival")]
            event = next((t for t in times if t and t <= feed_ts + 30), None)
            rows.append((feed_ts, trip.get("trip_id"), trip.get("schedule_relationship"),
                         stu.get("stop_sequence"), event))
    return pd.DataFrame(rows, columns=["feed_ts", "trip_id", "relationship", "stop_sequence", "event_ts"])


def estimate_times(st, snaps):
    """Each seen trip's time at every stop between the first and last stop it was reported at.

    Delay (actual minus timetable) is interpolated between reported stops, because a
    30-second poll can miss a stop when a bus passes two stops in quick succession.
    """
    events = (snaps.dropna(subset=["event_ts", "stop_sequence"])
              .drop_duplicates(["trip_id", "stop_sequence"], keep="last")
              .astype({"stop_sequence": int}))
    merged = (st[st.trip_id.isin(events.trip_id)]
              .merge(events[["trip_id", "stop_sequence", "event_ts"]], on=["trip_id", "stop_sequence"], how="left")
              .sort_values(["trip_id", "stop_sequence"]))
    merged["delay"] = merged.event_ts - merged.sched_ts
    merged.loc[merged.delay.abs() > 2 * 3600, "delay"] = np.nan  # wrong service day or bad data
    parts = []
    for _, g in merged.groupby("trip_id", sort=False):
        known = g[g.delay.notna()]
        if known.empty:
            continue
        seq = g.stop_sequence.to_numpy()
        delay = np.interp(seq, known.stop_sequence.to_numpy(), known.delay.to_numpy())
        inside = (seq >= known.stop_sequence.iat[0]) & (seq <= known.stop_sequence.iat[-1])
        parts.append(g.assign(est_ts=np.where(inside, g.sched_ts.to_numpy() + delay, np.nan)))
    return pd.concat(parts).dropna(subset=["est_ts"])


def observed(_args):
    polls = pd.read_csv(DATA / "polls.csv")
    ok = polls[polls.ok == 1]
    t0, t1 = ok.feed_timestamp.min(), ok.feed_timestamp.max()
    day = dt.datetime.fromtimestamp(t0).date()
    snaps = load_snapshots(DATA / "raw")
    tt = Timetable()
    st = tt.bus_stop_times_on(day)

    print(f"== Data quality, {day:%a %d %b} {clock(t0)}-{clock(t1)} ({(t1 - t0) / 3600:.1f} h)")
    waits = ok.feed_timestamp.sort_values().diff()
    print(f"Polls: {len(ok)} of {len(polls)} succeeded; median response {ok.latency_ms.median():.0f} ms; "
          f"median data age {ok.feed_age_s.median():.1f} s; longest wait between good snapshots {waits.max():.0f} s")
    seen = set(snaps.trip_id.dropna())
    print(f"Trips in the feed: {len(seen):,}; {len(seen & set(tt.trips.trip_id)) / len(seen):.1%} found in the timetable")
    span = st.groupby("trip_id").sched_ts.agg(["min", "max"])
    expected = set(span.index[(span["min"] <= t1 - 600) & (span["max"] >= t0 + 600)])
    cancelled = set(snaps.trip_id[snaps.relationship == 3]) & expected
    missing = expected - seen
    print(f"Bus trips timetabled during the window: {len(expected):,}; seen in the feed {len(expected & seen):,} "
          f"({len(expected & seen) / len(expected):.1%}); marked cancelled {len(cancelled)}; never seen {len(missing)}")

    est = estimate_times(st, snaps)
    print(f"Stop times estimated: {len(est):,} ({est.delay.notna().mean():.0%} reported directly, "
          f"the rest interpolated between reported stops)")

    # Stops with a bus at least every 15 minutes during the window, and the actual headways between seen buses.
    w = st[st.boarding & st.sched_ts.between(t0, t1)]
    frequent = w.groupby(KEYS).sched_headway.median().le(FREQUENT_S).rename("frequent")
    est = est[est.boarding].sort_values("est_ts")
    grouped = est.groupby(KEYS)
    est["headway"] = grouped.est_ts.diff()
    est["prev_trip"] = grouped.trip_id.shift()
    est["prev_ts"] = grouped.est_ts.shift()
    hw = est.dropna(subset=["headway", "sched_headway"]).join(frequent, on=KEYS)
    # Only buses that both passed during the window: a bus that passed before collection
    # started may have no estimate, which would make the next headway look like a gap.
    hw = hw[hw.frequent.eq(True) & (hw.prev_ts >= t0) & (hw.est_ts <= t1)].copy()
    hw["ratio"] = hw.headway / hw.sched_headway
    hw["flag"] = np.select([hw.ratio < BUNCH, hw.ratio > GAP], ["bunched", "gap"], "")

    # Is a gap real, or was another bus due in between that the data doesn't show?
    def times_at_stops(stop_times):
        return {key: np.sort(g.sched_ts.to_numpy()) for key, g in stop_times.groupby(KEYS)}
    due = st[st.boarding]
    untimed = ~due.set_index(["trip_id", "stop_sequence"]).index.isin(est.set_index(["trip_id", "stop_sequence"]).index)
    explanations = (
        ("cancelled trip", times_at_stops(due[due.trip_id.isin(cancelled)])),
        ("bus missing from data", times_at_stops(due[due.trip_id.isin(missing)])),
        # In the feed, but not while it was passing this stop (tracking started late or ended early).
        ("bus not tracked at this stop", times_at_stops(due[untimed & due.trip_id.isin(seen - cancelled)])),
    )

    def cause(row):
        key = (row.route_short_name, row.direction_id, row.stop_id)
        lo, hi = row.prev_ts - row.sched_headway, row.est_ts
        for label, table in explanations:
            times = table.get(key)
            if times is not None and ((times > lo) & (times < hi)).any():
                return label
        return "confirmed"
    hw["cause"] = ""
    gaps = hw.flag == "gap"
    if gaps.any():
        hw.loc[gaps, "cause"] = hw[gaps].apply(cause, axis=1)
    # A gap the data can't confirm is what the monitor would label suspect: keep it out of the scores.
    hw["suspect"] = hw.cause.isin(["bus missing from data", "bus not tracked at this stop"])
    hw["h2"], hw["s2"] = hw.headway ** 2, hw.sched_headway ** 2
    trusted = hw[~hw.suspect]

    def episodes(flag):
        pairs = trusted[trusted.flag == flag].groupby(["route_short_name", "direction_id", "prev_trip", "trip_id"]).size()
        return pairs[pairs >= MIN_STOPS]

    per_stop = trusted.groupby(KEYS).agg(n=("headway", "size"), h=("headway", "sum"), h2=("h2", "sum"),
                                         s=("sched_headway", "sum"), s2=("s2", "sum"))
    per_stop["ewt"] = (per_stop.h2 / (2 * per_stop.h) - per_stop.s2 / (2 * per_stop.s)) / 60
    per_stop = per_stop.reset_index()
    per_stop["weighted"] = per_stop.ewt * per_stop.n

    routes = trusted.groupby("route_short_name").agg(
        headways=("headway", "size"),
        timetable_min=("sched_headway", lambda s: s.median() / 60),
        spread=("ratio", "std"),
        bunched_pct=("flag", lambda f: (f == "bunched").mean() * 100),
        gap_pct=("flag", lambda f: (f == "gap").mean() * 100))
    sums = per_stop.groupby("route_short_name")[["weighted", "n"]].sum()
    routes["ewt_min"] = sums.weighted / sums.n
    routes["bunch_episodes"] = episodes("bunched").groupby(level=0).size().reindex(routes.index).fillna(0).astype(int)
    gap_pairs = episodes("gap")
    routes["gap_episodes"] = gap_pairs.groupby(level=0).size().reindex(routes.index).fillna(0).astype(int)
    routes["suspect_gaps"] = hw.groupby("route_short_name").suspect.sum().reindex(routes.index).astype(int)
    routes = routes[routes.headways >= 20].sort_values("ewt_min", ascending=False)

    print(f"\n== Frequent stops (timetabled every {FREQUENT_S // 60} min or better)")
    print(f"Headways measured: {len(hw):,} at {hw.groupby(KEYS).ngroups:,} stops on {hw.route_short_name.nunique()} routes")
    print("Gap causes:", hw.loc[gaps, "cause"].value_counts().to_dict())
    print(f"Suspect gaps the data can't confirm, left out from here on: {hw.suspect.sum()}")
    print(f"Bunched (under {BUNCH:g}x timetable): {(trusted.flag == 'bunched').mean():.1%} of headways; "
          f"gaps (over {GAP:g}x): {(trusted.flag == 'gap').mean():.1%}")
    print(f"Episodes (same pair of buses flagged at {MIN_STOPS}+ stops): "
          f"{len(episodes('bunched'))} bunching, {len(gap_pairs)} gaps")
    print(f"Routes with at least one bunching episode: {(routes.bunch_episodes > 0).sum()} of {len(routes)}")
    print(f"\nPer route (spread = variation of actual headways relative to timetable; ewt = excess wait, minutes)")
    print(routes.round(2).to_string())

    hw.drop(columns=["h2", "s2"]).to_csv(DATA / "headways.csv", index=False)
    routes.round(3).to_csv(DATA / "route_summary.csv")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("part", choices=["timetable", "observed"])
    args = parser.parse_args()
    {"timetable": timetable, "observed": observed}[args.part](args)


if __name__ == "__main__":
    main()
