"""Automated controlled-fault experiment (Milestone 1, section 08 evaluation criteria).

Requires the demo stack to be running (python run.py evaluate starts it automatically).
Timeline:  healthy -> inventory 1.5 s delay -> recovery -> payment 30% errors -> recovery
Measures:  detection delay, healthy false-positive rate, fault detection rate,
           root-cause (service) localization accuracy, trace agreement.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402

from common import config  # noqa: E402

API = f"http://127.0.0.1:{config.DASHBOARD_PORT}"
LIVE_LOG = config.DATA_DIR / "live_log.csv"


def post(path):
    httpx.post(f"{API}{path}", json={}, timeout=5).raise_for_status()


def wait(seconds, label):
    end = time.time() + seconds
    while time.time() < end:
        try:
            st = httpx.get(f"{API}/api/state", timeout=5).json()["state"]
            extra = f"score={st.get('score', 0) or 0:.3f} status={st['status']}"
            if st["status"] == "anomaly":
                extra += f" suspected={st.get('suspected_service')}"
        except Exception as e:
            extra = f"(detector unreachable: {e})"
        print(f"  [{label}] {max(0, end - time.time()):5.0f}s left  {extra}", flush=True)
        time.sleep(min(10, max(0.1, end - time.time())))


def wait_until_ready():
    print("Waiting for the detector to fill its first window...", flush=True)
    while True:
        try:
            st = httpx.get(f"{API}/api/state", timeout=5).json()["state"]
            if st["status"] != "warming_up":
                return
        except Exception:
            pass
        time.sleep(3)


def load_rows(t_start, t_end):
    rows = []
    with open(LIVE_LOG, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = float(r["timestamp"])
            if t_start <= t <= t_end:
                r["t"] = t
                rows.append(r)
    return rows


def analyze(phases, recovery_grace):
    t_start, t_end = phases[0]["start"], phases[-1]["end"]
    rows = load_rows(t_start, t_end)
    fault_phases = [p for p in phases if p["kind"] == "fault"]

    def in_grace(t):  # right after a fault is cleared the 60 s window still contains faulty samples
        return any(p["end"] <= t < p["end"] + recovery_grace for p in fault_phases)

    healthy = [r for r in rows if r["active_fault"] == "none" and not in_grace(r["t"])
               and not any(p["start"] <= r["t"] <= p["end"] for p in fault_phases)]
    fp = sum(int(r["alert"]) for r in healthy)
    result = {
        "healthy": {
            "windows": len(healthy),
            "duration_s": round(len(healthy) * config.SAMPLE_INTERVAL),
            "false_alerts": fp,
            "false_positive_rate": fp / len(healthy) if healthy else None,
        },
        "faults": [],
    }
    for p in fault_phases:
        fr = [r for r in rows if p["start"] <= r["t"] <= p["end"]]
        alerts = [r for r in fr if r["alert"] == "1"]
        first = alerts[0]["t"] if alerts else None
        correct = [r for r in alerts if r["suspected_service"] == p["true_service"]]
        trace_ok = [r for r in alerts if r["trace_suspect"] == p["true_service"]]
        result["faults"].append({
            "name": p["name"], "true_service": p["true_service"],
            "windows": len(fr), "duration_s": round(p["end"] - p["start"]),
            "detected": bool(alerts),
            "detection_delay_s": round(first - p["start"], 1) if first else None,
            "detection_rate": len(alerts) / len(fr) if fr else None,
            "localization_accuracy": len(correct) / len(alerts) if alerts else None,
            "trace_agreement": len(trace_ok) / len(alerts) if alerts else None,
            "suspected_counts": {s: sum(1 for r in alerts if r["suspected_service"] == s) for s in config.SERVICES},
        })
    return result


def pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def write_report(res, phases, meta):
    lines = [
        "# Evaluation results", "",
        f"Run at {time.strftime('%Y-%m-%d %H:%M:%S')}. Sampling every {config.SAMPLE_INTERVAL:.0f} s, "
        f"window {config.SEQ_LEN} samples, threshold {meta['threshold']:.4f}. "
        "An alert is confirmed after 2 consecutive windows above threshold.", "",
        "## Timeline", "",
        "| Phase | Duration |", "|---|---|",
    ]
    for p in phases:
        lines.append(f"| {p['name']} | {p['end'] - p['start']:.0f} s |")
    h = res["healthy"]
    lines += [
        "", "## Healthy false-positive rate", "",
        f"- Evaluated healthy windows: **{h['windows']}** (~{h['duration_s']} s, excluding the post-fault recovery period)",
        f"- False alerts: **{h['false_alerts']}** -> false-positive rate **{pct(h['false_positive_rate'])}**", "",
        "## Fault experiments", "",
        "| Fault | True service | Detected | Detection delay | Detection rate | Localization accuracy | Trace agreement |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in res["faults"]:
        lines.append(f"| {f['name']} | {f['true_service']} | {'yes' if f['detected'] else 'no'} | "
                     f"{f['detection_delay_s'] if f['detection_delay_s'] is not None else 'n/a'} s | "
                     f"{pct(f['detection_rate'])} ({f['windows']} windows) | {pct(f['localization_accuracy'])} | "
                     f"{pct(f['trace_agreement'])} |")
    lines += [
        "", "Definitions:",
        "- *Detection delay*: time from fault injection to the first confirmed alert.",
        "- *Detection rate*: fraction of fault-period windows with a confirmed alert (includes the first windows "
        "before the fault had entered the 60 s window, so it is a conservative number).",
        "- *Localization accuracy*: fraction of alert windows where the top-ranked service was the injected one.",
        "- *Trace agreement*: fraction of alert windows where trace evidence independently pointed to the injected service.",
        "", "## Limitations", "",
        "- Single machine, simulated services and synthetic traffic; results are not production-scale.",
        "- Two fault types only (latency, errors); CPU / memory faults were not injected.",
        "- The ranking is a hypothesis supported by traces, not proof of causality.",
        "- Thresholds are calibrated on one healthy run; a new machine should be re-baselined (python run.py setup).",
    ]
    (config.RESULTS_DIR / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (config.RESULTS_DIR / "evaluation.json").write_text(json.dumps({"phases": phases, "results": res}, indent=2), encoding="utf-8")
    print("\n".join(lines))


def main(healthy_s, fault_s, recovery_s):
    meta = httpx.get(f"{API}/api/state", timeout=5).json()["model"]
    post("/api/fault/reset")
    wait_until_ready()
    phases = []

    def phase(name, kind, seconds, action=None, true_service=None):
        if action:
            post(action)
        start = time.time()
        print(f"\n== {name} ({seconds:.0f} s) ==", flush=True)
        wait(seconds, name)
        phases.append({"name": name, "kind": kind, "start": start, "end": time.time(), "true_service": true_service})

    phase("healthy baseline", "healthy", healthy_s)
    phase("inventory latency +1.5 s", "fault", fault_s, "/api/fault/inventory_delay", "inventory")
    post("/api/fault/reset")
    phase("recovery 1", "healthy", recovery_s)
    phase("payment 30% errors", "fault", fault_s, "/api/fault/payment_errors", "payment")
    post("/api/fault/reset")
    phase("recovery 2", "healthy", recovery_s)
    time.sleep(1)
    res = analyze(phases, recovery_grace=config.SEQ_LEN * config.SAMPLE_INTERVAL + 10)
    write_report(res, phases, meta)
    print(f"\nSaved results/evaluation.md and results/evaluation.json", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--healthy", type=float, default=180)
    p.add_argument("--fault", type=float, default=120)
    p.add_argument("--recovery", type=float, default=120)
    a = p.parse_args()
    main(a.healthy, a.fault, a.recovery)
