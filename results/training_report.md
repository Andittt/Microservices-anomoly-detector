# Training report

- Trained at: 2026-11-17 12:30:03 (1.6 s, 87 epochs)
- Healthy rows: 180 (train 135, validation 45, chronological split)
- Windows: train 124, validation 34 (length 12 x 15 features)
- Best validation loss: 0.1208
- Validation window score: mean 0.1208, std 0.0578, max 0.2782
- **Anomaly threshold: 0.4174** (max(mean + 4*std, 1.5 * max) of held-out healthy validation window scores)
- Training windows above threshold: 0.0%
