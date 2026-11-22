"""Trains the LSTM Autoencoder on healthy telemetry only and calibrates the anomaly threshold.

Workflow (Milestone 1, section 05):
 1. load healthy rows (all 15 features present)
 2. chronological split -> train / validation; scaler fitted on train only
 3. 12-step overlapping windows, train autoencoder
 4. threshold from held-out healthy validation reconstruction errors
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import config  # noqa: E402
from detector.model import (FlooredStandardScaler, LSTMAutoencoder, make_windows,  # noqa: E402
                            reconstruction_errors, save_artifacts)


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = list(r)
    missing = [c for c in config.FEATURES if c not in r.fieldnames]
    if missing:
        raise SystemExit(f"CSV is missing features: {missing}")
    X = np.array([[float(row[c]) for c in config.FEATURES] for row in rows], dtype=np.float64)
    return X


def main(csv_path, epochs, val_frac, seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    X = load_csv(csv_path)
    n = len(X)
    if n < 4 * config.SEQ_LEN:
        raise SystemExit(f"Only {n} rows - collect more healthy data (need at least {4 * config.SEQ_LEN}).")
    split = int(n * (1 - val_frac))
    scaler = FlooredStandardScaler().fit(X[:split], config.FEATURES)
    Xs = scaler.transform(X)
    train_w = make_windows(Xs[:split])
    val_w = make_windows(Xs[split:])
    print(f"[train] rows={n} train_rows={split} val_rows={n - split} "
          f"train_windows={len(train_w)} val_windows={len(val_w)}", flush=True)

    model = LSTMAutoencoder(len(config.FEATURES), hidden=32, latent=16)
    opt = torch.optim.Adam(model.parameters(), lr=3e-3)
    loss_fn = nn.MSELoss()
    xt = torch.tensor(train_w, dtype=torch.float32)
    xv = torch.tensor(val_w, dtype=torch.float32)
    best, best_state, patience, history = float("inf"), None, 0, []
    t0 = time.time()
    for ep in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(len(xt))
        for i in range(0, len(xt), 16):
            b = xt[perm[i:i + 16]]
            opt.zero_grad()
            loss = loss_fn(model(b), b)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            tl = loss_fn(model(xt), xt).item()
            vl = loss_fn(model(xv), xv).item()
        history.append({"epoch": ep, "train_loss": tl, "val_loss": vl})
        if vl < best - 1e-4:
            best, best_state, patience = vl, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            patience += 1
        if ep % 25 == 0 or ep == 1:
            print(f"[train] epoch {ep:3d} train_loss={tl:.4f} val_loss={vl:.4f}", flush=True)
        if patience >= 40:
            print(f"[train] early stop at epoch {ep}", flush=True)
            break
    model.load_state_dict(best_state)

    # ---- threshold calibration on held-out healthy windows ----
    val_scores, val_feat = reconstruction_errors(model, val_w)
    train_scores, _ = reconstruction_errors(model, train_w)
    mean, std, vmax = float(val_scores.mean()), float(val_scores.std()), float(val_scores.max())
    threshold = max(mean + 4 * std, vmax * 1.5)
    fp_train = float((train_scores > threshold).mean())
    feat_mean = val_feat.mean(axis=0)
    feat_p99 = np.percentile(val_feat, 99, axis=0)

    trace_baseline = {}
    tb_path = config.DATA_DIR / "trace_baseline.json"
    if tb_path.exists():
        trace_baseline = json.loads(tb_path.read_text(encoding="utf-8"))

    meta = {
        "features": config.FEATURES,
        "seq_len": config.SEQ_LEN,
        "sample_interval": config.SAMPLE_INTERVAL,
        "hidden": 32, "latent": 16,
        "threshold": threshold,
        "threshold_rule": "max(mean + 4*std, 1.5 * max) of held-out healthy validation window scores",
        "val_score_mean": mean, "val_score_std": std, "val_score_max": vmax,
        "train_windows_over_threshold": fp_train,
        "feature_error_mean": feat_mean.tolist(),
        "feature_error_p99": feat_p99.tolist(),
        "trace_baseline": trace_baseline,
        "rows": n, "train_rows": split, "val_rows": n - split,
        "epochs_run": len(history), "best_val_loss": best,
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "training_seconds": round(time.time() - t0, 1),
    }
    save_artifacts(model, FlooredStandardScaler.from_dict(scaler.to_dict()), meta)
    (config.RESULTS_DIR / "training_history.json").write_text(json.dumps(history), encoding="utf-8")

    report = [
        "# Training report", "",
        f"- Trained at: {meta['trained_at']} ({meta['training_seconds']} s, {len(history)} epochs)",
        f"- Healthy rows: {n} (train {split}, validation {n - split}, chronological split)",
        f"- Windows: train {len(train_w)}, validation {len(val_w)} (length {config.SEQ_LEN} x {len(config.FEATURES)} features)",
        f"- Best validation loss: {best:.4f}",
        f"- Validation window score: mean {mean:.4f}, std {std:.4f}, max {vmax:.4f}",
        f"- **Anomaly threshold: {threshold:.4f}** ({meta['threshold_rule']})",
        f"- Training windows above threshold: {fp_train * 100:.1f}%",
    ]
    (config.RESULTS_DIR / "training_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report), flush=True)
    print(f"[train] saved model, scaler and metadata to {config.MODEL_DIR}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default=str(config.DATA_DIR / "healthy_baseline.csv"))
    p.add_argument("--epochs", type=int, default=300)
    p.add_argument("--val-frac", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    main(a.csv, a.epochs, a.val_frac, a.seed)
