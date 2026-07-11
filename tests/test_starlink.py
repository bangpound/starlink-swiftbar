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
