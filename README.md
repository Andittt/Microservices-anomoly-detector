# Dynamic Microservice Anomaly Detection & Root-Cause Isolation

CSET 464 project (Milestone 2 implementation). A small microservice system (checkout → inventory, payment)
is observed through Prometheus-format metrics and OpenTelemetry traces. An **LSTM Autoencoder** trained only on
healthy telemetry detects anomalies, ranks the most likely faulty **service** and **metric**, and checks the
ranking against **trace evidence**. A live dashboard shows everything and lets you inject faults.

This is the **Python-only mode**: no Docker needed. It runs on Windows, macOS and Linux.

---

## Quick start (Windows)

> **Setting this up on a new laptop? Follow [SETUP_GUIDE_WINDOWS.md](SETUP_GUIDE_WINDOWS.md)** for full step-by-step instructions, test checklist and troubleshooting.

Requirements: **Python 3.10 – 3.13** from python.org (tick *"Add python.exe to PATH"* when installing),
internet access for the first install, and ports 8001–8003 and 8080 free.

Open **Command Prompt** in this folder and run:

```bat
run.bat setup
```

The first run installs the packages, which takes a few minutes. After that it:
1. starts the 3 services and the traffic generator,
2. collects **15 minutes** of healthy telemetry (`data/healthy_baseline.csv`),
3. trains the model and calibrates the threshold (`model_artifacts/`, `results/training_report.md`).

Then start the demo:

```bat
run.bat demo
```

The dashboard opens at **http://127.0.0.1:8080**. Wait about 60 s for the first window to fill. Press **Ctrl+C** to stop everything.

> **Always run `run.bat setup` once on the laptop used for the demo.** CPU, memory and latency differ between
> machines, so a model trained on another laptop may raise false alerts. For a quicker baseline use
> `run.bat setup --minutes 10`.

macOS / Linux: run the same commands with `./run.sh` instead of `run.bat`.

## Live demonstration script

1. `run.bat demo` and wait until the status says **HEALTHY**. Show the stable metrics and the score below the red threshold line.
2. Click **Inject inventory delay (1.5 s)**. Within about 10–20 s the status turns **ANOMALY DETECTED**:
   - inventory and checkout latency rise (checkout calls inventory),
   - the root-cause panel ranks **inventory** first, and notes that checkout's latency is propagated from inventory,
   - **Trace evidence** shows the inventory self time going from ~50 ms to ~1500 ms, and the waterfall shows the slow inventory span inside a checkout trace.
3. Click **Clear faults** and wait about 60–70 s for the window to recover to **HEALTHY**.
4. Click **Inject payment errors (30%)**. Payment and checkout error rates rise. The suspected service is **payment**, and the traces show the errors originating in payment.
5. Clear the faults and show `results/evaluation.md` for the measured results.

## Measured evaluation

```bat
run.bat evaluate
```

This takes about 11 minutes. It runs healthy → inventory delay → recovery → payment errors → recovery automatically,
then writes `results/evaluation.md` with:
- detection delay,
- healthy false-positive rate,
- detection rate,
- localization accuracy,
- trace agreement.

## Project structure

| Path | What it is |
|---|---|
| `services/checkout.py`, `inventory.py`, `payment.py` | The three FastAPI microservices |
| `services/telemetry.py` | Prometheus metrics, OpenTelemetry tracing, fault-injection admin routes |
| `traffic/generator.py` | Open-loop traffic generator (6–12 req/s, slowly varying) |
| `detector/features.py` | Builds the 15-feature vector (p95 latency, error rate, rps, CPU, memory × 3 services) |
| `detector/collect.py` | Healthy baseline collection with data-quality checks |
| `detector/model.py` | LSTM Autoencoder, floored StandardScaler, windowing, scoring |
| `detector/train.py` | Chronological split, training, threshold calibration |
| `detector/traces.py` | Trace assembly, per-service self time, error origin |
| `detector/app.py` | Live detector, localization, trace corroboration, dashboard API, `/metrics` |
| `dashboard/index.html` | Dashboard with the 7 planned panels |
| `evaluation/evaluate.py` | Controlled fault experiments and metrics |
| `run.py`, `run.bat`, `run.sh` | Launchers |

## How it works

- **Features (15).** For each service, every 5 s: p95 latency, 5xx error rate and request rate are computed from
  Prometheus counter and histogram deltas, the same way PromQL `rate()` and `histogram_quantile()` work. Process CPU % and
  memory are also recorded. Rows with missing values are rejected and never silently set to zero.
- **Model.** An LSTM encoder turns a 12 × 15 window into a 16-dimensional latent vector, and an LSTM decoder reconstructs the window.
  The model is trained only on healthy windows. It uses a chronological train/validation split, and the scaler is fitted on the training part only.
- **Threshold.** `max(mean + 4·std, 1.5 · max)` of the validation scores. An alert needs **2 consecutive** windows above it.
- **Localization.** Each feature's error over the 12-step window is compared with its healthy 99th percentile, and the
  excess is summed per service. A dependency rule down-weights checkout latency or errors when a downstream service deviates in the same metric.
- **Trace evidence.** Per-service *self time* is span duration minus time spent waiting on child calls. Together with the
  error-origin service, it gives an independent second opinion, shown as "agrees" or "points elsewhere".

The output is a ranked hypothesis, not proof of causality.

## Troubleshooting

- **"port already in use"**: another program is using port 8001–8003 or 8080. Close it, or restart the laptop.
- **Dashboard says DETECTOR OFFLINE**: check `logs/detector.log`.
- **False alerts while healthy**: re-run `run.bat setup` on this machine.
- **Logs** for every process are in the `logs/` folder.
