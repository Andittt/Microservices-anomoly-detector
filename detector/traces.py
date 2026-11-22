"""Trace evidence: pulls finished OpenTelemetry spans from each service, assembles
them into distributed traces and computes per-service SELF time (span duration minus
time spent waiting on child spans). Self time separates "checkout is slow because it
waits on inventory" from "checkout itself is slow".
"""
import time
from collections import defaultdict

import httpx

from common import config


def fetch_spans(since, client=None):
    client = client or httpx.Client(timeout=3.0, limits=httpx.Limits(max_keepalive_connections=0))
    spans = []
    for svc, url in config.SERVICE_URLS.items():
        try:
            spans.extend(client.get(f"{url}/traces", params={"since": since}).json())
        except Exception:
            pass
    return spans


def assemble(spans):
    traces = defaultdict(list)
    for s in spans:
        traces[s["trace_id"]].append(s)
    out = []
    for tid, ss in traces.items():
        ids = {s["span_id"] for s in ss}
        roots = [s for s in ss if s["parent_id"] is None or s["parent_id"] not in ids]
        root = min(roots or ss, key=lambda s: s["start"])
        if root["service"] != "checkout":
            continue  # only complete checkout-rooted traces
        out.append({
            "trace_id": tid,
            "start": min(s["start"] for s in ss),
            "duration_ms": (max(s["end"] for s in ss) - min(s["start"] for s in ss)) * 1000,
            "error": any(s["error"] for s in ss),
            "spans": sorted(ss, key=lambda s: s["start"]),
            "self_ms": self_times(ss),
            "error_origin": error_origin(ss),
        })
    out.sort(key=lambda t: t["start"])
    return out


def self_times(spans):
    children = defaultdict(float)
    for s in spans:
        if s["parent_id"]:
            children[s["parent_id"]] += s["duration_ms"]
    # Only count top-level-in-service spans' self time; nested spans of the same
    # service are already inside their parent's duration, so use exclusive time per span.
    per_service = defaultdict(float)
    for s in spans:
        per_service[s["service"]] += max(0.0, s["duration_ms"] - children[s["span_id"]])
    return dict(per_service)


def error_origin(spans):
    """Deepest service whose span is in error and whose children are not in error."""
    by_parent = defaultdict(list)
    for s in spans:
        by_parent[s["parent_id"]].append(s)
    origins = set()
    for s in spans:
        if s["error"] and s["kind"] != "CLIENT":
            child_err = any(c["error"] for c in by_parent[s["span_id"]] if c["service"] != s["service"])
            # descend through same-service spans
            stack = list(by_parent[s["span_id"]])
            while stack and not child_err:
                c = stack.pop()
                if c["service"] != s["service"] and c["error"]:
                    child_err = True
                stack.extend(by_parent[c["span_id"]])
            if not child_err:
                origins.add(s["service"])
    return sorted(origins)


def summarize(traces):
    """Mean self time per service and error-origin counts over a set of traces."""
    if not traces:
        return {"n": 0, "self_ms": {}, "error_origin_rate": {}}
    sums = defaultdict(float)
    errs = defaultdict(int)
    for t in traces:
        for svc, ms in t["self_ms"].items():
            sums[svc] += ms
        for svc in t["error_origin"]:
            errs[svc] += 1
    n = len(traces)
    return {
        "n": n,
        "self_ms": {s: sums[s] / n for s in config.SERVICES},
        "error_origin_rate": {s: errs[s] / n for s in config.SERVICES},
    }


def recent_summary(seconds=15):
    return summarize(assemble(fetch_spans(time.time() - seconds - 5)))
