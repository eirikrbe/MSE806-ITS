#!/usr/bin/env python3
"""Collector for the AT Gap Monitor.

Polls Auckland Transport's combined realtime feed (vehicle positions, trip
updates and alerts) and saves every snapshot so it can be analysed later.

    python3 collector.py --once          one test call, then a summary of the feed
    python3 collector.py --until 12:00   poll every 30 s until 12:00

Keys are read from .env (PRIMARY_KEY, SECONDARY_KEY) and never printed.
Licence plates are removed before anything is written to disk.
"""

import argparse
import csv
import datetime as dt
import gzip
import http.client
import json
import signal
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

FEED_URL = "https://api.at.govt.nz/realtime/legacy/"
HERE = Path(__file__).resolve().parent
LOG_FIELDS = [
    "polled_at", "key", "http_status", "ok", "latency_ms", "bytes_wire", "bytes_json",
    "feed_timestamp", "feed_age_s", "entities", "vehicle_positions", "trip_updates",
    "alerts", "snapshot", "error",
]


def load_keys(env_path):
    """Return [(name, key)] for PRIMARY_KEY and SECONDARY_KEY from a .env file."""
    values = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.removeprefix("export ").strip()] = value.strip().strip("\"'")
    keys = [(name, values[name]) for name in ("PRIMARY_KEY", "SECONDARY_KEY") if values.get(name)]
    if not keys:
        sys.exit(f"No PRIMARY_KEY or SECONDARY_KEY in {env_path}")
    return keys


def fetch(key):
    """Call the combined feed once. Returns (status, wire_bytes, body, latency_ms)."""
    request = urllib.request.Request(FEED_URL, headers={
        "Ocp-Apim-Subscription-Key": key,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    })
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=25) as response:
        wire = response.read()
        status = response.status
        encoding = response.headers.get("Content-Encoding", "")
    latency_ms = round((time.monotonic() - started) * 1000)
    body = gzip.decompress(wire) if encoding == "gzip" else wire
    return status, len(wire), body, latency_ms


def seconds(ts):
    """Feed timestamps should be POSIX seconds; accept milliseconds too."""
    if isinstance(ts, (int, float)) and ts > 1e12:
        return ts / 1000
    return ts


def strip_plates(entities):
    """Remove licence plates (data minimisation: the analysis never needs them)."""
    for entity in entities:
        for part in ("trip_update", "vehicle"):
            descriptor = (entity.get(part) or {}).get("vehicle")
            if isinstance(descriptor, dict):
                descriptor.pop("license_plate", None)


def poll(keys, key_index):
    """Fetch and summarise one snapshot. Returns (log_row, feed or None, key_index)."""
    row = {"polled_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "ok": 0}
    for _ in keys:
        name, key = keys[key_index]
        row["key"] = name
        try:
            status, wire_bytes, body, latency_ms = fetch(key)
            break
        except urllib.error.HTTPError as err:
            row.update(http_status=err.code, error=f"HTTP {err.code}")
            if err.code not in (401, 403):
                return row, None, key_index
            key_index = (key_index + 1) % len(keys)  # key rejected: try the other one
        except (OSError, http.client.HTTPException) as err:
            row["error"] = f"{type(err).__name__}: {err}"[:200]
            return row, None, key_index
    else:
        return row, None, key_index

    row.update(http_status=status, latency_ms=latency_ms, bytes_wire=wire_bytes, bytes_json=len(body))
    try:
        feed = json.loads(body)
    except json.JSONDecodeError as err:
        row["error"] = f"bad JSON: {err}"[:200]
        return row, None, key_index
    if feed.get("status") != "OK":
        row["error"] = f"feed status {feed.get('status')!r}: {feed.get('error')}"[:200]
        return row, None, key_index

    response = feed.get("response") or {}
    entities = response.get("entity") or []
    feed_ts = seconds((response.get("header") or {}).get("timestamp"))
    parts = Counter(part for e in entities for part in ("vehicle", "trip_update", "alert") if e.get(part))
    strip_plates(entities)
    row.update(
        ok=1,
        feed_timestamp=feed_ts,
        feed_age_s=round(time.time() - feed_ts, 1) if isinstance(feed_ts, (int, float)) else "",
        entities=len(entities),
        vehicle_positions=parts["vehicle"],
        trip_updates=parts["trip_update"],
        alerts=parts["alert"],
        error="",
    )
    return row, feed, key_index


def save_snapshot(feed, data_dir, polled_at):
    """Write one snapshot as gzipped JSON: data/raw/YYYY-MM-DD/HHMMSS.json.gz."""
    when = dt.datetime.fromisoformat(polled_at)
    folder = data_dir / "raw" / when.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{when:%H%M%S}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as out:
        json.dump(feed, out, separators=(",", ":"))
    return path


def append_log(row, log_path):
    """One line per poll in data/polls.csv: the reliability record for the report."""
    is_new = not log_path.exists()
    with log_path.open("a", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def describe(feed):
    """Print what the feed actually contains, to check assumptions before a long run."""
    entities = feed["response"]["entity"]
    positions = [e["vehicle"] for e in entities if e.get("vehicle")]
    updates = [e["trip_update"] for e in entities if e.get("trip_update")]
    on_trip = [p for p in positions if (p.get("trip") or {}).get("route_id")]
    routes = Counter(p["trip"]["route_id"] for p in on_trip)
    print(f"Vehicle positions: {len(positions):,} ({len(on_trip):,} on a trip, {len(routes):,} routes)")
    print(f"Trip updates:      {len(updates):,}")
    print(f"Alerts:            {sum(1 for e in entities if e.get('alert')):,}")

    def share(items, test):
        return f"{sum(1 for i in items if test(i)) / len(items):.0%}" if items else "n/a"

    print("Position fields filled in (non-zero):", ", ".join(
        f"{f} {share(positions, lambda p, f=f: (p.get('position') or {}).get(f) not in (None, '', 0))}"
        for f in ("latitude", "longitude", "bearing", "speed", "odometer")))
    for f in ("occupancy_status", "congestion_level"):
        print(f"{f} values:", dict(Counter(p.get(f) for p in positions).most_common()))
    def stop_updates(update):
        """AT sends stop_time_update as one object; the GTFS-RT spec allows a list."""
        stu = update.get("stop_time_update")
        return [stu] if isinstance(stu, dict) else (stu or [])

    print("Stop updates per trip update:", dict(sorted(Counter(len(stop_updates(u)) for u in updates).items())))
    print("Trip schedule_relationship:", dict(Counter((u.get("trip") or {}).get("schedule_relationship") for u in updates)))
    print("Busiest routes now (vehicles):", ", ".join(f"{r} {n}" for r, n in routes.most_common(12)))
    sample = next((u for u in updates if u.get("stop_time_update")), None)
    if sample:
        print("Sample trip update:", json.dumps({k: sample.get(k) for k in ("trip", "stop_time_update", "timestamp", "delay")})[:700])
    sample = next(iter(on_trip), None)
    if sample:
        print("Sample vehicle position:", json.dumps(sample)[:500])


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="make one call and describe the feed")
    parser.add_argument("--until", metavar="HH:MM", help="stop at this local time (default: run until stopped)")
    parser.add_argument("--interval", type=int, default=30, help="seconds between polls (default 30)")
    parser.add_argument("--data-dir", type=Path, default=HERE / "data", help="where snapshots are saved")
    return parser.parse_args()


def stop_time(until):
    """Next occurrence of HH:MM local time, or None to run until stopped."""
    if not until:
        return None
    hour, minute = map(int, until.split(":"))
    now = dt.datetime.now()
    stop = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return stop if stop > now else stop + dt.timedelta(days=1)


def main():
    args = parse_args()
    keys = load_keys(HERE / ".env")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.data_dir / "polls.csv"

    if args.once:
        row, feed, _ = poll(keys, 0)
        if feed is not None:
            row["snapshot"] = save_snapshot(feed, args.data_dir, row["polled_at"]).name
        append_log(row, log_path)
        print(f"HTTP {row.get('http_status')} using {row.get('key')}, {row.get('latency_ms')} ms, "
              f"{row.get('bytes_wire', 0):,} bytes on the wire, {row.get('bytes_json', 0):,} bytes of JSON")
        if feed is None:
            sys.exit(f"Failed: {row.get('error')}")
        print(f"Feed age: {row['feed_age_s']} s")
        describe(feed)
        return

    stop_at = stop_time(args.until)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"Polling every {args.interval} s" + (f" until {stop_at:%a %H:%M}" if stop_at else "")
          + ". Ctrl+C to stop.", flush=True)
    key_index, failures, polls, saved = 0, 0, 0, 0
    next_at = time.monotonic()
    try:
        while stop_at is None or dt.datetime.now() < stop_at:
            row, feed, key_index = poll(keys, key_index)
            polls += 1
            if feed is not None:
                row["snapshot"] = save_snapshot(feed, args.data_dir, row["polled_at"]).name
                saved += 1
                failures = 0
                next_at = max(next_at + args.interval, time.monotonic())
                print(f"{row['polled_at'][11:19]}  ok  {row['vehicle_positions']:>5,} vehicles  "
                      f"{row['trip_updates']:>5,} trips  {row['bytes_wire'] / 1e6:5.2f} MB  "
                      f"{row['latency_ms']:>5} ms  feed age {row['feed_age_s']} s", flush=True)
            else:
                failures += 1
                next_at = time.monotonic() + min(10 * 2 ** (failures - 1), 120)  # back off: 10, 20, 40 ... 120 s
                print(f"{row['polled_at'][11:19]}  FAILED ({failures} in a row): {row.get('error')}", flush=True)
            append_log(row, log_path)
            time.sleep(max(0.0, next_at - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        print(f"Stopped. {saved} of {polls} polls saved to {args.data_dir / 'raw'}", flush=True)


if __name__ == "__main__":
    main()
