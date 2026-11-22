"""Builds the 15-feature telemetry vector (5 metrics x 3 services) from Prometheus-format
/metrics endpoints.

Python-only mode scrapes each service's /metrics directly (same exposition format
Prometheus uses). Rates and p95 are computed from counter / histogram-bucket deltas
over a short window, exactly like PromQL rate() and histogram_quantile().
"""
import time
from collections import deque

import httpx
from prometheus_client.parser import text_string_to_metric_families

from common import config


def parse_metrics(text):
    snap = {"requests": 0.0, "errors": 0.0, "buckets": {}, "cpu": None, "mem": None}
    for fam in text_string_to_metric_families(text):
        for s in fam.samples:
            if s.name == "app_requests_total":
                snap["requests"] += s.value
                if s.labels.get("status_class") == "5xx":
                    snap["errors"] += s.value
            elif s.name == "app_request_duration_seconds_bucket":
                le = float(s.labels["le"])
                snap["buckets"][le] = snap["buckets"].get(le, 0.0) + s.value
            elif s.name == "app_process_cpu_percent":
                snap["cpu"] = s.value
            elif s.name == "app_process_memory_bytes":
                snap["mem"] = s.value / (1024 * 1024)
    return snap


def histogram_quantile(q, bucket_deltas):
    """Same linear interpolation as PromQL histogram_quantile()."""
    les = sorted(bucket_deltas)
    total = bucket_deltas[les[-1]] if les else 0
    if total <= 0:
        return None
    rank = q * total
    prev_le, prev_count = 0.0, 0.0
    for le in les:
        count = bucket_deltas[le]
        if count >= rank:
            if le == float("inf"):
                return prev_le
            if count == prev_count:
                return le
            return prev_le + (le - prev_le) * (rank - prev_count) / (count - prev_count)
        prev_le, prev_count = le, count
    return les[-2] if len(les) > 1 else None


def local_client(timeout=3.0):
    """HTTP client without keep-alive: avoids reusing a connection the server just closed
    (uvicorn drops idle connections after 5 s, the same as our sampling interval)."""
    return httpx.Client(timeout=timeout, limits=httpx.Limits(max_keepalive_connections=0))


class FeatureBuilder:
    def __init__(self, window_ticks=config.RATE_WINDOW_TICKS):
        self.history = {s: deque(maxlen=window_ticks + 1) for s in config.SERVICES}
        self.last_values = {}
        self.client = local_client()
        self.failures = {s: 0 for s in config.SERVICES}

    def scrape(self):
        """Returns {service: snapshot or None if unreachable}. A service is only reported
        unreachable after 2 consecutive failed scrapes (each with one retry)."""
        out = {}
        for svc, url in config.SERVICE_URLS.items():
            out[svc] = None
            for _attempt in range(2):
                try:
                    r = self.client.get(f"{url}/metrics")
                    r.raise_for_status()
                    out[svc] = parse_metrics(r.text)
                    out[svc]["t"] = time.time()
                    break
                except Exception:
                    time.sleep(0.2)
            self.failures[svc] = 0 if out[svc] is not None else self.failures[svc] + 1
        return out

    def is_down(self, svc):
        return self.failures[svc] >= 2

    def step(self):
        """Scrape once and return (feature_dict, status). status per service is
        'ok', 'warming_up', 'no_traffic' or 'unreachable'."""
        snaps = self.scrape()
        features, status = {}, {}
        for svc in config.SERVICES:
            snap = snaps[svc]
            if snap is None:
                status[svc] = "unreachable" if self.is_down(svc) else "scrape_failed"
                for fam in config.FEATURE_FAMILIES:
                    features[f"{svc}_{fam}"] = None
                continue
            hist = self.history[svc]
            hist.append(snap)
            features[f"{svc}_cpu"] = snap["cpu"]
            features[f"{svc}_memory_mb"] = snap["mem"]
            if len(hist) < 2:
                status[svc] = "warming_up"
                for fam in ("latency_p95", "error_rate", "rps"):
                    features[f"{svc}_{fam}"] = None
                continue
            old, new = hist[0], hist[-1]
            dt = max(new["t"] - old["t"], 1e-6)
            d_req = new["requests"] - old["requests"]
            d_err = new["errors"] - old["errors"]
            if d_req < 0:  # service restarted -> counters reset
                hist.clear()
                hist.append(snap)
                status[svc] = "warming_up"
                for fam in ("latency_p95", "error_rate", "rps"):
                    features[f"{svc}_{fam}"] = None
                continue
            features[f"{svc}_rps"] = d_req / dt
            if d_req > 0:
                deltas = {le: new["buckets"].get(le, 0) - old["buckets"].get(le, 0) for le in new["buckets"]}
                features[f"{svc}_latency_p95"] = histogram_quantile(0.95, deltas)
                features[f"{svc}_error_rate"] = d_err / d_req
                status[svc] = "ok"
            else:
                # No requests in window: latency / error rate are undefined, not zero.
                features[f"{svc}_latency_p95"] = self.last_values.get(f"{svc}_latency_p95")
                features[f"{svc}_error_rate"] = self.last_values.get(f"{svc}_error_rate")
                status[svc] = "no_traffic"
        for k, v in features.items():
            if v is not None:
                self.last_values[k] = v
        return features, status


def is_complete(features):
    return all(features.get(f) is not None for f in config.FEATURES)


def sleep_until_next_tick(next_t):
    delay = next_t - time.time()
    if delay > 0:
        time.sleep(delay)
    return max(next_t + config.SAMPLE_INTERVAL, time.time())
