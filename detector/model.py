"""LSTM Autoencoder + scaler + scoring shared by training, live detection and evaluation."""
import json

import numpy as np
import torch
from torch import nn

from common import config


class LSTMAutoencoder(nn.Module):
    """Compact sequence autoencoder: encoder LSTM -> latent vector -> decoder LSTM -> features."""

    def __init__(self, n_features=15, hidden=32, latent=16):
        super().__init__()
        self.encoder = nn.LSTM(n_features, hidden, batch_first=True)
        self.to_latent = nn.Linear(hidden, latent)
        self.decoder = nn.LSTM(latent, hidden, batch_first=True)
        self.output = nn.Linear(hidden, n_features)

    def forward(self, x):  # x: (batch, seq_len, n_features)
        _, (h, _) = self.encoder(x)
        z = self.to_latent(h[-1])                          # (batch, latent)
        z_seq = z.unsqueeze(1).repeat(1, x.size(1), 1)     # repeat across time
        out, _ = self.decoder(z_seq)
        return self.output(out)


class FlooredStandardScaler:
    """StandardScaler (fit on training segment only) with a minimum std per feature family,
    so near-constant healthy metrics (e.g. 0% errors) still produce meaningful z-scores."""

    def fit(self, X, features):
        self.mean = X.mean(axis=0)
        std = X.std(axis=0)
        floors = np.array([config.STD_FLOOR[next(f for f in config.FEATURE_FAMILIES if name.endswith(f))]
                           for name in features])
        self.std = np.maximum(std, floors)
        return self

    def transform(self, X):
        return (X - self.mean) / self.std

    def to_dict(self):
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, d):
        s = cls()
        s.mean, s.std = np.array(d["mean"]), np.array(d["std"])
        return s


def make_windows(X, seq_len=config.SEQ_LEN):
    return np.stack([X[i:i + seq_len] for i in range(len(X) - seq_len + 1)])


def reconstruction_errors(model, windows):
    """Returns (window_score, per_feature_error). window_score = mean squared error over the
    whole 12-step window; per_feature_error = squared error per feature over the same window
    (used for localization, so the ranking stays on the service whose deviation is in the window)."""
    model.eval()
    with torch.no_grad():
        x = torch.tensor(windows, dtype=torch.float32)
        recon = model(x).numpy()
    sq = (recon - windows) ** 2
    score = sq.mean(axis=(1, 2))
    per_feature = sq.mean(axis=1)
    return score, per_feature


def save_artifacts(model, scaler, metadata):
    torch.save(model.state_dict(), config.MODEL_DIR / "lstm_autoencoder.pt")
    (config.MODEL_DIR / "scaler.json").write_text(json.dumps(scaler.to_dict(), indent=2), encoding="utf-8")
    (config.MODEL_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def load_artifacts():
    meta = json.loads((config.MODEL_DIR / "metadata.json").read_text(encoding="utf-8"))
    scaler = FlooredStandardScaler.from_dict(json.loads((config.MODEL_DIR / "scaler.json").read_text(encoding="utf-8")))
    model = LSTMAutoencoder(len(meta["features"]), meta["hidden"], meta["latent"])
    model.load_state_dict(torch.load(config.MODEL_DIR / "lstm_autoencoder.pt", map_location="cpu"))
    model.eval()
    if meta["features"] != config.FEATURES:
        raise RuntimeError("Feature schema mismatch between training and inference")
    return model, scaler, meta
