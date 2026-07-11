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
