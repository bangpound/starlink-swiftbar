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
    "ping_success_15m": 93.9,
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


def test_active_alerts_swupdate_reboot_ready():
    status = {"alerts": {}, "swupdate_reboot_ready": True}
    assert "Software update ready (reboot)" in plugin.active_alerts(status)


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


def test_render_healthy():
    out = plugin.render(HEALTHY)
    lines = out.splitlines()
    assert lines[0] == "🛰 🟢 93.9%"
    assert "---" in lines
    assert "Connected | color=#3cb371" in out
    assert "Ping success (15m): 93.9%" in out
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
    assert out.splitlines()[0] == "🛰 🟠 93.9%"
    assert "Alert | color=orange" in out
    assert "⚠ Thermal throttle | color=orange" in out
    assert "Alerts: none" not in out


def test_render_unreachable():
    out = plugin.render(None)
    lines = out.splitlines()
    assert lines[0] == "🛰 ⚪️"
    assert "Dish not reachable" in out
    assert "Refresh | refresh=true" in out


def test_render_error_has_no_traceback():
    out = plugin.render(None, error="boom")
    lines = out.splitlines()
    assert lines[0] == "🛰 ⚠️"
    assert "Error: boom | color=red" in out


def test_render_missing_fields_do_not_crash():
    # MessageToDict omits zero/empty fields; render must tolerate a bare dict.
    out = plugin.render({"alerts": {}, "disablement_code": "OKAY"})
    # no ping_success_15m key -> menu bar shows the dot alone, no percentage
    assert out.splitlines()[0] == "🛰 🟢"
    assert "Latency: — ms" in out
    assert "Uptime: 0m" in out


def test_ping_success_pct_computes_mean():
    hist = {"pop_ping_drop_rate": [0.0, 0.0, 0.5, 0.5]}
    assert plugin.ping_success_pct(hist) == 75.0


def test_ping_success_pct_none_when_empty():
    assert plugin.ping_success_pct({}) is None
    assert plugin.ping_success_pct({"pop_ping_drop_rate": []}) is None
