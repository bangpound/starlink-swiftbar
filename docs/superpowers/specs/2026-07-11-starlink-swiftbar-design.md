# Starlink SwiftBar Plugin — Design

**Date:** 2026-07-11
**Status:** Approved

## Goal

A persistent menu-bar widget (SwiftBar) that shows Starlink dish status at a
glance, replacing the need to open the web UI at http://192.168.100.1/. The
menu bar shows connection state; the dropdown shows the useful detail.

## How the dish exposes data

The web UI reads from a gRPC service on the dish at `192.168.100.1:9200`:
service `SpaceX.API.Device.Device`, method `Handle`, request `get_status`. A
single call returns everything this widget needs (state, latency, throughput,
drop rate, obstruction, uptime, alerts).

## Approach (chosen: A — reflection)

A single self-contained `uv` script that fetches the current proto schema from
the dish at runtime via gRPC **server reflection** (using `yagrc`). No
checked-in protobuf stubs to maintain — resilient to Starlink's frequent proto
changes and matches the existing single-file Python plugin style in
`~/Applications/SwiftBar`.

Rejected alternatives:
- **B — vendored/compiled `*_pb2.py` stubs:** faster by one round-trip, but
  must be re-vendored whenever Starlink changes the proto; more files, more
  brittle. Not worth it for a menu-bar widget.
- **C — shell out to `grpcurl`:** `grpcurl` isn't installed and the project
  standard is `uv` Python scripts.

## Architecture & data flow

Single self-contained `uv` script named `starlink.30s.py` (the `.30s.` segment
is SwiftBar's 30-second refresh interval; rename to change it). PEP 723 header:

```
# /// script
# requires-python = ">=3.11"
# dependencies = ["grpcio", "yagrc"]
# ///
```

Each cycle SwiftBar runs `uv run starlink.30s.py`, which:

1. Opens an insecure gRPC channel to `192.168.100.1:9200` with a short deadline
   (~4s).
2. Uses `yagrc` reflection to build the `Device` stub at runtime and calls
   `Handle(get_status=...)`.
3. Reads fields off the `dish_get_status` response into a small plain dict.
4. Prints SwiftBar-formatted output (menu-bar line, `---`, dropdown lines).

Stateless: no stored state, no config file. Runs to completion each cycle.

## Display layout

**Menu bar (glance):** connection state only — icon + one word, color-coded.

**Connected:**
```
🛰 Connected
─────────────────────────────
Latency: 28 ms  ·  Drop: 0.0%
↓ 145.2 Mbps   ↑ 12.4 Mbps
Obstruction: 0.4% (clear)
Uptime: 3d 14h 22m
─────────────────────────────
Alerts: none
─────────────────────────────
Open Starlink UI | href=http://192.168.100.1
Refresh | refresh=true
```

**With an active alert:** the menu-bar word changes (e.g. "Alert") and
turns amber/red; alerts are listed and colored in the dropdown:
```
🛰 Alert
─────────────────────────────
...metrics...
─────────────────────────────
Alerts:
⚠ Thermal throttle | color=orange
⚠ Software update pending | color=orange
```

**Not on the Starlink network** (dish unreachable within deadline) — muted, not
alarming:
```
🛰 –
─────────────────────────────
Dish not reachable
(not connected to Starlink LAN)
─────────────────────────────
Refresh | refresh=true
```

### Field mapping (from a real live `get_status` response, snake_case via
`MessageToDict(..., preserving_proto_field_name=True)`)

> **Note on missing fields:** `MessageToDict` omits any field whose value is
> zero / false / empty. So `pop_ping_drop_rate`, false alert bools, and empty
> sub-messages will be *absent* from the dict. The renderer must use
> `.get(key, default)` everywhere.

- Menu word is **derived** (there is no `state` field on current firmware),
  in priority order:
  1. dish unreachable → `–` (dimmed)
  2. `disablement_code` != `"OKAY"` → "Disabled" (red)
  3. `outage` present → "Offline" (red)
  4. any `alerts.*` bool true → "Alert" (orange)
  5. otherwise → "Connected" (green)
- Latency ← `pop_ping_latency_ms`; Drop ← `pop_ping_drop_rate` (default `0.0`)
- Throughput ← `downlink_throughput_bps` / `uplink_throughput_bps` ÷ 1e6
- Obstruction ← `obstruction_stats.fraction_obstructed` (as %); "clear" when
  no obstruction alert
- Uptime ← `device_state.uptime_s` (a string), humanized (e.g. `3d 14h 22m`)
- Alerts ← the `alerts` sub-message bools. Real field names:
  `motors_stuck`, `thermal_throttle`, `thermal_shutdown`,
  `mast_not_near_vertical`, `unexpected_location`, `slow_ethernet_speeds`,
  `slow_ethernet_speeds_100`, `roaming`, `install_pending`, `is_heating`,
  `power_supply_thermal_throttle`, `is_power_save_idle`, `dbf_telem_stale`,
  `low_motor_current`, `lower_signal_than_predicted`, `obstruction_map_reset`,
  `dish_water_detected`, `router_water_detected`, `upsu_router_port_slow`,
  `no_ethernet_link`. Plus software update: `swupdate_reboot_ready` (bool) and
  `software_update_state` (string, `"IDLE"` when nothing pending).

## Error handling

The plugin must never show a stack trace in the menu bar.

- **Dish unreachable / deadline exceeded** (`grpc.RpcError` with `UNAVAILABLE` /
  `DEADLINE_EXCEEDED`) → the muted "not connected" state. This is the normal
  case when on another network, so it is expected, not an error.
- **Reflection or parsing failure** (a renamed field, unexpected response) →
  menu bar shows a dimmed `🛰 ?`; dropdown shows a one-line error with the
  exception message plus the Refresh / Open UI actions. Any single field we
  cannot read degrades to `—` rather than crashing the whole render.
- **`uv` / dependency resolution failure** → SwiftBar surfaces stderr; the
  script keeps its own output on stdout clean.

## Testing

Network call is separated from parsing/rendering so the logic is testable
without a reachable dish.

- `render(status: dict | None) -> str` is pure: takes a plain dict (or `None`
  for unreachable) and returns the full SwiftBar string.
- Tests feed captured sample responses: healthy dish, each alert type, an
  obstructed dish, and `None` (unreachable) — asserting the menu-bar word,
  colors, and that no exception escapes.
- A `--debug` flag dumps the raw parsed dict for capturing new fixtures against
  the live dish.
- Manual verification: drop the file in `~/Applications/SwiftBar`; confirm it
  renders on the Starlink LAN and degrades gracefully off it.

## Out of scope (YAGNI)

- History / graphing (SwiftBar is a glance widget; the web UI has history).
- Configurable thresholds or a config file.
- Obstruction map imagery.
- Controlling the dish (reboot, stow) — read-only status only.
