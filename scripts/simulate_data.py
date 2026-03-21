#!/usr/bin/env python3
"""
scripts/simulate_data.py
─────────────────────────
RhythmCloud cardiac IoT telemetry simulator.

Generates realistic telemetry for multiple patients and devices,
sends events to the live API, and supports batch generation
over configurable time windows.

Usage:
  python scripts/simulate_data.py                        # defaults
  python scripts/simulate_data.py --patients 5 --events 100
  python scripts/simulate_data.py --patients 3 --events 50 --abnormal-rate 0.2
  python scripts/simulate_data.py --dry-run              # print without sending
  python scripts/simulate_data.py --hours-back 24        # spread over 24 hours

Environment:
  API_BASE_URL  The deployed API Gateway base URL (or set --api-url)
"""

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Generator

import urllib.request
import urllib.error

# ── Default configuration ─────────────────────────────────────────────────────
DEFAULT_API_URL     = os.environ.get(
    "API_BASE_URL",
    "https://5gzmj1ltf7.execute-api.eu-north-1.amazonaws.com/dev"
)
DEFAULT_PATIENTS    = 5
DEFAULT_EVENTS      = 50
DEFAULT_ABNORMAL    = 0.15   # 15% abnormal events
DEFAULT_TX_FAIL     = 0.08   # 8%  transmission failures
DEFAULT_SYNC_FAIL   = 0.06   # 6%  sync failures
DEFAULT_BATTERY_LOW = 0.10   # 10% chance of low battery episode
DEFAULT_DELAY_MS    = 100    # ms between API calls
DEFAULT_HOURS_BACK  = 6      # spread events over last N hours

# ── Patient + device registry ─────────────────────────────────────────────────
PATIENT_PROFILES = [
    {
        "patientId":  "P001",
        "deviceId":   "D-P001-001AB",
        "name":       "Alice Brennan",
        "age":        67,
        "condition":  "atrial_fibrillation",
        "baseHR":     78,
        "baseBPsys":  138,
        "baseBPdia":  88,
        "baseSpo2":   96.5,
    },
    {
        "patientId":  "P002",
        "deviceId":   "D-P002-002CD",
        "name":       "Brian Doyle",
        "age":        72,
        "condition":  "heart_failure",
        "baseHR":     88,
        "baseBPsys":  145,
        "baseBPdia":  92,
        "baseSpo2":   95.0,
    },
    {
        "patientId":  "P003",
        "deviceId":   "D-P003-003EF",
        "name":       "Catherine Murphy",
        "age":        58,
        "condition":  "hypertension",
        "baseHR":     72,
        "baseBPsys":  155,
        "baseBPdia":  98,
        "baseSpo2":   97.5,
    },
    {
        "patientId":  "P004",
        "deviceId":   "D-P004-004GH",
        "name":       "David O'Sullivan",
        "age":        81,
        "condition":  "arrhythmia",
        "baseHR":     65,
        "baseBPsys":  128,
        "baseBPdia":  82,
        "baseSpo2":   94.0,
    },
    {
        "patientId":  "P005",
        "deviceId":   "D-P005-005IJ",
        "name":       "Eleanor Walsh",
        "age":        63,
        "condition":  "coronary_artery_disease",
        "baseHR":     70,
        "baseBPsys":  132,
        "baseBPdia":  84,
        "baseSpo2":   97.0,
    },
]

EVENT_TYPES = ["vitals", "vitals", "vitals", "vitals", "sync", "device_health", "alert", "battery"]


# ── Simulation engine ─────────────────────────────────────────────────────────

class PatientSimulator:
    """Simulates realistic cardiac telemetry for a single patient."""

    def __init__(self, profile: dict, abnormal_rate: float,
                 tx_fail_rate: float, sync_fail_rate: float,
                 battery_low_rate: float):
        self.profile          = profile
        self.abnormal_rate    = abnormal_rate
        self.tx_fail_rate     = tx_fail_rate
        self.sync_fail_rate   = sync_fail_rate
        self.battery_low_rate = battery_low_rate

        # Internal state
        self._battery    = random.uniform(45, 95)
        self._signal_dbm = random.uniform(-80, -55)
        self._episode    = False   # True during an abnormal episode
        self._episode_len = 0

    def next_event(self, timestamp: datetime) -> dict:
        """Generate the next telemetry event for this patient."""
        profile = self.profile

        # Battery drains slowly over time
        self._battery = max(5, self._battery - random.uniform(0, 0.3))

        # Signal strength fluctuates
        self._signal_dbm = max(-120, min(-30,
            self._signal_dbm + random.uniform(-3, 3)
        ))

        # Determine if we're in/starting an abnormal episode
        if not self._episode and random.random() < self.abnormal_rate:
            self._episode     = True
            self._episode_len = random.randint(2, 6)

        if self._episode:
            vitals = self._abnormal_vitals()
            self._episode_len -= 1
            if self._episode_len <= 0:
                self._episode = False
        else:
            vitals = self._normal_vitals()

        # Transmission / sync status
        if random.random() < self.tx_fail_rate:
            tx_status = "failed"
        elif random.random() < 0.05:
            tx_status = "pending"
        else:
            tx_status = "success"

        if random.random() < self.sync_fail_rate:
            sync_status = "failed"
        else:
            sync_status = "synced"

        # Battery low event type override
        if self._battery < 20 and random.random() < self.battery_low_rate:
            event_type = "battery"
        elif self._episode:
            event_type = "alert"
        else:
            event_type = random.choice(EVENT_TYPES)

        return {
            "patientId":          profile["patientId"],
            "deviceId":           profile["deviceId"],
            "timestamp":          timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "heartRate":          vitals["heartRate"],
            "spo2":               vitals["spo2"],
            "systolicBP":         vitals["systolicBP"],
            "diastolicBP":        vitals["diastolicBP"],
            "batteryLevel":       round(self._battery, 1),
            "signalStrength":     round(self._signal_dbm, 1),
            "transmissionStatus": tx_status,
            "syncStatus":         sync_status,
            "eventType":          event_type,
        }

    def _normal_vitals(self) -> dict:
        """Generate vitals within normal range with realistic variation."""
        p = self.profile
        # Circadian-style variation using sine wave
        hour_rad = (datetime.now().hour / 24) * 2 * math.pi
        hr_offset = math.sin(hour_rad) * 8

        return {
            "heartRate":  round(max(45, min(120,
                p["baseHR"] + hr_offset + random.gauss(0, 5)
            )), 1),
            "spo2":       round(min(100, max(93,
                p["baseSpo2"] + random.gauss(0, 0.5)
            )), 1),
            "systolicBP": round(max(90, min(180,
                p["baseBPsys"] + random.gauss(0, 8)
            )), 1),
            "diastolicBP": round(max(55, min(110,
                p["baseBPdia"] + random.gauss(0, 5)
            )), 1),
        }

    def _abnormal_vitals(self) -> dict:
        """Generate abnormal vitals simulating a cardiac event."""
        p          = self.profile
        event_kind = random.choice([
            "tachycardia", "bradycardia", "hypertensive_crisis", "hypoxia"
        ])

        if event_kind == "tachycardia":
            return {
                "heartRate":   round(random.uniform(130, 180), 1),
                "spo2":        round(random.uniform(91, 95), 1),
                "systolicBP":  round(p["baseBPsys"] + random.uniform(20, 40), 1),
                "diastolicBP": round(p["baseBPdia"] + random.uniform(10, 25), 1),
            }
        elif event_kind == "bradycardia":
            return {
                "heartRate":   round(random.uniform(30, 49), 1),
                "spo2":        round(random.uniform(88, 93), 1),
                "systolicBP":  round(p["baseBPsys"] - random.uniform(15, 30), 1),
                "diastolicBP": round(p["baseBPdia"] - random.uniform(5, 15), 1),
            }
        elif event_kind == "hypertensive_crisis":
            return {
                "heartRate":   round(p["baseHR"] + random.uniform(10, 30), 1),
                "spo2":        round(random.uniform(92, 96), 1),
                "systolicBP":  round(random.uniform(185, 230), 1),
                "diastolicBP": round(random.uniform(115, 140), 1),
            }
        else:  # hypoxia
            return {
                "heartRate":   round(p["baseHR"] + random.uniform(15, 35), 1),
                "spo2":        round(random.uniform(82, 89), 1),
                "systolicBP":  round(p["baseBPsys"] + random.gauss(0, 10), 1),
                "diastolicBP": round(p["baseBPdia"] + random.gauss(0, 6), 1),
            }


# ── API client ────────────────────────────────────────────────────────────────

def send_event(api_url: str, event: dict, dry_run: bool) -> bool:
    """POST a single event to the API. Returns True on success."""
    endpoint = f"{api_url.rstrip('/')}/events"

    if dry_run:
        print(f"  [DRY RUN] Would POST: {json.dumps(event)}")
        return True

    body = json.dumps(event).encode("utf-8")
    req  = urllib.request.Request(
        endpoint,
        data    = body,
        headers = {"Content-Type": "application/json"},
        method  = "POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("eventId") is not None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        print(f"  [ERROR] HTTP {exc.code}: {body}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  [ERROR] {exc}", file=sys.stderr)
        return False


# ── Timestamp generator ───────────────────────────────────────────────────────

def generate_timestamps(
    count: int,
    hours_back: int,
) -> Generator[datetime, None, None]:
    """
    Yield `count` timestamps spread evenly over the last `hours_back` hours,
    with a small random jitter so they don't land exactly on the hour.
    """
    now   = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours_back)
    span  = timedelta(hours=hours_back)

    for i in range(count):
        fraction = i / max(count - 1, 1)
        ts = start + span * fraction + timedelta(seconds=random.uniform(-60, 60))
        yield ts


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="RhythmCloud cardiac IoT telemetry simulator"
    )
    parser.add_argument("--api-url",       default=DEFAULT_API_URL,
                        help="API Gateway base URL")
    parser.add_argument("--patients",      type=int, default=DEFAULT_PATIENTS,
                        help="Number of patients to simulate (max 5)")
    parser.add_argument("--events",        type=int, default=DEFAULT_EVENTS,
                        help="Total events to generate per patient")
    parser.add_argument("--abnormal-rate", type=float, default=DEFAULT_ABNORMAL,
                        help="Fraction of events that are abnormal (0.0–1.0)")
    parser.add_argument("--tx-fail-rate",  type=float, default=DEFAULT_TX_FAIL,
                        help="Fraction of events with transmission failure")
    parser.add_argument("--sync-fail-rate",type=float, default=DEFAULT_SYNC_FAIL,
                        help="Fraction of events with sync failure")
    parser.add_argument("--hours-back",    type=int,   default=DEFAULT_HOURS_BACK,
                        help="Spread events over the last N hours")
    parser.add_argument("--delay-ms",      type=int,   default=DEFAULT_DELAY_MS,
                        help="Delay in ms between API calls (0 = no delay)")
    parser.add_argument("--dry-run",       action="store_true",
                        help="Print events without sending to API")
    parser.add_argument("--seed",          type=int,   default=None,
                        help="Random seed for reproducible output")

    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    num_patients = min(args.patients, len(PATIENT_PROFILES))
    profiles     = PATIENT_PROFILES[:num_patients]

    print("=" * 60)
    print("  RhythmCloud Telemetry Simulator")
    print("=" * 60)
    print(f"  API URL:       {args.api_url}")
    print(f"  Patients:      {num_patients}")
    print(f"  Events/patient:{args.events}")
    print(f"  Total events:  {num_patients * args.events}")
    print(f"  Abnormal rate: {args.abnormal_rate:.0%}")
    print(f"  TX fail rate:  {args.tx_fail_rate:.0%}")
    print(f"  Hours back:    {args.hours_back}")
    print(f"  Dry run:       {args.dry_run}")
    print("=" * 60)
    print()

    total_sent     = 0
    total_failed   = 0
    total_abnormal = 0

    for profile in profiles:
        simulator = PatientSimulator(
            profile          = profile,
            abnormal_rate    = args.abnormal_rate,
            tx_fail_rate     = args.tx_fail_rate,
            sync_fail_rate   = args.sync_fail_rate,
            battery_low_rate = DEFAULT_BATTERY_LOW,
        )

        print(f"Patient {profile['patientId']} — {profile['name']} "
              f"({profile['condition'].replace('_',' ').title()})")

        timestamps = list(generate_timestamps(args.events, args.hours_back))
        sent = failed = abnormal = 0

        for ts in timestamps:
            event = simulator.next_event(ts)

            is_bad = (
                event["transmissionStatus"] == "failed"
                or event["syncStatus"] == "failed"
                or float(event["heartRate"]) < 50
                or float(event["heartRate"]) > 130
                or float(event["spo2"]) < 90
                or float(event["batteryLevel"]) < 20
            )
            if is_bad:
                abnormal += 1

            ok = send_event(args.api_url, event, args.dry_run)
            if ok:
                sent += 1
            else:
                failed += 1

            # Progress indicator
            total_done = sent + failed
            if total_done % 10 == 0 or total_done == args.events:
                bar_len  = 20
                filled   = int(bar_len * total_done / args.events)
                bar      = "█" * filled + "░" * (bar_len - filled)
                print(f"  [{bar}] {total_done}/{args.events} "
                      f"sent={sent} failed={failed} abnormal={abnormal}",
                      end="\r")

            if args.delay_ms > 0 and not args.dry_run:
                time.sleep(args.delay_ms / 1000)

        print(f"  [{('█' * 20)}] {args.events}/{args.events} "
              f"sent={sent} failed={failed} abnormal={abnormal}   ")

        total_sent     += sent
        total_failed   += failed
        total_abnormal += abnormal
        print()

    print("=" * 60)
    print(f"  Simulation complete")
    print(f"  Total sent:     {total_sent}")
    print(f"  Total failed:   {total_failed}")
    print(f"  Total abnormal: {total_abnormal}")
    success_rate = (total_sent / (total_sent + total_failed) * 100) if (total_sent + total_failed) else 0
    print(f"  API success:    {success_rate:.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
