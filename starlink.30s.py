#!/opt/homebrew/bin/uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["grpcio", "yagrc"]
# ///
# <xbar.title>Starlink Status</xbar.title>
# <xbar.version>1.0.0</xbar.version>
# <xbar.author>Benjamin Doherty</xbar.author>
# <xbar.author.github>bangpound</xbar.author.github>
# <xbar.desc>Starlink dish status in the menu bar: 15-minute ping success rate, connection state, latency, throughput, obstruction, uptime, and alerts. Reads the dish gRPC API at 192.168.100.1:9200.</xbar.desc>
# <xbar.dependencies>python,uv</xbar.dependencies>
# <xbar.abouturl>http://192.168.100.1</xbar.abouturl>
# <swiftbar.hideAbout>false</swiftbar.hideAbout>
"""SwiftBar plugin: Starlink dish status in the macOS menu bar."""

import sys

DISH_ADDR = "192.168.100.1:9200"
DEADLINE_S = 4.0


def humanize_uptime(seconds: int | str) -> str:
    """Format an uptime in seconds as a compact d/h/m string.

    Minutes are always shown; larger units only when non-zero.

    >>> humanize_uptime(4062)
    '1h 7m'
    >>> humanize_uptime(0)
    '0m'
    >>> humanize_uptime(93784)
    '1d 2h 3m'
    >>> humanize_uptime("4062")
    '1h 7m'
    """
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


ALERT_LABELS = {
    "motors_stuck": "Motors stuck",
    "thermal_throttle": "Thermal throttle",
    "thermal_shutdown": "Thermal shutdown",
    "mast_not_near_vertical": "Mast not vertical",
    "unexpected_location": "Unexpected location",
    "slow_ethernet_speeds": "Slow Ethernet",
    "slow_ethernet_speeds_100": "Ethernet limited to 100M",
    "roaming": "Roaming",
    "power_supply_thermal_throttle": "Power supply throttle",
    "dbf_telem_stale": "Telemetry stale",
    "low_motor_current": "Low motor current",
    "lower_signal_than_predicted": "Signal lower than predicted",
    "obstruction_map_reset": "Obstruction map reset",
    "dish_water_detected": "Water in dish",
    "router_water_detected": "Water in router",
    "upsu_router_port_slow": "Router port slow",
    "no_ethernet_link": "No Ethernet link",
}


# Dish alert flags that describe normal operation rather than a fault: shown
# in the dropdown, but they don't put the menu bar into the Alert state.
INFO_LABELS = {
    "install_pending": "Install pending",
    "is_heating": "Heating (snow melt)",
    "is_power_save_idle": "Power save idle",
}


def active_alerts(status) -> list[str]:
    alerts = status.get("alerts", {})
    return [label for key, label in ALERT_LABELS.items() if alerts.get(key)]


def info_notices(status) -> list[str]:
    alerts = status.get("alerts", {})
    out = [label for key, label in INFO_LABELS.items() if alerts.get(key)]
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


# Menu-bar state is signalled by a colored dot emoji (legible on any menu-bar
# background) rather than colored text, which uses the system default color so
# it stays readable in light and dark menu bars. Keyed by state word so the
# dropdown text color can change without affecting the dot.
STATE_DOTS = {"Connected": "🟢", "Alert": "🟠", "Offline": "🔴", "Disabled": "🔴"}


WINDOW_S = 15 * 60  # history samples are 1/s


def ping_success_pct(history):
    """15-minute ping success rate (%) from a get_history dict, or None.

    The dish keeps its own ring buffer of per-second ping drop rates, so no
    state needs to be stored locally. ``current`` is the total number of
    samples ever taken; sample ``i`` lives at slot ``i % len(buffer)``. Only
    the most recent ``min(current, len, 900)`` samples are averaged, so
    unwritten slots after a reboot and anything older than 15 minutes in a
    longer buffer are ignored. Success = 1 - mean(drop).

    >>> ping_success_pct({"current": "4",
    ...                   "pop_ping_drop_rate": [0.0, 0.0, 0.5, 0.5]})
    75.0
    >>> ping_success_pct({}) is None
    True
    >>> ping_success_pct({"current": "3", "pop_ping_drop_rate": []}) is None
    True
    """
    drops = history.get("pop_ping_drop_rate") or []
    # MessageToDict renders uint64 as a string and omits it when zero.
    current = int(history.get("current", 0))
    count = min(current, len(drops), WINDOW_S)
    if count == 0:
        return None
    recent = [drops[(current - k) % len(drops)] for k in range(1, count + 1)]
    return (1.0 - sum(recent) / count) * 100.0


def _actions():
    return [
        "---",
        "Open Starlink UI | href=http://192.168.100.1",
        "Refresh | refresh=true",
    ]


def render(status, error=None) -> str:
    lines = []
    if error is not None:
        lines.append("🛰 ⚠️")
        lines.append("---")
        lines.append(f"Error: {error} | color=red")
        lines.extend(_actions())
        return "\n".join(lines)

    if status is None:
        lines.append("🛰 ⚪️")
        lines.append("---")
        lines.append("Dish not reachable")
        lines.append("(not connected to Starlink LAN) | color=#888888")
        lines.extend(_actions())
        return "\n".join(lines)

    word, color = state_word(status)
    dot = STATE_DOTS[word]
    pct = status.get("ping_success_15m")
    lines.append(f"🛰 {dot} {pct:.1f}%" if pct is not None else f"🛰 {dot}")
    lines.append("---")

    # The descriptive state word lives in the dropdown now (the dot carries
    # current state in the menu bar); color is legible on the dropdown bg.
    lines.append(f"{word} | color={color}")
    if pct is not None:
        lines.append(f"Ping success (15m): {pct:.1f}%")

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

    notices = info_notices(status)
    if notices:
        lines.append("Info:")
        for notice in notices:
            lines.append(f"ℹ {notice}")

    lines.extend(_actions())
    return "\n".join(lines)


def fetch_status(addr=DISH_ADDR, timeout=DEADLINE_S, keep_history=False):
    """Dish status dict (from get_status), or None if the dish is unreachable.

    Adds ``ping_success_15m`` from get_history; with ``keep_history`` the raw
    parsed history is also attached as ``dish_get_history`` (for --debug).
    """
    import grpc
    from google.protobuf.json_format import MessageToDict
    from yagrc import reflector as yagrc_reflector

    channel = grpc.insecure_channel(addr)
    try:
        # Reflection uses yagrc's own QUERY_TIMEOUT (10 s), not `timeout`, so
        # the worst case is ~10 + 2 * timeout = 18 s: still under the 30 s
        # refresh. Off the Starlink LAN the connect usually fails fast with
        # UNAVAILABLE instead.
        reflector = yagrc_reflector.GrpcReflectionClient()
        reflector.load_protocols(channel, symbols=["SpaceX.API.Device.Device"])
        stub_class = reflector.service_stub_class("SpaceX.API.Device.Device")
        request_class = reflector.message_class("SpaceX.API.Device.Request")
        stub = stub_class(channel)
        response = stub.Handle(request_class(get_status={}), timeout=timeout)
        # 15-minute ping history is best-effort: a failure here must not lose
        # the status we already have.
        try:
            hist_response = stub.Handle(request_class(get_history={}),
                                        timeout=timeout)
        except grpc.RpcError:
            hist_response = None
    except grpc.RpcError as exc:
        if exc.code() in (grpc.StatusCode.UNAVAILABLE,
                          grpc.StatusCode.DEADLINE_EXCEEDED):
            return None
        raise
    finally:
        channel.close()

    parsed = MessageToDict(response, preserving_proto_field_name=True)
    status = parsed.get("dish_get_status", {})
    if hist_response is not None:
        history = MessageToDict(
            hist_response, preserving_proto_field_name=True
        ).get("dish_get_history", {})
        status["ping_success_15m"] = ping_success_pct(history)
        if keep_history:
            status["dish_get_history"] = history
    return status


ERROR_TEXT_MAX = 120


def error_text(exc) -> str:
    """One-line, SwiftBar-safe description of an exception.

    gRPC errors expose a clean ``details()``; their ``str()`` is a multi-line
    repr. Newlines would become extra menu items and ``|`` would start
    SwiftBar parameters, so keep the first line, neutralize ``|`` and cap
    the length.

    >>> error_text(ValueError("bad\\nthings | color=green"))
    'bad'
    """
    details = getattr(exc, "details", None)
    text = (details() if callable(details) else None) or str(exc)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    text = lines[0] if lines else type(exc).__name__
    text = text.replace("|", "¦")
    if len(text) > ERROR_TEXT_MAX:
        text = text[:ERROR_TEXT_MAX - 1] + "…"
    return text


def main(argv: list[str]) -> int:
    """Run the plugin with command-line arguments ``argv``; return exit code.

    Menu mode always exits 0 once a menu is printed, including the error and
    unreachable menus: SwiftBar treats a non-zero exit as a plugin failure.
    """
    if "--debug" in argv:
        # Debugging wants the real traceback and the raw history, not the
        # menu-bar rendering.
        import json
        status = fetch_status(keep_history=True)
        if status is None:
            print(f"dish not reachable at {DISH_ADDR}", file=sys.stderr)
            return 1
        print(json.dumps(status, indent=2))
        return 0
    try:
        status = fetch_status()
    except Exception as exc:  # noqa: BLE001 -- never leak a traceback to the menu bar
        print(render(None, error=error_text(exc)))
        return 0
    print(render(status))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
