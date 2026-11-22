"""Collects a HEALTHY telemetry baseline into data/healthy_baseline.csv.

Each row = one timestamped 15-feature vector. Rows with any missing feature are
rejected (and counted) instead of being silently filled with zeros.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import config  # noqa: E402
from detector import traces  # noqa: E402
from detector.features import FeatureBuilder, is_complete, sleep_until_next_tick  # noqa: E402


def main(minutes, out):
    fb = FeatureBuilder()
    out = Path(out)
    rows_needed = int(minutes * 60 / config.SAMPLE_INTERVAL)
    written = rejected = 0
    print(f"[collect] collecting {rows_needed} healthy rows (~{minutes} min) -> {out}", flush=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp"] + config.FEATURES)
        next_t = time.time()
        while written < rows_needed:
            next_t = sleep_until_next_tick(next_t)
            feats, status = fb.step()
            if not is_complete(feats) or any(s != "ok" for s in status.values()):
                rejected += 1
                continue
            w.writerow([f"{time.time():.3f}"] + [f"{feats[k]:.6f}" for k in config.FEATURES])
            f.flush()
            written += 1
            if written % 12 == 0 or written == rows_needed:
                print(f"[collect] {written}/{rows_needed} rows "
                      f"(rejected {rejected}) checkout p95={feats['checkout_latency_p95']*1000:.0f}ms "
                      f"rps={feats['checkout_rps']:.1f}", flush=True)
    print(f"[collect] done: {written} rows written, {rejected} incomplete rows rejected", flush=True)

    # Healthy trace baseline: mean per-service self time and error-origin rate
    summary = traces.recent_summary(seconds=45)
    (config.DATA_DIR / "trace_baseline.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[collect] healthy trace baseline from {summary['n']} traces: "
          + ", ".join(f"{s}={ms:.0f}ms" for s, ms in summary["self_ms"].items()), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=10)
    p.add_argument("--out", default=str(config.DATA_DIR / "healthy_baseline.csv"))
    a = p.parse_args()
    main(a.minutes, a.out)
