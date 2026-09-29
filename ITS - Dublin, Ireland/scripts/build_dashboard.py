"""Build the presentation dashboard: Research/dashboard/dublin_bus_replay.html

Run:  conda run -n it python Research/scripts/build_dashboard.py [--observed-date 20260922]

Inputs
  GTFS_Dublin_Bus/                       static timetable (Mon-Thu service 190 is replayed)
  Research/dashboard/*_osm_raw.json      coastline, Liffey, M50, Phoenix Park (OpenStreetMap, ODbL)
  Research/dashboard/template.html       the page; __DATA__ and __LEAFLET_CSS__ are filled in here
  ~/nta_gtfsr_data/stu_*.csv.gz          optional: observed delays for --observed-date (Dublin service date)
"""
import argparse, json, subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]   # the "ITS - Dublin, Ireland" folder
G = ROOT / "GTFS_Dublin_Bus"
DASH = ROOT / "dashboard"
DATA_DIR = ROOT / "data"
SERVICE = "190"
LEAFLET_CSS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"


# ---------------------------------------------------------------- geometry helpers
def rdp(pts, tol_m):
    """Douglas-Peucker on (lat, lon) pairs, tolerance in metres."""
    if len(pts) < 3:
        return [list(p) for p in pts]
    P = np.asarray(pts, float)
    k = np.cos(np.radians(P[:, 0].mean()))
    XY = np.column_stack([P[:, 1] * 111320 * k, P[:, 0] * 110540])
    keep = np.zeros(len(P), bool)
    keep[[0, -1]] = True
    stack = [(0, len(P) - 1)]
    while stack:
        s, e = stack.pop()
        if e <= s + 1:
            continue
        a, ab = XY[s], XY[e] - XY[s]
        seg = XY[s + 1:e] - a
        L = np.hypot(*ab)
        d = np.hypot(seg[:, 0], seg[:, 1]) if L == 0 else np.abs(ab[0] * seg[:, 1] - ab[1] * seg[:, 0]) / L
        i = int(np.argmax(d))
        if d[i] > tol_m:
            keep[s + 1 + i] = True
            stack += [(s, s + 1 + i), (s + 1 + i, e)]
    return [[round(a, 5), round(b, 5)] for a, b in P[keep]]


def chain(ways):
    """Join ways that share end nodes into longer lines."""
    key = lambda p: (round(p[0], 7), round(p[1], 7))
    segs = [w for w in ways if len(w) >= 2]
    ends = defaultdict(list)
    for i, w in enumerate(segs):
        ends[key(w[0])].append(i)
        ends[key(w[-1])].append(i)
    used, lines = set(), []
    for i in range(len(segs)):
        if i in used:
            continue
        used.add(i)
        line = list(segs[i])
        for forward in (True, False):
            while True:
                k = key(line[-1] if forward else line[0])
                nxt = [j for j in ends[k] if j not in used]
                if not nxt:
                    break
                j = nxt[0]
                used.add(j)
                w = segs[j]
                if forward:
                    line += w[1:] if key(w[0]) == k else w[::-1][1:]
                else:
                    line = (w[:-1] if key(w[-1]) == k else w[::-1][:-1]) + line
        lines.append(line)
    return lines


def geom(el):
    return [(p["lat"], p["lon"]) for p in el.get("geometry", [])]


def basemap():
    raw = json.loads((DASH / "basemap_osm_raw.json").read_text())["elements"]
    liffey = json.loads((DASH / "liffey_osm_raw.json").read_text())["elements"]
    tag = lambda e, k: e.get("tags", {}).get(k)
    coast = chain([geom(e) for e in raw if tag(e, "natural") == "coastline"])
    closed = [c for c in coast if len(c) > 3 and c[0] == c[-1]]
    open_ = sorted([c for c in coast if not (len(c) > 3 and c[0] == c[-1])], key=len, reverse=True)
    main = open_[0]
    if main[0][0] < main[-1][0]:                       # run north -> south
        main = main[::-1]
    sea = main + [(main[-1][0], -5.4), (main[0][0], -5.4)]
    park_rel = max((e for e in raw if e["type"] == "relation" and tag(e, "leisure") == "park"),
                   key=lambda e: sum(len(m.get("geometry") or []) for m in e.get("members", [])))
    park_ways = [[(p["lat"], p["lon"]) for p in m["geometry"]] for m in park_rel["members"]
                 if m.get("role") == "outer" and m.get("geometry")]
    park = max(chain(park_ways), key=len)
    return {
        "sea": rdp(sea, 25),
        "islands": [rdp(c, 25) for c in closed if len(c) > 8],
        "coast": [rdp(c, 25) for c in open_ if len(c) > 5],
        "liffey": [rdp(c, 15) for c in chain([geom(e) for e in liffey if e["type"] == "way"])],
        "m50": [rdp(c, 30) for c in chain([geom(e) for e in raw if tag(e, "highway") == "motorway"]) if len(c) > 3],
        "park": rdp(park, 20),
    }


# ---------------------------------------------------------------- timetable
def secs(col):
    hms = col.str.split(":", expand=True).astype(int)
    return hms[0] * 3600 + hms[1] * 60 + hms[2]


def network_and_trips():
    routes = pd.read_csv(G / "routes.txt", dtype=str)
    trips = pd.read_csv(G / "trips.txt", dtype=str)
    trips = trips[trips["service_id"] == SERVICE].merge(routes[["route_id", "route_short_name", "route_long_name"]],
                                                         on="route_id")
    stops = pd.read_csv(G / "stops.txt", dtype={"stop_id": str})
    st = pd.read_csv(G / "stop_times.txt", usecols=["trip_id", "stop_sequence", "stop_id", "departure_time"],
                     dtype={"trip_id": str, "stop_id": str})
    st = st[st["trip_id"].isin(trips["trip_id"])]
    st["t"] = secs(st["departure_time"])
    st = st.sort_values(["trip_id", "stop_sequence"])
    shapes = pd.read_csv(G / "shapes.txt", dtype={"shape_id": str}).sort_values(["shape_id", "shape_pt_sequence"])
    shape_km = shapes.groupby("shape_id")["shape_dist_traveled"].max() / 1000

    # per-trip summary
    g = st.groupby("trip_id")
    tt = pd.DataFrame({"start": g["t"].first(), "end": g["t"].last()})
    trips = trips.join(tt, on="trip_id")
    trips["km"] = trips["shape_id"].map(shape_km)
    trips["h"] = (trips["end"] - trips["start"]) / 3600
    trips["hour"] = trips["start"] // 3600

    # route metrics: scheduled speed by window, weekday trips
    windows = {"early": (5, 7), "am": (7, 10), "mid": (10, 16), "pm": (16, 19), "eve": (19, 24)}
    route_order = sorted(trips["route_short_name"].unique(),
                         key=lambda r: (not r[0].isdigit(), int("".join(c for c in r if c.isdigit()) or 0), r))
    ridx = {r: i for i, r in enumerate(route_order)}
    shape_pts = {sid: grp[["shape_pt_lat", "shape_pt_lon"]].to_numpy() for sid, grp in shapes.groupby("shape_id")}
    routes_out = []
    for r in route_order:
        tr = trips[trips["route_short_name"] == r]
        spd = {}
        for k, (a, b) in windows.items():
            w = tr[(tr["hour"] >= a) & (tr["hour"] < b)]
            spd[k] = round(float(w["km"].sum() / w["h"].sum()), 1) if w["h"].sum() > 0 else None
        main_shapes = tr.groupby("direction_id")["shape_id"].agg(lambda s: s.mode().iat[0]).tolist()
        routes_out.append({"n": r, "name": tr["route_long_name"].iat[0], "trips": int(len(tr)), "spd": spd,
                           "shapes": [rdp(shape_pts[s], 15) for s in main_shapes]})

    # stops, stop patterns, delta-encoded trips
    used = st["stop_id"].unique()
    sidx = {s: i for i, s in enumerate(used)}
    stops = stops.set_index("stop_id").loc[used]
    stop_xy = [[round(a, 5), round(b, 5)] for a, b in zip(stops["stop_lat"], stops["stop_lon"])]
    pat_idx, patterns, trip_rows, trip_ids, seq_pos = {}, [], [], [], {}
    heads = sorted(trips["trip_headsign"].fillna("").unique())
    hidx = {h: i for i, h in enumerate(heads)}
    meta = trips.set_index("trip_id")
    for tid, grp in st.groupby("trip_id", sort=False):
        pat = tuple(sidx[s] for s in grp["stop_id"])
        if pat not in pat_idx:
            pat_idx[pat] = len(patterns)
            patterns.append(list(pat))
        t = grp["t"].to_numpy()
        m = meta.loc[tid]
        trip_rows.append([ridx[m["route_short_name"]], hidx[m["trip_headsign"] if isinstance(m["trip_headsign"], str) else ""],
                          pat_idx[pat], int(t[0])] + np.diff(t).astype(int).tolist())
        trip_ids.append(tid)
        seq_pos[tid] = {int(s): i for i, s in enumerate(grp["stop_sequence"])}

    # buses running per 5 min (timetable)
    delta = np.zeros(31 * 12 + 2, int)
    for row in trip_rows:
        s, e = row[3], row[3] + sum(row[4:])
        delta[s // 300] += 1
        delta[e // 300 + 1] -= 1
    running = np.cumsum(delta)[: 30 * 12 + 1].tolist()

    # busiest stops (weekday bus visits)
    busy = st["stop_id"].value_counts().head(12)
    busiest = [{"name": stops.loc[s, "stop_name"], "lat": round(stops.loc[s, "stop_lat"], 5),
                "lon": round(stops.loc[s, "stop_lon"], 5), "buses": int(c)} for s, c in busy.items()]
    return (routes_out, stop_xy, patterns, heads, trip_rows, trip_ids, seq_pos, running, busiest)


# ---------------------------------------------------------------- observed delays (optional)
def observed(dates, trip_ids, seq_pos):
    """Observed delays for one or more Dublin service days, keyed by date.

    Each day is independent: `t` is seconds since that day's local midnight, so the
    replay keeps a 24-hour timeline and the viewer switches days rather than
    scrubbing across two midnights.
    """
    files = sorted(DATA_DIR.glob("stu_*.csv.gz"))
    if not files:
        return None
    stu_all = pd.concat((pd.read_csv(f, dtype={"trip_id": str, "start_date": str, "vehicle_id": str})
                         for f in files))
    trips_files = sorted(DATA_DIR.glob("trips_*.csv.gz"))
    tr_all = pd.concat((pd.read_csv(f, dtype={"trip_id": str, "start_date": str}) for f in trips_files)) \
        if trips_files else None
    tix = {t: i for i, t in enumerate(trip_ids)}

    days = {}
    for date in dates:
        stu = stu_all[(stu_all["start_date"] == date) & stu_all["vehicle_id"].notna()].copy()
        if stu.empty:
            print(f"  ! no observed rows for {date}, skipped")
            continue
        stu["delay"] = stu["dep_delay"].fillna(stu["arr_delay"])
        stu = stu.dropna(subset=["delay", "stop_sequence"])
        midnight = pd.Timestamp(date, tz="Europe/Dublin").timestamp()
        stu["t"] = (stu["poll_ts"] - midnight).astype(int)
        out = {}
        for tid, grp in stu.sort_values("poll_ts").groupby("trip_id"):
            if tid not in tix:
                continue
            pos = seq_pos[tid]
            out[tix[tid]] = [[int(t), pos.get(int(s), -1), int(d)] for t, s, d in
                             zip(grp["t"], grp["stop_sequence"], grp["delay"]) if abs(d) < 3 * 3600]
        cancelled = []
        if tr_all is not None:
            c = tr_all[(tr_all["start_date"] == date)
                       & tr_all["trip_rel"].astype(str).str.upper().str.contains("CANCEL")]
            cancelled = sorted({tix[t] for t in c["trip_id"] if t in tix})
        days[date] = {"trips": out, "cancelled": cancelled,
                      "last_poll_s": int(stu["poll_ts"].max() - midnight) if len(stu) else None}
        print(f"  {date}: {len(out)} tracked trips, {len(cancelled)} cancelled, "
              f"last poll {days[date]['last_poll_s']}s after midnight")
    if not days:
        return None
    return {"dates": sorted(days), "days": days}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--observed-date", nargs="+", metavar="YYYYMMDD",
                    help="one or more Dublin service dates to colour buses by real lateness; "
                         "with several, the page gets a day switch")
    args = ap.parse_args()
    routes, stop_xy, patterns, heads, trip_rows, trip_ids, seq_pos, running, busiest = network_and_trips()
    summary = json.loads((ROOT / "figures" / "gtfs_summary.json").read_text())
    speed_by_hour = summary["speed_kmh_by_hour"]
    data = {
        "meta": {"service": "Monday–Thursday timetable (NTA GTFS, valid from 20 Sep 2026)",
                 "speed_by_hour": speed_by_hour, "running_5min": running,
                 "peak_pm": summary["peak_trips_in_progress_pm"]},
        "basemap": basemap(), "routes": routes, "stops": stop_xy, "patterns": patterns, "heads": heads,
        "trips": trip_rows, "busiest": busiest,
        "observed": observed(args.observed_date, trip_ids, seq_pos) if args.observed_date else None,
    }
    css = subprocess.run(["curl", "-sSL", LEAFLET_CSS], capture_output=True, text=True, check=True).stdout
    html = (DASH / "template.html").read_text()
    html = html.replace("/*__LEAFLET_CSS__*/", css).replace("__DATA__", json.dumps(data, separators=(",", ":")))
    out = DASH / "dublin_bus_replay.html"
    out.write_text(html)
    obs = data["observed"]
    obs_desc = ", ".join(f"{d} ({len(obs['days'][d]['trips'])} trips)" for d in obs["dates"]) if obs else "none"
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB): {len(routes)} routes, {len(trip_rows)} trips, "
          f"{len(patterns)} stop patterns\nobserved days: {obs_desc}")


if __name__ == "__main__":
    main()
