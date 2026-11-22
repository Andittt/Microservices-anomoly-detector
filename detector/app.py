"""Live anomaly detector + dashboard server.

Every SAMPLE_INTERVAL seconds:
  1. build the 15-feature vector from the services' metrics
  2. score the latest 12-step window with the LSTM Autoencoder
  3. flag an anomaly when the score is above the calibrated threshold
     (an alert is CONFIRMED after 2 consecutive anomalous windows)
  4. localize: rank services by feature-level reconstruction error, with a
     dependency adjustment (checkout symptoms explained by a deviating downstream)
  5. corroborate with trace evidence (per-service self time / error origin)
It also exports its own Prometheus metrics at /metrics and serves the dashboard.
"""
import csv
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest  # noqa: E402

from common import config  # noqa: E402
from detector import traces as tr  # noqa: E402
from detector.features import FeatureBuilder, local_client, sleep_until_next_tick  # noqa: E402
from detector.model import load_artifacts, reconstruction_errors  # noqa: E402

DASHBOARD_DIR = config.ROOT / "dashboard"
LIVE_LOG = config.DATA_DIR / "live_log.csv"
FAULT_LOG = config.DATA_DIR / "fault_log.csv"

G_SCORE = Gauge("anomaly_score", "LSTM-AE reconstruction error of latest window")
G_THRESH = Gauge("anomaly_threshold", "Calibrated anomaly threshold")
G_FLAG = Gauge("anomaly_flag", "1 if a confirmed anomaly alert is active")
G_SERVICE = Gauge("anomaly_service_score", "Localization score per service", ["service"])
G_SUSPECT = Gauge("anomaly_suspected_service", "1 for the currently suspected service", ["service"])
G_FEATURE = Gauge("anomaly_feature_error", "Reconstruction error per feature (12-step window)", ["feature"])


class Detector:
    def __init__(self):
        self.model, self.scaler, self.meta = load_artifacts()
        self.threshold = float(self.meta["threshold"])
        self.p99 = np.array(self.meta["feature_error_p99"])
        self.trace_base = self.meta.get("trace_baseline") or {}
        self.fb = FeatureBuilder()
        self.window = deque(maxlen=config.SEQ_LEN)
        self.history = deque(maxlen=240)  # 20 minutes of ticks
        self.consecutive = 0
        self.alert_started = None
        self.lock = threading.Lock()
        self.state = {"status": "warming_up", "message": "Collecting the first 60 s of telemetry..."}
        self.events = deque(maxlen=50)
        self.client = local_client()
        self.recent_traces = []
        self.last_values = {}
        G_THRESH.set(self.threshold)
        new_log = not LIVE_LOG.exists()
        self.log_f = open(LIVE_LOG, "a", newline="", encoding="utf-8")
        self.log_w = csv.writer(self.log_f)
        if new_log:
            self.log_w.writerow(["timestamp", "score", "threshold", "raw_anomaly", "alert",
                                 "suspected_service", "suspected_feature", "trace_suspect",
                                 "active_fault"] + config.FEATURES)

    # ---------- faults ----------
    def active_fault(self):
        labels = []
        for svc in ("inventory", "payment"):
            try:
                f = self.client.get(f"{config.SERVICE_URLS[svc]}/admin/fault").json()
            except Exception:
                continue
            if f.get("delay_ms", 0) > 0:
                labels.append(f"{svc}_delay")
            if f.get("error_rate", 0) > 0:
                labels.append(f"{svc}_errors")
        return "+".join(labels) or "none"

    def log_event(self, kind, text):
        ev = {"time": time.time(), "kind": kind, "text": text}
        self.events.appendleft(ev)
        new = not FAULT_LOG.exists()
        with open(FAULT_LOG, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp", "kind", "text"])
            w.writerow([f"{ev['time']:.3f}", kind, text])

    # ---------- localization ----------
    def localize(self, per_feat):
        excess = np.maximum(0.0, per_feat - self.p99)
        fe = dict(zip(config.FEATURES, excess.tolist()))
        notes = []
        # Dependency adjustment: checkout latency/errors largely explained by a downstream
        # service deviating in the same metric family are down-weighted.
        for fam in ("latency_p95", "error_rate"):
            up = fe[f"checkout_{fam}"]
            if up <= 0:
                continue
            down_svc = max(config.DOWNSTREAM["checkout"], key=lambda s: fe[f"{s}_{fam}"])
            down = fe[f"{down_svc}_{fam}"]
            if down >= 0.25 * up:
                fe[f"checkout_{fam}"] = up * 0.25
                notes.append(f"checkout {fam.replace('_', ' ')} deviation is propagated from {down_svc} "
                             f"(downstream dependency) and was down-weighted")
        svc_scores = {s: sum(fe[f"{s}_{fam}"] for fam in config.FEATURE_FAMILIES) for s in config.SERVICES}
        if sum(svc_scores.values()) == 0:  # fall back to raw error if nothing exceeds healthy p99
            raw = dict(zip(config.FEATURES, per_feat.tolist()))
            svc_scores = {s: sum(raw[f"{s}_{fam}"] for fam in config.FEATURE_FAMILIES) for s in config.SERVICES}
            fe = raw
        total = sum(svc_scores.values()) or 1.0
        ranking = sorted(({"service": s, "score": v, "share": v / total} for s, v in svc_scores.items()),
                         key=lambda r: -r["score"])
        top_feats = sorted(({"feature": f, "error": float(per_feat[i]), "adjusted": fe[f],
                             "healthy_p99": float(self.p99[i])}
                            for i, f in enumerate(config.FEATURES)), key=lambda r: -r["adjusted"])[:6]
        return ranking, top_feats, notes

    def trace_evidence(self):
        spans = tr.fetch_spans(time.time() - 20, self.client)
        traces = tr.assemble(spans)
        cutoff = time.time() - 15
        recent = [t for t in traces if t["start"] >= cutoff]
        summ = tr.summarize(recent)
        base_self = self.trace_base.get("self_ms", {})
        base_err = self.trace_base.get("error_origin_rate", {})
        per_svc = []
        for s in config.SERVICES:
            cur = summ["self_ms"].get(s)
            b = base_self.get(s)
            ratio = (cur / b) if (cur is not None and b) else None
            per_svc.append({"service": s, "self_ms": cur, "baseline_self_ms": b, "self_ratio": ratio,
                            "error_origin_rate": summ["error_origin_rate"].get(s, 0.0),
                            "baseline_error_origin_rate": base_err.get(s, 0.0)})
        suspect, reason = None, None
        err_cand = max(per_svc, key=lambda p: p["error_origin_rate"] - p["baseline_error_origin_rate"])
        lat_cand = max(per_svc, key=lambda p: p["self_ratio"] or 0)
        if err_cand["error_origin_rate"] - err_cand["baseline_error_origin_rate"] > 0.05:
            suspect = err_cand["service"]
            reason = f"{err_cand['error_origin_rate'] * 100:.0f}% of recent traces have errors originating in {suspect}"
        elif (lat_cand["self_ratio"] or 0) > 2.0:
            suspect = lat_cand["service"]
            reason = (f"{suspect} self time {lat_cand['self_ms']:.0f} ms vs healthy "
                      f"{lat_cand['baseline_self_ms']:.0f} ms ({lat_cand['self_ratio']:.1f}x)")
        # pick an evidence trace: slowest or erroring recent trace
        evidence = None
        if recent:
            errs = [t for t in recent if t["error"]]
            evidence = (errs[-1] if errs and (suspect == err_cand["service"]) else max(recent, key=lambda t: t["duration_ms"]))
        self.recent_traces = [{k: t[k] for k in ("trace_id", "start", "duration_ms", "error", "self_ms", "error_origin")}
                              for t in recent[-12:]][::-1]
        return {"n_traces": summ["n"], "per_service": per_svc, "suspect": suspect, "reason": reason,
                "evidence_trace": evidence}

    # ---------- main loop ----------
    def tick(self):
        feats, status = self.fb.step()
        unreachable = [s for s, st in status.items() if st == "unreachable"]
        for k in config.FEATURES:  # fill missing values with last known (never silent zeros)
            if feats.get(k) is None:
                feats[k] = self.last_values.get(k)
            else:
                self.last_values[k] = feats[k]
        fault = self.active_fault()
        now = time.time()
        if any(v is None for v in feats.values()):
            with self.lock:
                self.state = {"status": "warming_up", "message": "Waiting for complete telemetry from all services...",
                              "service_status": status, "active_fault": fault}
            return
        self.window.append([feats[k] for k in config.FEATURES])
        evidence = self.trace_evidence()
        if len(self.window) < config.SEQ_LEN:
            with self.lock:
                self.state = {"status": "warming_up",
                              "message": f"Filling the 12-step window ({len(self.window)}/{config.SEQ_LEN})...",
                              "service_status": status, "active_fault": fault, "features": feats,
                              "traces": evidence, "recent_traces": self.recent_traces}
                self.history.append({"t": now, "score": None, "threshold": self.threshold, "alert": False,
                                     "fault": fault, "features": feats})
            return

        X = self.scaler.transform(np.array(self.window, dtype=np.float64))[None, :, :]
        score_arr, per_feat_arr = reconstruction_errors(self.model, X)
        score, per_feat = float(score_arr[0]), per_feat_arr[0]
        raw = score > self.threshold
        self.consecutive = self.consecutive + 1 if raw else 0
        alert = self.consecutive >= 2 or bool(unreachable)
        ranking, top_feats, notes = self.localize(per_feat)
        suspected = unreachable[0] if unreachable else ranking[0]["service"]
        suspected_feat = top_feats[0]["feature"]
        if alert and self.alert_started is None:
            self.alert_started = now
            self.log_event("alert", f"ANOMALY detected - suspected {suspected} ({suspected_feat}), score {score:.2f}")
        elif not alert and self.alert_started is not None:
            self.log_event("recovered", f"Back to normal after {now - self.alert_started:.0f} s")
            self.alert_started = None

        G_SCORE.set(score)
        G_FLAG.set(1 if alert else 0)
        for r in ranking:
            G_SERVICE.labels(r["service"]).set(r["score"])
            G_SUSPECT.labels(r["service"]).set(1 if (alert and r["service"] == suspected) else 0)
        for i, f in enumerate(config.FEATURES):
            G_FEATURE.labels(f).set(float(per_feat[i]))

        agree = (evidence["suspect"] == suspected) if evidence["suspect"] else None
        self.log_w.writerow([f"{now:.3f}", f"{score:.6f}", f"{self.threshold:.6f}", int(raw), int(alert),
                             suspected if alert else "", suspected_feat if alert else "",
                             evidence["suspect"] or "", fault] + [f"{feats[k]:.6f}" for k in config.FEATURES])
        self.log_f.flush()
        with self.lock:
            self.history.append({"t": now, "score": score, "threshold": self.threshold, "alert": alert,
                                 "fault": fault, "features": feats})
            self.state = {
                "status": "anomaly" if alert else ("suspicious" if raw else "healthy"),
                "message": ("Service unreachable: " + ", ".join(unreachable)) if unreachable else None,
                "score": score, "threshold": self.threshold, "consecutive": self.consecutive,
                "suspected_service": suspected, "suspected_feature": suspected_feat,
                "ranking": ranking, "top_features": top_feats, "notes": notes,
                "traces": evidence, "trace_agrees": agree, "recent_traces": self.recent_traces,
                "service_status": status, "active_fault": fault, "features": feats,
                "alert_since": self.alert_started,
            }

    def run(self):
        next_t = time.time()
        while True:
            next_t = sleep_until_next_tick(next_t)
            try:
                self.tick()
            except Exception as e:  # keep the loop alive during the demo
                print(f"[detector] tick error: {e!r}", flush=True)


# ---------------- web app ----------------
detector: Detector | None = None


@asynccontextmanager
async def lifespan(_app):
    global detector
    detector = Detector()
    threading.Thread(target=detector.run, daemon=True).start()
    print(f"[detector] threshold={detector.threshold:.4f}; dashboard on http://127.0.0.1:{config.DASHBOARD_PORT}", flush=True)
    yield


app = FastAPI(title="Anomaly detector", lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(DASHBOARD_DIR / "index.html")


@app.get("/api/state")
def api_state():
    with detector.lock:
        return {"state": detector.state, "history": list(detector.history), "events": list(detector.events),
                "features": config.FEATURES, "services": config.SERVICES, "jaeger_url": config.JAEGER_UI_URL,
                "model": {k: detector.meta[k] for k in ("threshold", "rows", "trained_at", "epochs_run",
                                                         "val_score_mean", "val_score_max")}}


FAULTS = {
    "inventory_delay": ("inventory", {"delay_ms": 1500}, "Injected 1.5 s latency into inventory"),
    "payment_errors": ("payment", {"error_rate": 0.3}, "Injected 30% error rate into payment"),
}


@app.post("/api/fault/{name}")
async def api_fault(name: str, request: Request):
    if name == "reset":
        for svc in ("inventory", "payment"):
            detector.client.post(f"{config.SERVICE_URLS[svc]}/admin/reset")
        detector.log_event("fault_cleared", "All faults removed")
        return {"ok": True}
    if name not in FAULTS:
        return JSONResponse({"error": "unknown fault"}, status_code=404)
    svc, body, text = FAULTS[name]
    try:
        override = await request.json()
        body = {**body, **(override or {})}
    except Exception:
        pass
    detector.client.post(f"{config.SERVICE_URLS[svc]}/admin/fault", json=body)
    detector.log_event("fault_injected", text if body == FAULTS[name][1] else f"{svc} fault {body}")
    return {"ok": True, "service": svc, "fault": body}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.DASHBOARD_PORT, log_level="warning")
