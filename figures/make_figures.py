"""Generates the report figures (PNG, dark theme matching the milestone report).

  python figures/make_figures.py

Diagrams: architecture, pipeline, roadmap.  Charts use REAL measured data from the
last evaluation run (data/live_log.csv + results/evaluation.json) and training history.
"""
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import config  # noqa: E402

OUT = ROOT / "figures"
DPI = 220

# ---- theme (matches the report's dark pages) ----
BG = "#0b0c0f"
PANEL = "#151922"
PANEL2 = "#1c2230"
BORDER = "#2c3445"
TEXT = "#e6e9ef"
MUTED = "#9aa3b5"
FAINT = "#5d6577"
GRID = "#222836"
ALERT = "#e5484d"          # reserved status colour: threshold / fault / alerts
SVC = {"checkout": "#4f8cff", "inventory": "#c97d0a", "payment": "#a46ef0"}  # validated categorical order
NEUTRAL = "#7d8799"

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": TEXT, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": BORDER, "font.family": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "regular",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "legend.frameon": False, "legend.labelcolor": MUTED,
})


def save(fig, name):
    path = OUT / name
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("wrote", path.relative_to(ROOT))


# =====================================================================
# Diagram helpers
# =====================================================================
def box(ax, x, y, w, h, title, sub=None, edge=BORDER, fill=PANEL, title_color=TEXT, fs=10.5, accent=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2",
                                linewidth=1.2, edgecolor=edge, facecolor=fill, zorder=2))
    if accent:
        ax.add_patch(FancyBboxPatch((x, y), 0.9, h, boxstyle="round,pad=0,rounding_size=0.45",
                                    linewidth=0, facecolor=accent, zorder=3))
    cy = y + h / 2
    if sub:
        ax.text(x + w / 2, cy + h * 0.17, title, ha="center", va="center", fontsize=fs,
                color=title_color, weight="bold", zorder=4)
        ax.text(x + w / 2, cy - h * 0.2, sub, ha="center", va="center", fontsize=fs - 2.3,
                color=MUTED, zorder=4, linespacing=1.35)
    else:
        ax.text(x + w / 2, cy, title, ha="center", va="center", fontsize=fs, color=title_color,
                weight="bold", zorder=4)


def arrow(ax, p1, p2, color=NEUTRAL, style="-|>", ls="-", lw=1.4, rad=0.0, label=None, lpos=0.5,
          loff=(0, 1.2), lcolor=None):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=11, color=color, lw=lw,
                                 linestyle=ls, connectionstyle=f"arc3,rad={rad}", zorder=1,
                                 shrinkA=2, shrinkB=2))
    if label:
        lx = p1[0] + (p2[0] - p1[0]) * lpos + loff[0]
        ly = p1[1] + (p2[1] - p1[1]) * lpos + loff[1]
        ax.text(lx, ly, label, ha="center", va="center", fontsize=7.6, color=lcolor or MUTED, zorder=5,
                bbox=dict(boxstyle="round,pad=0.2", fc=BG, ec="none"))


def band(ax, y, h, label, bottom=False):
    ax.add_patch(FancyBboxPatch((0, y), 100, h, boxstyle="round,pad=0,rounding_size=1.5",
                                linewidth=0.8, edgecolor=GRID, facecolor="#0f1218", zorder=0))
    ax.text(1.5, (y + 1.2) if bottom else (y + h - 1.4), label.upper(), fontsize=7.6, color=FAINT,
            va="bottom" if bottom else "top", ha="left", weight="bold", zorder=1)


def canvas(w_in, h_in, xmax=100, ymax=60):
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, ymax)
    ax.axis("off")
    ax.set_aspect("auto")
    return fig, ax


# =====================================================================
# Figure 1 - architecture
# =====================================================================
def fig_architecture():
    fig, ax = canvas(11, 7.6, 100, 76)
    band(ax, 52, 23, "Application layer  (FastAPI services)")
    band(ax, 36, 14.5, "Observability layer")
    band(ax, 18, 16.5, "Detection layer")
    band(ax, 1, 15.5, "Presentation layer")

    # application
    box(ax, 4, 56, 17, 10, "Traffic generator", "open-loop, 6-12 req/s")
    box(ax, 30, 56, 19, 10, "Checkout API", ":8001  entry point", accent=SVC["checkout"])
    box(ax, 58, 63, 19, 9, "Inventory API", ":8002  reserve stock", accent=SVC["inventory"])
    box(ax, 58, 53.5, 19, 9, "Payment API", ":8003  charge card", accent=SVC["payment"])
    box(ax, 83, 58, 15, 10, "Fault injection", "/admin/fault\n+1.5 s delay | 30% 5xx", edge="#5a2a2d")
    arrow(ax, (21, 61), (30, 61), label="POST /checkout", loff=(0, 1.6))
    arrow(ax, (49, 62.5), (58, 67.5), label="reserve", loff=(-1.2, 1.6))
    arrow(ax, (49, 59.5), (58, 58), label="charge", loff=(0, -1.6))
    arrow(ax, (83, 64.5), (77, 67), color=ALERT, ls="--", lw=1.1)
    arrow(ax, (83, 61.5), (77, 58), color=ALERT, ls="--", lw=1.1)

    # observability
    box(ax, 3, 38, 44, 9.5, "Prometheus-format metrics  (/metrics)",
        "request counter | latency histogram | process CPU % | memory\nscraped every 5 s (Prometheus server in Docker mode)")
    box(ax, 54, 38, 40, 9.5, "OpenTelemetry tracing  (/traces)",
        "FastAPI + httpx spans, W3C trace context propagated\nexported to Collector -> Jaeger in Docker mode")
    arrow(ax, (25, 52.2), (25, 47.6), label="metrics from all 3 services", lpos=0.5, loff=(9, 0))
    arrow(ax, (74, 52.2), (74, 47.6), label="spans from all 3 services", lpos=0.5, loff=(-8.5, 0))

    # detection
    box(ax, 4, 21, 25, 10, "Feature builder", "15 features = 5 metrics x 3 services\nrate() / histogram_quantile() logic")
    box(ax, 36, 21, 25, 10, "LSTM Autoencoder", "12-step window (60 s)\nscore vs calibrated threshold")
    box(ax, 68, 21, 28, 10, "Root-cause localization", "per-feature error ranking\n+ dependency rule + trace self-time")
    arrow(ax, (25, 38), (17, 31))
    arrow(ax, (29, 26), (36, 26))
    arrow(ax, (61, 26), (68, 26))
    arrow(ax, (78, 38), (82, 31), label="trace evidence", loff=(5.5, 0))

    # presentation
    box(ax, 10, 4, 34, 9.5, "Live dashboard  (:8080)",
        "score + threshold | suspected service | traces\nlatency, errors, traffic, CPU, memory | fault buttons")
    box(ax, 56, 4, 34, 9.5, "Grafana + Jaeger UI",
        "Docker mode: same detector metrics via Prometheus\n(anomaly_score, anomaly_flag, service ranking)")
    arrow(ax, (75, 21), (32, 13.5), label="state API + /metrics", lpos=0.55, loff=(0, 1.3))
    arrow(ax, (82, 21), (73, 13.5))

    ax.text(100, -1.5, "Azure mapping (future option): services -> Azure Container Apps | telemetry -> Azure Monitor / "
            "Application Insights | dashboards -> Azure Managed Grafana", ha="right", va="top", fontsize=7.8, color=FAINT)
    save(fig, "fig1_architecture.png")


# =====================================================================
# Figure 2 - telemetry-to-decision pipeline
# =====================================================================
def fig_pipeline():
    fig, ax = canvas(11, 4.6, 100, 46)
    band(ax, 25, 20, "Training  (offline, healthy traffic only)")
    band(ax, 1, 21, "Inference  (live, every 5 s)", bottom=True)

    tw, th, ty = 14.5, 10, 29
    train = [("Collect", "15-min healthy CSV\nincomplete rows rejected"),
             ("Split", "chronological\n75% train / 25% val"),
             ("Scale", "StandardScaler on\ntrain only (floored)"),
             ("Train", "LSTM-AE on 12-step\nwindows, early stop"),
             ("Calibrate", "threshold from\nheld-out healthy"),
             ("Artifacts", "model.pt, scaler,\nmetadata.json")]
    xs = [2 + i * 16.4 for i in range(6)]
    for (t, s), x in zip(train, xs):
        box(ax, x, ty, tw, th, t, s, fs=10)
    for x in xs[:-1]:
        arrow(ax, (x + tw, ty + th / 2), (x + 16.4, ty + th / 2))

    iy = 5
    infer = [("Generate", "traffic + optional\ninjected fault"),
             ("Observe", "scrape metrics,\ncollect spans"),
             ("Window", "latest 12 x 15\nfeature matrix"),
             ("Reconstruct", "score > threshold,\n2 in a row = alert"),
             ("Localize", "rank service + metric,\ncheck with traces"),
             ("Visualize", "dashboard, event\nlog, /metrics")]
    for i, ((t, s), x) in enumerate(zip(infer, xs)):
        box(ax, x, iy, tw, th, t, s, fs=10, accent=ALERT if t == "Reconstruct" else None)
    for x in xs[:-1]:
        arrow(ax, (x + tw, iy + th / 2), (x + 16.4, iy + th / 2))
    # artifacts feed reconstruct; observe feeds collect
    arrow(ax, (xs[5] + tw / 2, ty), (xs[3] + tw / 2 + 2, iy + th), ls="--", rad=-0.15, label="load model", lpos=0.5,
          loff=(0, 2.2))
    arrow(ax, (xs[1] + tw / 2, iy + th), (xs[0] + tw / 2, ty), ls="--", label="healthy only", lpos=0.5, loff=(1.5, 0))
    save(fig, "fig2_pipeline.png")


# =====================================================================
# Data for measured charts
# =====================================================================
def load_eval():
    ev = json.loads((config.RESULTS_DIR / "evaluation.json").read_text(encoding="utf-8"))
    rows = []
    with open(config.DATA_DIR / "live_log.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    t0 = ev["phases"][0]["start"]
    rows = [r for r in rows if ev["phases"][0]["start"] - 1 <= float(r["timestamp"]) <= ev["phases"][-1]["end"] + 1]
    return ev, rows, t0


def shade_faults(ax, ev, t0, label=True, ymax_frac=0.04):
    for p in ev["phases"]:
        if p["kind"] != "fault":
            continue
        a, b = (p["start"] - t0) / 60, (p["end"] - t0) / 60
        ax.axvspan(a, b, color=ALERT, alpha=0.10, lw=0, zorder=0)
        if label:
            ax.text((a + b) / 2, ymax_frac, p["name"], transform=ax.get_xaxis_transform(), ha="center", va="bottom",
                    fontsize=8.5, color=TEXT)


def direct_label(ax, x, y, text, color):
    ax.annotate(text, (x, y), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8.5,
                color=TEXT, annotation_clip=False)
    ax.plot([x], [y], "o", ms=5, color=color, mec=BG, mew=1.5, zorder=5)


# =====================================================================
# Figure 3 - latency during the inventory delay (measured)
# =====================================================================
def fig_latency(ev, rows, t0):
    p = next(p for p in ev["phases"] if p["true_service"] == "inventory")
    lo, hi = p["start"] - 90, p["end"] + 120
    rr = [r for r in rows if lo <= float(r["timestamp"]) <= hi]
    x = [(float(r["timestamp"]) - p["start"]) for r in rr]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.axvspan(0, p["end"] - p["start"], color=ALERT, alpha=0.10, lw=0)
    ax.text((p["end"] - p["start"]) / 2, 0.5, "inventory +1.5 s injected\n(checkout p95 overlaps inventory:\nit waits on the inventory call)",
            transform=ax.get_xaxis_transform(), ha="center", va="center", fontsize=8.5, color=TEXT, linespacing=1.4)
    for s, lw, z in (("payment", 2, 2), ("inventory", 3.2, 2), ("checkout", 1.6, 3)):
        y = [float(r[f"{s}_latency_p95"]) * 1000 for r in rr]
        ax.plot(x, y, color=SVC[s], lw=lw, label=s, solid_capstyle="round", zorder=z)
    h, l = ax.get_legend_handles_labels()
    order = [l.index(s) for s in config.SERVICES]
    ax.set_xlabel("seconds relative to fault injection")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_ylim(0, None)
    ax.set_xlim(x[0], x[-1])
    ax.legend([h[i] for i in order], config.SERVICES, loc="upper left", ncol=3, bbox_to_anchor=(0, 1.13))
    ax.set_title("Measured p95 latency per service during a controlled inventory delay", loc="left", pad=28)
    save(fig, "fig3_latency_inventory_fault.png")


# =====================================================================
# Figure 4 - roadmap Gantt
# =====================================================================
def fig_gantt():
    start = date(2026, 10, 19)
    phases = [("Setup and APIs", 0, 1), ("Metrics", 1, 1), ("Tracing", 2, 1), ("Baseline", 3, 1),
              ("ML", 4, 1), ("Dashboard + chaos", 5, 1), ("Evaluation + report", 6, 1)]
    optional = [("Docker / Grafana / Jaeger stack", 5, 2), ("Azure deployment (optional)", 6, 1)]
    fig, ax = plt.subplots(figsize=(10, 4.0))
    ax.grid(axis="y", visible=False)
    labels = []
    allp = phases + optional
    for i, (name, wk, dur) in enumerate(allp):
        y = len(allp) - 1 - i
        s = start + timedelta(weeks=wk)
        is_opt = (name, wk, dur) in optional
        ax.barh(y, timedelta(weeks=dur).days, left=mdates.date2num(s), height=0.56,
                color="none" if is_opt else SVC["checkout"], edgecolor=SVC["checkout"],
                hatch="////" if is_opt else None, lw=1.2)
        labels.append(name)
    ax.set_yticks(range(len(allp)))
    ax.set_yticklabels(labels[::-1])
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.set_xlim(mdates.date2num(start - timedelta(days=2)), mdates.date2num(start + timedelta(weeks=7.6)))
    ax.set_title("Planned implementation roadmap: 7 weeks from 19 Oct 2026 (hatched = optional extensions)",
                 loc="left", pad=12)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    save(fig, "fig4_roadmap_gantt.png")


# =====================================================================
# Figure 5 - anomaly score vs threshold (measured)
# =====================================================================
def fig_score(ev, rows, t0):
    thr = float(rows[0]["threshold"])
    x = [(float(r["timestamp"]) - t0) / 60 for r in rows]
    y = [float(r["score"]) for r in rows]
    alerts = [(xi, yi) for xi, yi, r in zip(x, y, rows) if r["alert"] == "1"]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    shade_faults(ax, ev, t0)
    ax.plot(x, y, color=TEXT, lw=2, label="anomaly score", zorder=3)
    ax.axhline(thr, color=ALERT, lw=1.5, ls=(0, (6, 4)), label=f"calibrated threshold ({thr:.3f})", zorder=2)
    if alerts:
        ax.plot(*zip(*alerts), "o", ms=4.5, color=ALERT, mec=BG, mew=1, label="confirmed alert", zorder=4)
    ax.set_yscale("log")
    ax.set_xlabel("minutes since start of evaluation run")
    ax.set_ylabel("reconstruction error (log scale)")
    ax.set_xlim(x[0], x[-1])
    ax.legend(loc="upper left", ncol=3, bbox_to_anchor=(0, 1.13))
    ax.set_title("Measured anomaly score across the controlled experiment", loc="left", pad=28)
    save(fig, "fig5_anomaly_score.png")


# =====================================================================
# Figure 6 - error rate during payment errors (measured)
# =====================================================================
def fig_errors(ev, rows, t0):
    p = next(p for p in ev["phases"] if p["true_service"] == "payment")
    lo, hi = p["start"] - 90, p["end"] + 120
    rr = [r for r in rows if lo <= float(r["timestamp"]) <= hi]
    x = [(float(r["timestamp"]) - p["start"]) for r in rr]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.axvspan(0, p["end"] - p["start"], color=ALERT, alpha=0.10, lw=0)
    ax.text((p["end"] - p["start"]) / 2, 0.22, "payment 30% errors injected\ncheckout returns 502 when payment fails,\nso its line overlaps payment;\ninventory stays at 0%",
            transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=8.5, color=TEXT, linespacing=1.4)
    ends = []
    for s in config.SERVICES:
        y = [float(r[f"{s}_error_rate"]) * 100 for r in rr]
        ax.plot(x, y, color=SVC[s], lw=2, label=s)
        ends.append((s, y))
    ax.set_xlabel("seconds relative to fault injection")
    ax.set_ylabel("5xx error rate (%)")
    ax.set_ylim(0, 45)
    ax.set_xlim(x[0], x[-1])
    ax.legend(loc="upper left", ncol=3, bbox_to_anchor=(0, 1.13))
    ax.set_title("Measured server error rate per service during a controlled payment fault", loc="left", pad=28)
    save(fig, "fig6_error_rate_payment_fault.png")


# =====================================================================
# Figure 7 - training curve
# =====================================================================
def fig_training():
    hist = json.loads((config.RESULTS_DIR / "training_history.json").read_text(encoding="utf-8"))
    meta = json.loads((config.MODEL_DIR / "metadata.json").read_text(encoding="utf-8"))
    ep = [h["epoch"] for h in hist]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(ep, [h["train_loss"] for h in hist], color=SVC["checkout"], lw=2, label="training windows")
    ax.plot(ep, [h["val_loss"] for h in hist], color=SVC["inventory"], lw=2, label="held-out validation windows")
    ax.axhline(meta["threshold"], color=ALERT, lw=1.5, ls=(0, (6, 4)),
               label=f"anomaly threshold ({meta['threshold']:.3f})")
    ax.set_yscale("log")
    ax.set_xlabel("epoch")
    ax.set_ylabel("reconstruction MSE (log)")
    ax.legend(loc="lower left")
    ax.set_title(f"LSTM Autoencoder training on {meta['rows']} healthy samples (early-stopped, best val "
                 f"{meta['best_val_loss']:.3f})", loc="left", pad=12)
    save(fig, "fig7_training_curve.png")


if __name__ == "__main__":
    fig_architecture()
    fig_pipeline()
    fig_gantt()
    fig_training()
    ev, rows, t0 = load_eval()
    fig_latency(ev, rows, t0)
    fig_score(ev, rows, t0)
    fig_errors(ev, rows, t0)
