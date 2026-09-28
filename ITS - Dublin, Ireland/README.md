# Dublin Bus ITS — data analysis

Supporting analysis for MSE806 *Intelligent Transportation Systems*, Assessment 1: a case study of
Dublin Bus. The World Bank case study the assessment is built on describes the system as it stood
around 2011, when automatic vehicle location was in its first year. This repository closes the
fifteen-year gap with measurements taken from the National Transport Authority's own public feeds
in September 2026.

Two questions are answered with data rather than with sources:

1. **What does the timetable admit about congestion?** Scheduled running times encode the delay the
   operator already expects, so peak congestion can be measured from the schedule alone.
2. **What actually happened on the road?** Polling the real-time feed every 62 seconds for two full
   weekdays gives observed lateness, cancellations, and the share of trips that never reported a bus.

---

## Headline results

### Scheduled service — Monday to Thursday timetable, valid from 20 Sep 2026

| Measure | Value |
|---|---|
| Routes · stops · weekday trips | 116 · 4,337 · 8,099 |
| In-service distance · bus-hours | 161,179 km · 9,857 h |
| Buses running at the peaks | 795 at 08:30 · 817 at 17:30 |
| Median stop spacing · trip length · trip time | 361 m · 20.3 km · 72 min |
| Peak penalty built into the timetable | 08:00 departures are timetabled a median **18.8%** longer than 06:00 departures on the same route pattern; **31%** are at least 25% longer |

### Observed service — two complete Dublin service days, 22–23 Sep 2026

| Measure | Value |
|---|---|
| Tracked trips · stop observations | 14,894 · 670,073 |
| **On time** (NTA rule: ≤1 min early, ≤5 min 59 s late) | **67.7%** |
| On time, low-frequency routes only | 69.7% |
| Median lateness · 90th percentile | +1.8 min · +9.3 min |
| Excess wait time, high-frequency route-directions | +1.11 min |
| Scheduled trips that appeared in the feed | 99.2% |
| …tracked by a vehicle · cancelled | 93.6% · 2.6% |
| **Scheduled, not cancelled, never tracked** ("ghost" trips) | **3.0%** |

Punctuality is a peak problem rather than an all-day problem: it falls from about 88% on time at
05:00 to 58% at 08:00 and 60% at 17:00, and recovers in the evening. No headline measure differed
by more than one percentage point between the two days.

Worst route-level performance by median lateness: **40D** (+4.6 min, 55.7% on time), H3 (+4.0 min),
E2 (+3.3 min), 43 and 42 (+3.1 min).

### An outage the feed did not report

For one hour — 10:00–11:00 on 22 September — the national real-time feed degraded while continuing
to serve a current header timestamp. 38 of 59 successful polls returned no new delay information at
all, trips present in the feed fell from about 1,530 to 1,218, and the backlog was released in a
single burst afterwards.

This is only visible if successive payloads are compared, because `FeedHeader.timestamp` stayed
within 12 seconds of real time throughout. A client trusting the header would have gone on showing
confident, ageing predictions. It was the only such hour in the collection period, and it is
excluded from the figures above.

---

## What is in this repository

```
scripts/     collection and analysis
  collect_gtfsr.py    polls NTA GTFS-Realtime TripUpdates every 62 s, stores only changed values
  analyse_gtfsr.py    punctuality, excess wait time, coverage, Figure 4
  gtfs_figures.py     Figures 1–3 from the static timetable
  build_dashboard.py  builds the replay map from GTFS + observed delays

figures/     the charts used in the report, each with the CSV behind it
  fig1_speed_by_hour.png        scheduled speed by departure hour
  fig2_buses_in_service.png     buses in service through the day
  fig3_peak_vs_early.png        peak versus early running times
  fig4_live_delay_by_hour.png   observed lateness by hour
  gtfs_summary.json             static measures
  gtfsr_summary.json            observed measures
  gtfsr_route_summary.csv       per-route punctuality

dashboard/   an interactive replay of the network
  dublin_bus_replay.html        self-contained; open it in a browser
  template.html                 page shell the builder fills
  *_osm_raw.json                basemap geometry from OpenStreetMap

data/        what was collected
  stu_YYYYMMDD.csv.gz           observed delay at each stop a bus passed
  trips_YYYYMMDD.csv.gz         per-trip status (running, cancelled, vehicle assigned)
  collector.log                 every poll attempt; the analysis reads it for coverage
```

### The dashboard

`dashboard/dublin_bus_replay.html` is a single self-contained file — download it and open it in a
browser, no server needed. It replays a weekday across the network, with each bus coloured by its
observed lateness on 22 September 2026, and a second mode showing scheduled speed by route.

---

## Method

**The feed does not predict; it reports.** Each trip update lists the stops a bus has *already
passed* where its delay changed — a trail of breakpoints, each carrying the delay observed there.
They are not forecasts for stops ahead. Treating the first entry as a next-stop prediction produces
badly wrong results; that mistake was made and corrected during this work.

From that, the analysis:

- takes the **last value reported** for each (trip, date, stop) and carries it forward to the stops
  in between, which is how GTFS-Realtime intends the data to be read;
- counts **only tracked buses** — trip updates carrying a vehicle ID. Untracked trips are mostly not
  yet started and are shown at schedule, so including them would flatter punctuality;
- applies the NTA's own punctuality rule: on time = no more than 1 minute early and no more than
  5 minutes 59 seconds late;
- computes **excess wait time** on high-frequency route-directions (≥5 buses/hour, 10:00–15:00) as
  AWT = Σh² / 2Σh, actual minus scheduled, per route/direction/stop/day between 07:00 and 19:00;
- reports coverage only for **complete service days** — at least 40 polls attempted in every hour
  from 05:00 to 23:59 Dublin time.

Two details that are easy to get wrong:

- **Poll counts come from the log, not from the stored rows.** The collector writes only new or
  changed values, so an hour in which the feed republishes identical data leaves almost no trace in
  the CSVs even though polling never stopped. Counting rows instead of polls makes a healthy day
  look like a collection failure.
- **A Dublin service day is not a file.** Files are named by the collecting machine's local date,
  and service days run past midnight (GTFS times beyond 24:00:00). All analysis keys off the feed's
  `start_date`.

---

## Reproducing this

Requires Python 3 with `pandas` and `matplotlib`.

**1. Get the static timetable.** Download the GTFS schedule for Dublin Bus from
[Transport for Ireland](https://www.transportforireland.ie/transitData/PT_Data.html) and unzip it to
`GTFS_Dublin_Bus/` **inside this folder**. It is not included here — `stop_times.txt` alone is 77 MB.
The analysis used the feed valid from 20 September 2026. Both steps below need it.

```bash
python scripts/gtfs_figures.py        # writes Figures 1-3 to figures/
```

**2. Analyse the collected real-time data.** No API key needed — the two days of data are already in
`data/`, and `--data-dir data --out-dir figures` are the defaults:

```bash
python scripts/analyse_gtfsr.py       # writes Figure 4, the route summary and gtfsr_summary.json
```

**3. Collecting fresh data.** Needs a free NTA API key from the
[NTA developer portal](https://developer.nationaltransport.ie/). Put it in `~/.nta_api_key` or set
`NTA_API_KEY`. No key is stored in this repository.

```bash
python scripts/collect_gtfsr.py --hours 48    # appends to data/
```

The feed's fair-use limit is one call per minute; the collector polls every 62 seconds and backs off
on errors.

**4. Rebuilding the dashboard.**

```bash
python scripts/build_dashboard.py --observed-date 20260922
```

---

## Data sources and licensing

- **GTFS schedule and GTFS-Realtime**, National Transport Authority, via Transport for Ireland.
  Licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Contains NTA data.
- **Basemap geometry** © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors,
  licensed [ODbL](https://opendatacommons.org/licenses/odbl/).

Observed delays are the NTA's own AVL-derived figures, not independent measurements. Two weekdays
are a sample, not a season. The feed covers Dublin Bus only — Go-Ahead Ireland routes are published
separately — and in-service running only, excluding dead running to and from depots. Comparisons
with the 2011 case study are approximate, because the two count different things.

Student work for MSE806 at Yoobee Colleges. Not affiliated with, or endorsed by, Dublin Bus or the
National Transport Authority.
