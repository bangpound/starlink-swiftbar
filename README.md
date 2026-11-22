# Starlink SwiftBar Plugin

A macOS menu-bar widget showing Starlink dish status, read live from the dish's
gRPC API at `192.168.100.1:9200`.

## Requirements

- [SwiftBar](https://github.com/swiftbar/SwiftBar)
- [`uv`](https://docs.astral.sh/uv/) (`brew install uv`)

The plugin is a single `uv` script; `uv` resolves `grpcio` and `yagrc` on first
run. Nothing is installed globally.

## Install

```bash
chmod +x starlink.30s.py
ln -sf "$(pwd)/starlink.30s.py" ~/Applications/SwiftBar/starlink.30s.py
```

Then Refresh All in SwiftBar. The `.30s.` in the filename sets a 30-second
refresh; rename (e.g. `starlink.1m.py`) to change it.

## Menu bar

Shows the dish's own 15-minute ping success rate (e.g. `🛰 🟢 95.3%`), with a
colored dot for current state: 🟢 connected, 🟠 alert (dish-reported alerts),
🔴 offline (active outage) or disabled (account/service), ⚪️ not on the
Starlink LAN. The dropdown shows the state word, ping success (15m), latency,
drop rate, down/up throughput, obstruction %, uptime, and any active alerts.

The 15-minute ping success comes from the dish's own history ring buffer
(`get_history`), so nothing is stored locally.

## Development

Tests use only the Python standard library (`unittest` + `doctest`) — no
third-party test runner. The plugin's network imports are lazy, so the tests
run without `grpcio`/`yagrc` installed and without a reachable dish:

```bash
uv run --no-project python -m unittest discover -s tests -v   # unit tests + doctests (no dish needed)
uv run ./starlink.30s.py                                       # render once against the live dish
uv run ./starlink.30s.py --debug                               # dump the raw parsed status JSON
```

CI (`.github/workflows/ci.yml`) runs on every push to `main` and every pull
request: `ruff check`, the test suite on Python 3.11–3.14, and a macOS smoke run
that resolves the script's dependencies and checks the plugin prints a valid
SwiftBar menu with no dish reachable.
