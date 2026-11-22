"""Shared instrumentation for the three microservices.

* Prometheus metrics: request counter, latency histogram, process CPU / memory.
* OpenTelemetry tracing: FastAPI server spans + httpx client spans, so trace
  context propagates checkout -> inventory / payment automatically.
  Finished spans are kept in memory (served at /traces) and, when
  OTEL_EXPORTER_OTLP_ENDPOINT is set (Docker mode), also exported to Jaeger.
* Fault-injection admin endpoints used by the controlled experiments.
"""
import random
import threading
import time
from collections import deque

import psutil
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import (CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram,
                               generate_latest)
from prometheus_client.core import GaugeMetricFamily

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (BatchSpanProcessor, SimpleSpanProcessor,
                                            SpanExporter, SpanExportResult)
from opentelemetry.trace import StatusCode

from common import config

REQUESTS = Counter("app_requests_total", "HTTP requests handled",
                   ["service", "endpoint", "status_class"])
LATENCY = Histogram("app_request_duration_seconds", "HTTP request duration",
                    ["service", "endpoint"],
                    buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5,
                             0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0))


class ProcessCollector:
    """Process CPU % and memory, collected at scrape time with psutil (works on Windows/macOS/Linux)."""

    def __init__(self, service):
        self.service = service
        self.proc = psutil.Process()
        self.proc.cpu_percent(None)

    def collect(self):
        cpu = GaugeMetricFamily("app_process_cpu_percent", "Process CPU percent", labels=["service"])
        cpu.add_metric([self.service], self.proc.cpu_percent(None))
        yield cpu
        mem = GaugeMetricFamily("app_process_memory_bytes", "Process RSS memory", labels=["service"])
        mem.add_metric([self.service], float(self.proc.memory_info().rss))
        yield mem


class InMemorySpanStore(SpanExporter):
    """Keeps the most recent finished spans so the detector/dashboard can read them."""

    def __init__(self, service, maxlen=3000):
        self.service = service
        self.spans = deque(maxlen=maxlen)
        self.lock = threading.Lock()

    def export(self, spans):
        with self.lock:
            for s in spans:
                attrs = dict(s.attributes or {})
                # Skip ASGI internal send/receive spans; keep server, client and work spans
                if s.name.endswith((" http send", " http receive")):
                    continue
                name = s.name
                if s.kind.name == "CLIENT":
                    url = str(attrs.get("http.url") or attrs.get("url.full") or "")
                    for svc, base in config.SERVICE_URLS.items():
                        if url.startswith(base):
                            name = f"call {svc} {url[len(base):]}"
                self.spans.append({
                    "trace_id": format(s.context.trace_id, "032x"),
                    "span_id": format(s.context.span_id, "016x"),
                    "parent_id": format(s.parent.span_id, "016x") if s.parent else None,
                    "name": name,
                    "service": self.service,
                    "kind": s.kind.name,
                    "start": s.start_time / 1e9,
                    "end": s.end_time / 1e9,
                    "duration_ms": (s.end_time - s.start_time) / 1e6,
                    "error": s.status.status_code == StatusCode.ERROR,
                    "status_code": attrs.get("http.status_code", attrs.get("http.response.status_code")),
                    "fault": attrs.get("fault.injected"),
                })
        return SpanExportResult.SUCCESS

    def since(self, ts):
        with self.lock:
            return [s for s in self.spans if s["end"] >= ts]


class FaultState:
    def __init__(self):
        self.delay_ms = 0.0
        self.error_rate = 0.0

    def as_dict(self):
        return {"delay_ms": self.delay_ms, "error_rate": self.error_rate}


_httpx_instrumented = False


def create_service(name: str) -> tuple[FastAPI, FaultState, trace.Tracer]:
    global _httpx_instrumented
    app = FastAPI(title=f"{name} service")
    faults = FaultState()

    # ---- tracing ----
    provider = TracerProvider(resource=Resource.create({"service.name": name}))
    store = InMemorySpanStore(name)
    provider.add_span_processor(SimpleSpanProcessor(store))
    if config.OTLP_ENDPOINT:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=config.OTLP_ENDPOINT, insecure=True)))
        except Exception as e:  # exporter optional in Python-only mode
            print(f"[{name}] OTLP exporter not available: {e}")
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(name)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider,
                                       excluded_urls="metrics,traces,health,admin")
    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        _httpx_instrumented = True

    # ---- metrics ----
    REGISTRY.register(ProcessCollector(name))

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        path = request.url.path
        if path in ("/metrics", "/traces", "/health") or path.startswith("/admin"):
            return await call_next(request)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            LATENCY.labels(name, path).observe(time.perf_counter() - start)
            REQUESTS.labels(name, path, f"{status // 100}xx").inc()

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/traces")
    def traces(since: float = 0.0):
        return store.since(since)

    @app.get("/health")
    def health():
        return {"service": name, "status": "ok", "faults": faults.as_dict()}

    # ---- fault injection (local admin routes) ----
    @app.get("/admin/fault")
    def get_fault():
        return faults.as_dict()

    @app.post("/admin/fault")
    async def set_fault(request: Request):
        body = await request.json()
        faults.delay_ms = float(body.get("delay_ms", faults.delay_ms))
        faults.error_rate = float(body.get("error_rate", faults.error_rate))
        print(f"[{name}] fault set -> {faults.as_dict()}", flush=True)
        return faults.as_dict()

    @app.post("/admin/reset")
    def reset_fault():
        faults.delay_ms = 0.0
        faults.error_rate = 0.0
        print(f"[{name}] faults cleared", flush=True)
        return faults.as_dict()

    return app, faults, tracer


async def apply_faults(faults: FaultState, span) -> JSONResponse | None:
    """Apply injected delay / error. Returns an error response if one should be sent."""
    import asyncio
    if faults.delay_ms > 0:
        span.set_attribute("fault.injected", f"delay_{int(faults.delay_ms)}ms")
        await asyncio.sleep(faults.delay_ms / 1000.0)
    if faults.error_rate > 0 and random.random() < faults.error_rate:
        span.set_attribute("fault.injected", f"error_rate_{faults.error_rate}")
        span.set_status(StatusCode.ERROR, "injected failure")
        return JSONResponse({"error": "injected failure"}, status_code=500)
    return None


def busy_work(ms: float):
    """Small amount of real CPU work so CPU metrics move with load."""
    end = time.perf_counter() + ms / 1000.0
    x = 0
    while time.perf_counter() < end:
        x += 1
    return x
