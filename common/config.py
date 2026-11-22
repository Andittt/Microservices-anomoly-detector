"""Central configuration. Every value can be overridden with an environment
variable so the same code runs locally (Python-only mode) and in Docker."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
MODEL_DIR = Path(os.getenv("MODEL_DIR", ROOT / "model_artifacts"))
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", ROOT / "results"))
for _d in (DATA_DIR, MODEL_DIR, RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

HOST = os.getenv("BIND_HOST", "127.0.0.1")

CHECKOUT_PORT = int(os.getenv("CHECKOUT_PORT", 8001))
INVENTORY_PORT = int(os.getenv("INVENTORY_PORT", 8002))
PAYMENT_PORT = int(os.getenv("PAYMENT_PORT", 8003))
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", 8080))

CHECKOUT_URL = os.getenv("CHECKOUT_URL", f"http://127.0.0.1:{CHECKOUT_PORT}")
INVENTORY_URL = os.getenv("INVENTORY_URL", f"http://127.0.0.1:{INVENTORY_PORT}")
PAYMENT_URL = os.getenv("PAYMENT_URL", f"http://127.0.0.1:{PAYMENT_PORT}")

SERVICE_URLS = {
    "checkout": CHECKOUT_URL,
    "inventory": INVENTORY_URL,
    "payment": PAYMENT_URL,
}
SERVICES = ["checkout", "inventory", "payment"]
# Call graph: checkout -> inventory, checkout -> payment
DOWNSTREAM = {"checkout": ["inventory", "payment"], "inventory": [], "payment": []}

# ---- Telemetry / feature schema (Milestone 1, section 04) ----
SAMPLE_INTERVAL = float(os.getenv("SAMPLE_INTERVAL", 5.0))  # seconds between feature rows
RATE_WINDOW_TICKS = 2          # rates/p95 computed over the last 2 ticks (~10 s) for stability
SEQ_LEN = 12                   # 12 samples ~ 60 s
FEATURE_FAMILIES = ["latency_p95", "error_rate", "rps", "cpu", "memory_mb"]
FEATURES = [f"{s}_{f}" for s in SERVICES for f in FEATURE_FAMILIES]  # 15 features

# Minimum std used by the scaler per family, so a metric that is (almost) constant
# during healthy training (e.g. error rate = 0) does not explode or vanish.
# CPU and memory are context signals (Milestone 1: "included as context rather than assumed causes");
# process RSS jumps by tens of MB on some OSes for reasons unrelated to load, so they get wide floors.
STD_FLOOR = {"latency_p95": 0.02, "error_rate": 0.02, "rps": 1.0, "cpu": 5.0, "memory_mb": 25.0}

# OpenTelemetry: if set (Docker mode), spans are also exported to an OTLP collector / Jaeger.
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
JAEGER_UI_URL = os.getenv("JAEGER_UI_URL", "")
