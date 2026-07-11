#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["grpcio", "yagrc"]
# ///
"""SwiftBar plugin: Starlink dish status in the macOS menu bar."""

import sys

DISH_ADDR = "192.168.100.1:9200"
DEADLINE_S = 4.0


def humanize_uptime(seconds: int | str) -> str:
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


def active_alerts(status) -> list[str]:
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


if __name__ == "__main__":
    main()
