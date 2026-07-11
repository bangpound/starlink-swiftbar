# Starlink SwiftBar Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single-file SwiftBar plugin that shows Starlink dish status in the macOS menu bar, reading live data from the dish's gRPC API.

**Architecture:** One self-contained `uv` script (`starlink.30s.py`) with a PEP 723 header. It fetches the dish's proto schema at runtime via gRPC server reflection (`yagrc`), calls `SpaceX.API.Device.Device/Handle` with `get_status`, and renders SwiftBar output. Network I/O (`fetch_status`) is isolated from pure logic (`render`, `active_alerts`, `state_word`, `humanize_uptime`) so the logic is unit-tested with no dish present. `grpc`/`yagrc` are imported lazily inside `fetch_status` so tests import the module without those deps.

**Tech Stack:** Python ≥3.11, `uv` (inline script metadata), `grpcio`, `yagrc`, `pytest` (dev only).

## Global Constraints

- Every Python script uses uv's inline-script functionality (PEP 723 `# /// script` header); run via `uv run`. No global pip installs.
- Plugin must be a **single executable file** named `starlink.30s.py` (SwiftBar reads the `.30s.` segment as a 30-second refresh interval).
- The plugin must **never** print a Python traceback to stdout — all failures render as a clean SwiftBar state.
- `grpc` and `yagrc` are imported **lazily inside `fetch_status` only**, never at module top level.
- Dish gRPC address: `192.168.100.1:9200`. gRPC call deadline: `4` seconds.
- Parse responses with `MessageToDict(resp, preserving_proto_field_name=True)` → snake_case keys. `MessageToDict` omits zero/false/empty fields, so read every field with `.get(key, default)`.

---

## File Structure

- `starlink.30s.py` (repo root) — the plugin. Contains: PEP 723 header, constants, `humanize_uptime`, `ALERT_LABELS`, `active_alerts`, `state_word`, `render`, `fetch_status`, `main`, and a `if __name__ == "__main__": main()` guard.
- `tests/test_starlink.py` — loads the plugin via `importlib` from its path (the filename has dots, so it can't be a normal import) and tests all pure functions against embedded fixtures.
- `README.md` — install/deploy instructions (symlink into `~/Applications/SwiftBar/`).

Dev copy lives in the repo; deployment is a symlink from `~/Applications/SwiftBar/starlink.30s.py` to the repo file so edits live-update.

---

### Task 1: Scaffold plugin + `humanize_uptime` + test harness

**Files:**
- Create: `starlink.30s.py`
- Test: `tests/test_starlink.py`

**Interfaces:**
- Produces: `humanize_uptime(seconds: int | str) -> str` — e.g. `4062 → "1h 7m"`, `0 → "0m"`, `93784 → "1d 2h 3m"`.
- Produces: a module loadable via `importlib` under the name `starlink_plugin` (used by all later test tasks).

- [ ] **Step 1: Write the failing test**

Create `tests/test_starlink.py`:

```python
import importlib.util
import pathlib

_PLUGIN = pathlib.Path(__file__).resolve().parent.parent / "starlink.30s.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location("starlink_plugin", _PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plugin = load_plugin()


def test_humanize_uptime_minutes_only():
    assert plugin.humanize_uptime(4062) == "1h 7m"


def test_humanize_uptime_zero():
    assert plugin.humanize_uptime(0) == "0m"


def test_humanize_uptime_days():
    assert plugin.humanize_uptime(93784) == "1d 2h 3m"


def test_humanize_uptime_accepts_string():
    assert plugin.humanize_uptime("4062") == "1h 7m"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_starlink.py -v`
Expected: FAIL — `starlink.30s.py` does not exist yet (import/exec error), or `AttributeError: module has no attribute 'humanize_uptime'`.

- [ ] **Step 3: Write minimal implementation**

Create `starlink.30s.py`:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["grpcio", "yagrc"]
# ///
"""SwiftBar plugin: Starlink dish status in the macOS menu bar."""

import sys

DISH_ADDR = "192.168.100.1:9200"
DEADLINE_S = 4.0


def humanize_uptime(seconds) -> str:
    total = int(seconds)
    minutes, _ = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


if __name__ == "__main__":
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_starlink.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add starlink.30s.py tests/test_starlink.py
git commit -m "feat: scaffold starlink swiftbar plugin with humanize_uptime"
```

---

### Task 2: Alert derivation — `ALERT_LABELS`, `active_alerts`, `state_word`

**Files:**
- Modify: `starlink.30s.py`
- Test: `tests/test_starlink.py`

**Interfaces:**
- Consumes: parsed status dict (snake_case keys, from `MessageToDict(..., preserving_proto_field_name=True)`).
- Produces: `active_alerts(status: dict) -> list[str]` — human labels for every true alert bool plus software-update state.
- Produces: `state_word(status: dict) -> tuple[str, str]` — `(word, color)` for the menu-bar title. Priority: `disablement_code != "OKAY"` → `("Disabled", "red")`; `outage` present → `("Offline", "red")`; any active alert → `("Alert", "orange")`; else → `("Connected", "#3cb371")`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_starlink.py`:

```python
HEALTHY = {
    "device_info": {"software_version": "2026.07.06.cr81950",
                    "hardware_version": "mini1_panda_prod2"},
    "device_state": {"uptime_s": "4062"},
    "obstruction_stats": {"fraction_obstructed": 0.42797056},
    "alerts": {},
    "downlink_throughput_bps": 18197474.0,
    "uplink_throughput_bps": 793159.7,
    "pop_ping_latency_ms": 19.134296,
    "software_update_state": "IDLE",
    "disablement_code": "OKAY",
}


def test_active_alerts_none_when_healthy():
    assert plugin.active_alerts(HEALTHY) == []


def test_active_alerts_lists_true_bools():
    status = {"alerts": {"thermal_throttle": True, "roaming": True}}
    result = plugin.active_alerts(status)
    assert "Thermal throttle" in result
    assert "Roaming" in result
    assert len(result) == 2


def test_active_alerts_includes_pending_software_update():
    status = {"alerts": {}, "software_update_state": "DOWNLOADING"}
    assert any("Software update" in a for a in plugin.active_alerts(status))


def test_state_word_connected():
    assert plugin.state_word(HEALTHY) == ("Connected", "#3cb371")


def test_state_word_alert():
    status = {"alerts": {"thermal_throttle": True}, "disablement_code": "OKAY"}
    assert plugin.state_word(status) == ("Alert", "orange")


def test_state_word_disabled():
    status = {"alerts": {}, "disablement_code": "NO_ACTIVE_ACCOUNT"}
    assert plugin.state_word(status) == ("Disabled", "red")


def test_state_word_offline_on_outage():
    status = {"alerts": {}, "disablement_code": "OKAY", "outage": {"cause": "NO_SCHEDULE"}}
    assert plugin.state_word(status) == ("Offline", "red")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_starlink.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'active_alerts'`.

- [ ] **Step 3: Write minimal implementation**

In `starlink.30s.py`, add after `humanize_uptime`:

```python
ALERT_LABELS = {
    "motors_stuck": "Motors stuck",
    "thermal_throttle": "Thermal throttle",
    "thermal_shutdown": "Thermal shutdown",
    "mast_not_near_vertical": "Mast not vertical",
    "unexpected_location": "Unexpected location",
    "slow_ethernet_speeds": "Slow Ethernet",
    "slow_ethernet_speeds_100": "Ethernet limited to 100M",
    "roaming": "Roaming",
    "install_pending": "Install pending",
    "is_heating": "Heating (snow melt)",
    "power_supply_thermal_throttle": "Power supply throttle",
    "is_power_save_idle": "Power save idle",
    "dbf_telem_stale": "Telemetry stale",
    "low_motor_current": "Low motor current",
    "lower_signal_than_predicted": "Signal lower than predicted",
    "obstruction_map_reset": "Obstruction map reset",
    "dish_water_detected": "Water in dish",
    "router_water_detected": "Water in router",
    "upsu_router_port_slow": "Router port slow",
    "no_ethernet_link": "No Ethernet link",
}


def active_alerts(status) -> list:
    alerts = status.get("alerts", {})
    out = [label for key, label in ALERT_LABELS.items() if alerts.get(key)]
    if status.get("swupdate_reboot_ready"):
        out.append("Software update ready (reboot)")
    sw = status.get("software_update_state", "IDLE")
    if sw not in ("IDLE", "", "DISABLED"):
        out.append(f"Software update: {sw}")
    return out


def state_word(status):
    if status.get("disablement_code", "OKAY") != "OKAY":
        return ("Disabled", "red")
    if status.get("outage"):
        return ("Offline", "red")
    if active_alerts(status):
        return ("Alert", "orange")
    return ("Connected", "#3cb371")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_starlink.py -v`
Expected: PASS (all tests, including Task 1's).

- [ ] **Step 5: Commit**

```bash
git add starlink.30s.py tests/test_starlink.py
git commit -m "feat: add alert labels and menu-bar state derivation"
```

---

### Task 3: `render` — all display states

**Files:**
- Modify: `starlink.30s.py`
- Test: `tests/test_starlink.py`

**Interfaces:**
- Consumes: `state_word`, `active_alerts`, `humanize_uptime`, `HEALTHY` fixture.
- Produces: `render(status: dict | None, error: str | None = None) -> str` — the full SwiftBar block (menu title, `---`, dropdown, `---`, actions). Contract:
  - `error is not None` → title `🛰 ? | color=#888888`, body line starting `Error:`.
  - `status is None` → title `🛰 – | color=#888888`, body `Dish not reachable`.
  - otherwise → title `🛰 {word} | color={color}` from `state_word`, then metric lines, then an `Alerts:` section, then actions.
- All three cases end with two action lines: `Open Starlink UI | href=http://192.168.100.1` and `Refresh | refresh=true`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_starlink.py`:

```python
def test_render_healthy():
    out = plugin.render(HEALTHY)
    lines = out.splitlines()
    assert lines[0] == "🛰 Connected | color=#3cb371"
    assert "---" in lines
    assert "Latency: 19 ms  ·  Drop: 0.0%" in out
    assert "↓ 18.2 Mbps   ↑ 0.8 Mbps" in out
    assert "Obstruction: 42.8%" in out
    assert "Uptime: 1h 7m" in out
    assert "Alerts: none" in out
    assert "Open Starlink UI | href=http://192.168.100.1" in out
    assert "Refresh | refresh=true" in out


def test_render_alert_lists_alerts():
    status = dict(HEALTHY, alerts={"thermal_throttle": True})
    out = plugin.render(status)
    assert out.splitlines()[0] == "🛰 Alert | color=orange"
    assert "⚠ Thermal throttle | color=orange" in out
    assert "Alerts: none" not in out


def test_render_unreachable():
    out = plugin.render(None)
    lines = out.splitlines()
    assert lines[0] == "🛰 – | color=#888888"
    assert "Dish not reachable" in out
    assert "Refresh | refresh=true" in out


def test_render_error_has_no_traceback():
    out = plugin.render(None, error="boom")
    lines = out.splitlines()
    assert lines[0] == "🛰 ? | color=#888888"
    assert "Error: boom | color=red" in out


def test_render_missing_fields_do_not_crash():
    # MessageToDict omits zero/empty fields; render must tolerate a bare dict.
    out = plugin.render({"alerts": {}, "disablement_code": "OKAY"})
    assert out.splitlines()[0] == "🛰 Connected | color=#3cb371"
    assert "Latency: — ms" in out
    assert "Uptime: 0m" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_starlink.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'render'`.

- [ ] **Step 3: Write minimal implementation**

In `starlink.30s.py`, add after `state_word`:

```python
def _actions():
    return [
        "---",
        "Open Starlink UI | href=http://192.168.100.1",
        "Refresh | refresh=true",
    ]


def render(status, error=None) -> str:
    lines = []
    if error is not None:
        lines.append("🛰 ? | color=#888888")
        lines.append("---")
        lines.append(f"Error: {error} | color=red")
        lines.extend(_actions())
        return "\n".join(lines)

    if status is None:
        lines.append("🛰 – | color=#888888")
        lines.append("---")
        lines.append("Dish not reachable")
        lines.append("(not connected to Starlink LAN) | color=#888888")
        lines.extend(_actions())
        return "\n".join(lines)

    word, color = state_word(status)
    lines.append(f"🛰 {word} | color={color}")
    lines.append("---")

    latency = status.get("pop_ping_latency_ms")
    lat_str = f"{latency:.0f} ms" if latency is not None else "— ms"
    drop = status.get("pop_ping_drop_rate", 0.0)
    lines.append(f"Latency: {lat_str}  ·  Drop: {drop * 100:.1f}%")

    down = status.get("downlink_throughput_bps", 0.0) / 1e6
    up = status.get("uplink_throughput_bps", 0.0) / 1e6
    lines.append(f"↓ {down:.1f} Mbps   ↑ {up:.1f} Mbps")

    frac = status.get("obstruction_stats", {}).get("fraction_obstructed", 0.0)
    lines.append(f"Obstruction: {frac * 100:.1f}%")

    uptime = humanize_uptime(status.get("device_state", {}).get("uptime_s", 0))
    lines.append(f"Uptime: {uptime}")

    lines.append("---")
    alerts = active_alerts(status)
    if alerts:
        lines.append("Alerts:")
        for alert in alerts:
            lines.append(f"⚠ {alert} | color=orange")
    else:
        lines.append("Alerts: none")

    lines.extend(_actions())
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_starlink.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add starlink.30s.py tests/test_starlink.py
git commit -m "feat: render all SwiftBar display states"
```

---

### Task 4: `fetch_status` + `main` (live integration)

**Files:**
- Modify: `starlink.30s.py`

**Interfaces:**
- Consumes: `render`, `DISH_ADDR`, `DEADLINE_S`.
- Produces: `fetch_status(addr: str = DISH_ADDR, timeout: float = DEADLINE_S) -> dict | None` — returns the parsed `dish_get_status` dict, or `None` when the dish is unreachable (`grpc.RpcError` with `UNAVAILABLE`/`DEADLINE_EXCEEDED`). Re-raises other `RpcError`s.
- Produces: `main(argv=None) -> None` — fetches, prints `render(...)`; on any unexpected exception prints `render(None, error=str(e))`; `--debug` prints the raw parsed dict as JSON instead.

- [ ] **Step 1: Write implementation**

`fetch_status` and `main` need a live dish and lazy gRPC imports, so they are verified manually rather than unit-tested (the pure logic is already covered). In `starlink.30s.py`, add after `render`:

```python
def fetch_status(addr=DISH_ADDR, timeout=DEADLINE_S):
    import grpc
    from google.protobuf.json_format import MessageToDict
    from yagrc import reflector as yagrc_reflector

    channel = grpc.insecure_channel(addr)
    try:
        reflector = yagrc_reflector.GrpcReflectionClient()
        reflector.load_protocols(channel, symbols=["SpaceX.API.Device.Device"])
        stub_class = reflector.service_stub_class("SpaceX.API.Device.Device")
        request_class = reflector.message_class("SpaceX.API.Device.Request")
        stub = stub_class(channel)
        response = stub.Handle(request_class(get_status={}), timeout=timeout)
    except grpc.RpcError as exc:
        if exc.code() in (grpc.StatusCode.UNAVAILABLE,
                          grpc.StatusCode.DEADLINE_EXCEEDED):
            return None
        raise
    finally:
        channel.close()

    parsed = MessageToDict(response, preserving_proto_field_name=True)
    return parsed.get("dish_get_status", {})


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    try:
        status = fetch_status()
    except Exception as exc:  # never leak a traceback to the menu bar
        print(render(None, error=str(exc)))
        return
    if "--debug" in argv:
        import json
        print(json.dumps(status, indent=2))
        return
    print(render(status))
```

Then replace the file's `if __name__ == "__main__":` block:

```python
if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify unit tests still pass (module still importable)**

Run: `uv run --with pytest pytest tests/test_starlink.py -v`
Expected: PASS — lazy imports mean the module still loads without `grpcio`.

- [ ] **Step 3: Verify against the live dish (must be on the Starlink LAN)**

Run: `uv run ./starlink.30s.py`
Expected: a menu-bar block whose first line is `🛰 Connected | color=#3cb371`, followed by real latency/throughput/uptime and `Alerts: none`.

Run: `uv run ./starlink.30s.py --debug`
Expected: pretty-printed JSON of the parsed status (real field values).

- [ ] **Step 4: Verify graceful degradation when off the Starlink LAN**

Run (simulating unreachable by pointing at a dead port): `uv run ./starlink.30s.py` after temporarily editing `DISH_ADDR` to `192.0.2.1:9200`, OR while disconnected from the dish.
Expected: first line `🛰 – | color=#888888` and `Dish not reachable` within ~4 seconds. Restore `DISH_ADDR` afterward.

- [ ] **Step 5: Commit**

```bash
git add starlink.30s.py
git commit -m "feat: add live gRPC fetch and plugin entrypoint"
```

---

### Task 5: Deploy to SwiftBar + README

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: the finished `starlink.30s.py`.

- [ ] **Step 1: Make the plugin executable and symlink it into SwiftBar**

```bash
chmod +x ./starlink.30s.py
ln -sf "$(pwd)/starlink.30s.py" ~/Applications/SwiftBar/starlink.30s.py
```

Expected: `ls -l ~/Applications/SwiftBar/starlink.30s.py` shows a symlink to the repo file.

- [ ] **Step 2: Refresh SwiftBar and verify the menu-bar item**

Open SwiftBar's menu → **Refresh All**, or run `open -a SwiftBar`.
Expected: a `🛰` item appears in the menu bar showing `Connected`; clicking it shows latency, throughput, obstruction, uptime, alerts, and the "Open Starlink UI" / "Refresh" actions.

- [ ] **Step 3: Write the README**

Create `README.md`:

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add README and SwiftBar install instructions"
```

---

## Self-Review

**Spec coverage:**
- Single uv script w/ reflection → Tasks 1, 4 ✓
- Menu-bar glance = connection state → `state_word`, Task 2/3 ✓
- Dropdown: latency+throughput, obstruction+signal, uptime, alerts → `render`, Task 3 ✓
- Error handling (unreachable / parse error / no traceback) → Task 3 (`None`/error render), Task 4 (`fetch_status` catch, `main` catch) ✓
- Testing: pure `render(status|None)`, fixtures, `--debug` → Tasks 1–3 tests, Task 4 `--debug` ✓
- Out-of-scope items (history, config, control) → not implemented ✓

**Placeholder scan:** No TBD/TODO; all steps contain complete code. ✓

**Type consistency:** `state_word` returns `(word, color)` used by `render`; `active_alerts` returns `list[str]` used by `render`; `humanize_uptime` accepts int or str (tested both); `fetch_status` returns `dict | None` consumed by `main`→`render`. ✓
