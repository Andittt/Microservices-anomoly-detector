# Evaluation results

Run at 2026-11-17 12:42:11. Sampling every 5 s, window 12 samples, threshold 0.4174. An alert is confirmed after 2 consecutive windows above threshold.

## Timeline

| Phase | Duration |
|---|---|
| healthy baseline | 180 s |
| inventory latency +1.5 s | 120 s |
| recovery 1 | 120 s |
| payment 30% errors | 120 s |
| recovery 2 | 120 s |

## Healthy false-positive rate

- Evaluated healthy windows: **56** (~280 s, excluding the post-fault recovery period)
- False alerts: **0** -> false-positive rate **0.0%**

## Fault experiments

| Fault | True service | Detected | Detection delay | Detection rate | Localization accuracy | Trace agreement |
|---|---|---|---|---|---|---|
| inventory latency +1.5 s | inventory | yes | 8.5 s | 95.8% (24 windows) | 100.0% | 100.0% |
| payment 30% errors | payment | yes | 8.4 s | 95.8% (24 windows) | 100.0% | 100.0% |

Definitions:
- *Detection delay*: time from fault injection to the first confirmed alert.
- *Detection rate*: fraction of fault-period windows with a confirmed alert (includes the first windows before the fault had entered the 60 s window, so it is a conservative number).
- *Localization accuracy*: fraction of alert windows where the top-ranked service was the injected one.
- *Trace agreement*: fraction of alert windows where trace evidence independently pointed to the injected service.

## Limitations

- Single machine, simulated services and synthetic traffic; results are not production-scale.
- Two fault types only (latency, errors); CPU / memory faults were not injected.
- The ranking is a hypothesis supported by traces, not proof of causality.
- Thresholds are calibrated on one healthy run; a new machine should be re-baselined (python run.py setup).
