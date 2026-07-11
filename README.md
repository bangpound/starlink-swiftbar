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

Shows connection state: **Connected** (green), **Alert** (orange, dish-reported
alerts), **Offline** (active outage), **Disabled** (account/service disabled),
or **–** (dimmed, not on the Starlink LAN). The dropdown shows latency, drop
rate, down/up throughput, obstruction %, uptime, and any active alerts.

## Development

```bash
uv run --with pytest pytest tests/ -v   # unit tests (no dish needed)
uv run ./starlink.30s.py                # render once against the live dish
uv run ./starlink.30s.py --debug        # dump the raw parsed status JSON
```
