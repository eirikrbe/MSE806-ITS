"""Collect NTA GTFS-Realtime TripUpdates for Dublin Bus, one poll per minute.

What the feed contains (checked 22 Sep 2026): each active trip has a list of stop_time_updates
at stops the bus has ALREADY passed, each with the delay (seconds, + = late) observed there.
Only stops where the delay changed are listed, so the list is a growing trail of breakpoints.
A consumer applies the latest delay to the stops after it.

This collector therefore saves:
  stu_YYYYMMDD.csv.gz    every (trip, stop) delay the first time it appears, and again if it changes
  trips_YYYYMMDD.csv.gz  every trip the first time it appears, and again if its status or vehicle changes
Repeats from minute to minute are skipped, which keeps a week of data small.

Fair usage (developer.nationaltransport.ie/usagepolicy): one call per 60 s per key.
Data licence: CC BY 4.0 - credit the National Transport Authority, "as is".

Key:     one line in ~/.nta_api_key   (or env var NTA_API_KEY)
Output:  ~/nta_gtfsr_data/   (outside OneDrive to avoid sync churn)
Run:     nohup caffeinate -i /opt/anaconda3/envs/it/bin/python collect_gtfsr.py --hours 168 \
             >> ~/nta_gtfsr_data/nohup.out 2>&1 &
Stop:    pkill -f collect_gtfsr.py
"""
import argparse, csv, gzip, json, logging, os, sys, time
from datetime import datetime
from pathlib import Path

import requests

URL = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates"
INTERVAL_S = 62
OUT = Path(__file__).resolve().parents[1] / "data"
STATIC_TRIPS = Path(__file__).resolve().parents[1] / "GTFS_Dublin_Bus" / "trips.txt"
STU_FIELDS = ["poll_ts", "trip_id", "start_date", "route_id", "direction_id", "vehicle_id",
              "stop_sequence", "stop_id", "arr_delay", "dep_delay", "stu_rel"]
TRIP_FIELDS = ["poll_ts", "trip_id", "start_date", "start_time", "route_id", "direction_id",
               "trip_rel", "vehicle_id", "n_stu", "tu_ts"]


def api_key() -> str:
    key = os.environ.get("NTA_API_KEY") or (Path.home() / ".nta_api_key").read_text().strip()
    if not key:
        sys.exit("No API key: put it in ~/.nta_api_key or NTA_API_KEY")
    return key


def g(d, *names, default=None):
    """First present key; the JSON may be snake_case or camelCase."""
    for n in names:
        if isinstance(d, dict) and n in d:
            return d[n]
    return default


def fetch(session: requests.Session) -> dict:
    r = session.get(URL, params={"format": "json"}, timeout=45)
    r.raise_for_status()
    return r.json()


def append(path: Path, fields: list, rows: list):
    if not rows:
        return
    new = not path.exists()
    with gzip.open(path, "at", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


class Collector:
    def __init__(self, keep: set | None):
        self.keep = keep
        self.last_stu = {}      # (trip, date, seq) -> (arr, dep, rel)
        self.trip_state = {}    # (trip, date) -> (trip_rel, vehicle)
        self.seen = {}          # (trip, date) -> poll number last seen
        self.n = 0

    def process(self, feed: dict, poll_ts: int):
        self.n += 1
        stu_rows, trip_rows, matched = [], [], 0
        for ent in g(feed, "entity", "Entity", default=[]) or []:
            tu = g(ent, "trip_update", "tripUpdate")
            if not tu:
                continue
            trip = g(tu, "trip", default={})
            tid, sd = g(trip, "trip_id", "tripId"), g(trip, "start_date", "startDate")
            if self.keep is not None and tid not in self.keep:
                continue
            matched += 1
            veh = g(g(tu, "vehicle", default={}) or {}, "id")
            rel = g(trip, "schedule_relationship", "scheduleRelationship", default="SCHEDULED")
            route, direction = g(trip, "route_id", "routeId"), g(trip, "direction_id", "directionId")
            stus = g(tu, "stop_time_update", "stopTimeUpdate", default=[]) or []
            k = (tid, sd)
            self.seen[k] = self.n
            if self.trip_state.get(k) != (rel, veh):
                self.trip_state[k] = (rel, veh)
                trip_rows.append({"poll_ts": poll_ts, "trip_id": tid, "start_date": sd,
                                  "start_time": g(trip, "start_time", "startTime"), "route_id": route,
                                  "direction_id": direction, "trip_rel": rel, "vehicle_id": veh,
                                  "n_stu": len(stus), "tu_ts": g(tu, "timestamp")})
            for s in stus:
                seq = g(s, "stop_sequence", "stopSequence")
                val = (g(g(s, "arrival", default={}) or {}, "delay"), g(g(s, "departure", default={}) or {}, "delay"),
                       g(s, "schedule_relationship", "scheduleRelationship"))
                kk = (tid, sd, seq)
                if self.last_stu.get(kk) != val:
                    self.last_stu[kk] = val
                    stu_rows.append({"poll_ts": poll_ts, "trip_id": tid, "start_date": sd, "route_id": route,
                                     "direction_id": direction, "vehicle_id": veh, "stop_sequence": seq,
                                     "stop_id": g(s, "stop_id", "stopId"), "arr_delay": val[0],
                                     "dep_delay": val[1], "stu_rel": val[2]})
        if self.n % 100 == 0:                       # forget trips not seen for 4 hours
            old = {k for k, last in self.seen.items() if last < self.n - 240}
            self.seen = {k: v for k, v in self.seen.items() if k not in old}
            self.trip_state = {k: v for k, v in self.trip_state.items() if k not in old}
            self.last_stu = {k: v for k, v in self.last_stu.items() if (k[0], k[1]) not in old}
        return stu_rows, trip_rows, matched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=168, help="stop after this many hours (default 7 days)")
    ap.add_argument("--once", action="store_true", help="single poll, print a summary, write nothing")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    logging.basicConfig(filename=OUT / "collector.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    with open(STATIC_TRIPS, newline="", encoding="utf-8-sig") as f:
        col = Collector({r["trip_id"] for r in csv.DictReader(f)})

    session = requests.Session()
    session.headers.update({"x-api-key": api_key(), "Cache-Control": "no-cache"})
    end = time.time() + args.hours * 3600
    backoff = INTERVAL_S
    logging.info("collector v2 started (trail of observed delays, changes only)")

    while time.time() < end:
        t0 = time.time()
        try:
            feed = fetch(session)
            stu_rows, trip_rows, matched = col.process(feed, int(t0))
            if matched == 0 and col.keep is not None:
                logging.warning("no entities match the static Dublin Bus trip_ids; storing all operators")
                col.keep = None
            if args.once:
                print(json.dumps({"dublin_bus_trips": matched, "new_stop_delays": len(stu_rows),
                                  "sample": stu_rows[:3]}, indent=1, default=str))
                return
            day = datetime.fromtimestamp(t0).strftime("%Y%m%d")
            append(OUT / f"stu_{day}.csv.gz", STU_FIELDS, stu_rows)
            append(OUT / f"trips_{day}.csv.gz", TRIP_FIELDS, trip_rows)
            logging.info("poll ok: %d Dublin Bus trips, %d new/changed stop delays, %d new/changed trips",
                         matched, len(stu_rows), len(trip_rows))
            backoff = INTERVAL_S
        except Exception as e:                                   # network, 429, bad JSON...
            logging.error("poll failed: %s", e)
            backoff = min(backoff * 2, 600)
            time.sleep(max(0, backoff - (time.time() - t0)))
            continue
        time.sleep(max(1, INTERVAL_S - (time.time() - t0)))
    logging.info("finished after %.1f h", args.hours)


if __name__ == "__main__":
    main()
