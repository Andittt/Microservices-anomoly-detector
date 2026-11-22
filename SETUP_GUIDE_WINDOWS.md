# Setup and Test Guide (Windows)

**Project:** Dynamic Microservice Anomaly Detection & Root-Cause Isolation

This guide walks you from a fresh Windows laptop to a working, tested demo.
**Do all of it the day before the presentation.**

Total time is about **35–45 minutes**. Most of that is waiting while the
computer installs packages and learns the laptop's normal behaviour.

| Part | What happens | Time |
|---|---|---|
| A | Install Python | 5 min |
| B | Unzip the project | 2 min |
| C | First-time setup (install packages, collect healthy data, train the model) | 20–30 min, mostly waiting |
| D | Run the demo and test both faults | 10 min |
| E | Optional: automated evaluation | 12 min, waiting |

---

## Before you start

You need:

- A Windows 10 or 11 laptop with at least **4 GB RAM** and about **3 GB free disk space**.
- An **internet connection**, needed for the first install only (about 1 GB download). After that it runs offline.
- The file **`microservice-anomaly-detection.zip`**.
- Keep the laptop **plugged in**, and do not let it sleep during Part C.

---

## Part A: Install Python (skip if Python 3.10–3.13 is already installed)

**A1. Check whether Python is already installed.**
Press the **Windows key**, type `cmd`, press **Enter**. In the black window, type:

```
py --list
```

- If you see `3.13`, `3.12`, `3.11` or `3.10` in the list, Python is ready. **Go to Part B.**
- If you see *"'py' is not recognized"*, or only versions like 3.14 or 3.15, continue with A2.

> **Why not the newest Python?** The machine-learning library (PyTorch) may not support
> the very newest Python yet. **Python 3.13 is the safe choice.**

**A2. Download Python 3.13.**
1. Open https://www.python.org/downloads/windows/
2. Under **"Stable Releases"**, find the newest **Python 3.13.x** entry (for example *Python 3.13.9*).
3. Click **"Download Windows installer (64-bit)"**.

**A3. Run the installer.**
1. Double-click the downloaded file (`python-3.13.x-amd64.exe`).
2. **IMPORTANT:** on the first screen, tick the box **"Add python.exe to PATH"** at the bottom.
3. Click **"Install Now"** and wait for *"Setup was successful"*.
4. If you see the option **"Disable path length limit"**, click it. This is optional but helps.
5. Click **Close**.

**A4. Check the install.** **Close** any open Command Prompt windows, open a **new** one
(Windows key → `cmd` → Enter) and type:

```
py -3.13 --version
```

You should see `Python 3.13.x`. If you do, Python is ready.

---

## Part B: Unzip the project

1. Copy `microservice-anomaly-detection.zip` to an easy location, for example the **Desktop**.
2. **Right-click** the zip → **"Extract All..."** → **Extract**.

   **Do not run anything from inside the zip preview window.** It must be extracted first.
3. You should now have a folder **`microservice-anomaly-detection`** containing `run.bat`,
   `README.md`, and folders such as `services`, `detector` and `dashboard`.

   If you see another `microservice-anomaly-detection` folder inside it, go into that inner folder.
4. **Open a Command Prompt in that folder:**
   - Open the folder in File Explorer.
   - Click the **address bar** at the top, type `cmd`, and press **Enter**.
   - A black Command Prompt window opens, already inside the project folder.
5. Check that you're in the right place. Type `dir` and press Enter. You should see `run.bat` in the list.

> Use **Command Prompt (cmd)**, not PowerShell. If you do use PowerShell, type `.\run.bat`
> instead of `run.bat` in every command below.

---

## Part C: First-time setup (do this once on this laptop)

In the Command Prompt from Part B4, type:

```
run.bat setup
```

**What you will see, in order:**

1. `[setup] First run: creating a Python environment in .venv ...` and `Using Python 3.13`.
2. `[setup] Installing packages ...`, followed by a lot of download text.
   This takes **3–10 minutes**, because PyTorch is large. **Do not close the window.**
3. `Starting microservices...` and then `checkout is up`, `inventory is up`, `payment is up`.
4. `Warming up with healthy traffic for 60 s...`
5. `[collect] collecting 180 healthy rows (~15.0 min)`, then a progress line about every minute, for example:
   ```
   [collect] 12/180 rows (rejected 1) checkout p95=145ms rps=9.2
   [collect] 24/180 rows (rejected 1) checkout p95=146ms rps=8.7
   ```
   This takes **15 minutes**. Leave the laptop alone; don't let it sleep.
6. A short **Training report**, for example:
   ```
   - Healthy rows: 180 (train 135, validation 45, chronological split)
   - **Anomaly threshold: 0.4174** ...
   - Training windows above threshold: 0.0%
   ```
   Your numbers will be different from these. That is expected.
7. Finally: **`Setup complete. Next:  python run.py demo`**

**Setup succeeded if you see "Setup complete".**

> **Short on time?** `run.bat setup --minutes 10` collects 10 minutes instead of 15.
> It works, but 15 minutes gives a more reliable model.
>
> **Windows Firewall popup?** It shouldn't appear because everything runs on `127.0.0.1`.
> If it does, clicking **Allow** or **Cancel** both work.

---

## Part D: Run the demo and test it

### D1. Start the demo

In the same Command Prompt, type:

```
run.bat demo
```

You will see the services start, then:

```
Dashboard: http://127.0.0.1:8080
Press Ctrl+C to stop everything.
```

Your web browser opens the dashboard automatically. If it doesn't, open Chrome or Edge and go to
**http://127.0.0.1:8080**.

**Keep the Command Prompt window open** the whole time. Closing it stops the demo.

### D2. Wait for HEALTHY (about 60–70 seconds)

- At first the status pill at the top says **WARMING UP**, and the root-cause panel says *"Filling the 12-step window (3/12)..."*.
- After about a minute it changes to green **HEALTHY**.
- The anomaly score line (white) should stay **below the red dashed threshold line**.
- The latency, error-rate and traffic charts show steady lines.

✅ **Test 1 passed if:** the status stays **HEALTHY** for 2–3 minutes.

### D3. Test fault 1: inventory latency

1. Click **"Inject inventory delay (1.5 s)"** at the top.
2. Within about **10–20 seconds**:
   - the status turns red: **ANOMALY DETECTED**;
   - the score line jumps far above the red threshold line;
   - the **Latency p95** chart shows inventory and checkout rising to about 2 seconds.
3. Check the **Suspected root cause** panel:
   - **Most likely service: inventory**;
   - deviating metric: **inventory_latency_p95**;
   - a green box saying **"Trace evidence agrees: inventory self time ~1000–1500 ms vs healthy ~40 ms"**;
   - a note that checkout's latency is **propagated from inventory**.
4. Scroll down to **Evidence trace**. The waterfall shows one checkout request with a long inventory bar.

✅ **Test 2 passed if:** the status is **ANOMALY DETECTED** and the suspected service is **inventory**.

### D4. Recover

1. Click **"Clear faults"**.
2. Wait about **60–70 seconds**. The 60-second window has to fill with healthy data again.
3. The status returns to green **HEALTHY**.

✅ **Test 3 passed if:** it goes back to **HEALTHY** within about 1.5 minutes.

### D5. Test fault 2: payment errors

1. Click **"Inject payment errors (30%)"**.
2. Within about **10–20 seconds**:
   - the status turns **ANOMALY DETECTED**;
   - the **Error rate** chart shows payment and checkout at about 30%. Checkout fails whenever payment fails.
3. The **Suspected root cause** panel shows **payment**, with trace evidence such as
   *"30% of recent traces have errors originating in payment"*.
4. Click **"Clear faults"** and wait for **HEALTHY** again.

✅ **Test 4 passed if:** the suspected service is **payment**.

### D6. Stop the demo

Click the Command Prompt window and press **Ctrl + C**. If Windows asks
*"Terminate batch job (Y/N)?"*, type **Y** and press Enter.

**If all 4 tests passed, the laptop is ready for the presentation.**

---

## Part E (optional): Automated evaluation with measured results

This runs both faults automatically and calculates the numbers for the report. It takes about **12 minutes** and you don't need to touch anything.

```
run.bat evaluate
```

When it finishes, open **`results\evaluation.md`** in the project folder (Notepad is fine). It contains:

- the detection delay;
- the false-positive rate;
- the detection rate;
- whether the correct service was identified.

On the developer's Mac, the result was **0 false alerts, about 8.5 s detection delay and 100% correct service** for both faults.

To regenerate the report charts from this new run, type:

```
.venv\Scripts\python.exe -m pip install matplotlib
.venv\Scripts\python.exe figures\make_figures.py
```

The new images appear in the `figures` folder.

---

## On presentation day

1. Open the project folder → click the address bar → type `cmd` → Enter.
2. Type `run.bat demo`.
3. **Wait for HEALTHY before you start presenting.** That takes about 1 minute, so start it a couple of minutes early.
4. Follow the demo script in Part D (D3 → D4 → D5).
5. Don't run `setup` again on the day. It isn't needed and takes 20 minutes.

**Talking points while demonstrating:**

- *"The model was trained only on healthy traffic. It has never seen a fault."*
- *"The score is the LSTM autoencoder's reconstruction error. The red line is a threshold calibrated on held-out healthy data."*
- *"Checkout is slow too, but the system ranks inventory first. Checkout is only waiting on inventory, and the traces confirm it."*
- *"This is a ranked hypothesis supported by trace evidence, not a proof of causality."*

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `'py' is not recognized` or `Python 3.10–3.13 was not found` | Python isn't installed or not on PATH. Redo **Part A**, tick **"Add python.exe to PATH"**, then open a **new** Command Prompt. |
| `'run.bat' is not recognized` | You're not in the project folder. Redo **Part B4**, and type `dir` to check that `run.bat` is listed. In PowerShell use `.\run.bat`. |
| Package install fails (red `ERROR`, `No matching distribution found for torch`) | Usually the wrong Python version or no internet. Delete the `.venv` folder (`rmdir /s /q .venv`), make sure Python **3.13** is installed (`py -3.13 --version`), and run `run.bat setup` again. |
| `ERROR: not reachable` or `exited early` when starting | A port is already in use, often by an old demo still running. Close **all** Command Prompt windows, or restart the laptop, and try again. See the next row for how to find the program using a port. |
| Port 8080 / 8001 / 8002 / 8003 in use | `netstat -ano \| findstr :8080` shows a PID in the last column. Then run `taskkill /PID <that number> /F`. |
| Dashboard shows **DETECTOR OFFLINE** | The demo stopped. Check that the Command Prompt is still running, and read `logs\detector.log`. |
| `No trained model found. Run: python run.py setup` | Part C wasn't completed. Run `run.bat setup`. |
| Status shows **ANOMALY** while no fault is injected | The model was trained on a different machine, or the laptop was busy or asleep during setup. Close heavy apps and run `run.bat setup` again. |
| Status stuck on **WARMING UP** for more than 2 minutes | Read `logs\detector.log` and `logs\traffic.log`. Restart with Ctrl+C, then `run.bat demo`. |
| Something else | Every process writes a log to the **`logs`** folder (`checkout.log`, `inventory.log`, `payment.log`, `traffic.log`, `detector.log`). Send those files to the project owner. |

**Starting completely fresh:** delete the `.venv` folder, the `data\healthy_baseline.csv` file and the
`model_artifacts` folder, then run `run.bat setup`.

---

## Quick reference

| Command | What it does |
|---|---|
| `run.bat setup` | First time only: install packages, collect 15 min healthy data, train the model |
| `run.bat demo` | Start everything and open the dashboard at http://127.0.0.1:8080 |
| `run.bat evaluate` | 12-minute automated test, results in `results\evaluation.md` |
| **Ctrl + C** then **Y** | Stop everything |
