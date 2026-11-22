"""One launcher for everything (works on Windows, macOS and Linux).

  python run.py setup      collect healthy baseline (~15 min) + train the model
  python run.py demo       start services + traffic + detector dashboard (http://127.0.0.1:8080)
  python run.py evaluate   automated fault experiments -> results/evaluation.md
  python run.py collect    only collect healthy data
  python run.py train      only train from data/healthy_baseline.csv
  python run.py services   only start the 3 microservices
"""
import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import config  # noqa: E402

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
PY = sys.executable
procs = []


def start(name, args):
    log = open(LOG_DIR / f"{name}.log", "a", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen([PY, *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    procs.append((name, p))
    print(f"  started {name:<10} (log: logs/{name}.log)")
    return p


def start_services():
    print("Starting microservices...")
    for name, port in (("inventory", config.INVENTORY_PORT), ("payment", config.PAYMENT_PORT),
                       ("checkout", config.CHECKOUT_PORT)):
        start(name, ["-m", "uvicorn", f"services.{name}:app", "--host", config.HOST,
                     "--port", str(port), "--log-level", "warning"])
    wait_for({s: f"{u}/health" for s, u in config.SERVICE_URLS.items()})


def wait_for(urls, timeout=60):
    deadline = time.time() + timeout
    pending = dict(urls)
    while pending and time.time() < deadline:
        for name, url in list(pending.items()):
            try:
                if httpx.get(url, timeout=1).status_code == 200:
                    print(f"  {name} is up")
                    pending.pop(name)
            except httpx.HTTPError:
                pass
        for n, p in procs:
            if p.poll() is not None:
                raise SystemExit(f"ERROR: {n} exited early - see logs/{n}.log")
        time.sleep(0.5)
    if pending:
        raise SystemExit(f"ERROR: not reachable: {list(pending)} - check logs/ folder")


def start_traffic():
    start("traffic", ["traffic/generator.py"])


def start_detector():
    if not (config.MODEL_DIR / "metadata.json").exists():
        raise SystemExit("No trained model found. Run:  python run.py setup")
    start("detector", ["detector/app.py"])
    wait_for({"dashboard": f"http://127.0.0.1:{config.DASHBOARD_PORT}/api/state"})


def stop_all():
    for name, p in reversed(procs):
        if p.poll() is None:
            p.terminate()
    for name, p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    procs.clear()


def run_step(args):
    """Run a foreground python step and stream its output."""
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1"}
    r = subprocess.run([PY, *args], cwd=ROOT, env=env)
    if r.returncode != 0:
        raise SystemExit(f"ERROR: step failed: {' '.join(args)}")


def wait_forever():
    try:
        while True:
            time.sleep(1)
            for n, p in procs:
                if p.poll() is not None:
                    print(f"WARNING: {n} stopped - see logs/{n}.log")
                    procs.remove((n, p))
                    break
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["setup", "demo", "evaluate", "collect", "train", "services"])
    ap.add_argument("--minutes", type=float, default=15, help="healthy collection length (setup/collect)")
    ap.add_argument("--warmup", type=float, default=60, help="seconds of traffic before collecting")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    try:
        if a.command == "train":
            run_step(["detector/train.py"])
            return
        start_services()
        if a.command == "services":
            print("Services running. Press Ctrl+C to stop.")
            wait_forever()
            return
        start_traffic()
        if a.command in ("setup", "collect"):
            print(f"Warming up with healthy traffic for {a.warmup:.0f} s...")
            time.sleep(a.warmup)
            run_step(["detector/collect.py", "--minutes", str(a.minutes)])
            if a.command == "setup":
                stop_all()
                run_step(["detector/train.py"])
                print("\nSetup complete. Next:  python run.py demo")
            return
        start_detector()
        url = f"http://127.0.0.1:{config.DASHBOARD_PORT}"
        if a.command == "evaluate":
            run_step(["evaluation/evaluate.py"])
            return
        print(f"\nDashboard: {url}\n(the detector needs ~60 s to fill its first window)")
        print("Press Ctrl+C to stop everything.")
        if not a.no_browser:
            webbrowser.open(url)
        wait_forever()
    finally:
        print("Stopping all processes...")
        stop_all()


if __name__ == "__main__":
    main()
