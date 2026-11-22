"""Unit tests for the Starlink SwiftBar plugin.

Run with the standard library test runner (no third-party deps):

    python3 -m unittest discover -s tests -v

The plugin's own doctests are collected via the ``load_tests`` protocol at the
bottom of this module, so the same command runs them too.
"""

import contextlib
import doctest
import importlib.util
import io
import pathlib
import unittest
from unittest import mock

_PLUGIN = pathlib.Path(__file__).resolve().parent.parent / "starlink.30s.py"


def load_plugin():
    """Load the dotted-filename plugin as a module (can't be a plain import)."""
    spec = importlib.util.spec_from_file_location("starlink_plugin", _PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plugin = load_plugin()


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


class HumanizeUptimeTests(unittest.TestCase):
    def test_minutes_only(self):
        self.assertEqual(plugin.humanize_uptime(4062), "1h 7m")

    def test_zero(self):
        self.assertEqual(plugin.humanize_uptime(0), "0m")

    def test_days(self):
        self.assertEqual(plugin.humanize_uptime(93784), "1d 2h 3m")

    def test_accepts_string(self):
        self.assertEqual(plugin.humanize_uptime("4062"), "1h 7m")


class ActiveAlertsTests(unittest.TestCase):
    def test_none_when_healthy(self):
        self.assertEqual(plugin.active_alerts(HEALTHY), [])

    def test_lists_true_bools(self):
        status = {"alerts": {"thermal_throttle": True, "roaming": True}}
        result = plugin.active_alerts(status)
        self.assertIn("Thermal throttle", result)
        self.assertIn("Roaming", result)
        self.assertEqual(len(result), 2)

    def test_includes_pending_software_update(self):
        status = {"alerts": {}, "software_update_state": "DOWNLOADING"}
        self.assertTrue(
            any("Software update" in a for a in plugin.active_alerts(status))
        )

    def test_swupdate_reboot_ready(self):
        status = {"alerts": {}, "swupdate_reboot_ready": True}
        self.assertIn(
            "Software update ready (reboot)", plugin.active_alerts(status)
        )


class StateWordTests(unittest.TestCase):
    def test_connected(self):
        self.assertEqual(plugin.state_word(HEALTHY), ("Connected", "#3cb371"))

    def test_alert(self):
        status = {"alerts": {"thermal_throttle": True},
                  "disablement_code": "OKAY"}
        self.assertEqual(plugin.state_word(status), ("Alert", "orange"))

    def test_disabled(self):
        status = {"alerts": {}, "disablement_code": "NO_ACTIVE_ACCOUNT"}
        self.assertEqual(plugin.state_word(status), ("Disabled", "red"))

    def test_offline_on_outage(self):
        status = {"alerts": {}, "disablement_code": "OKAY",
                  "outage": {"cause": "NO_SCHEDULE"}}
        self.assertEqual(plugin.state_word(status), ("Offline", "red"))


class PingSuccessPctTests(unittest.TestCase):
    def test_computes_mean(self):
        # MessageToDict renders the uint64 sample counter as a string.
        hist = {"current": "4", "pop_ping_drop_rate": [0.0, 0.0, 0.5, 0.5]}
        self.assertEqual(plugin.ping_success_pct(hist), 75.0)

    def test_none_when_empty(self):
        self.assertIsNone(plugin.ping_success_pct({}))
        self.assertIsNone(plugin.ping_success_pct({"pop_ping_drop_rate": []}))

    def test_ignores_unfilled_slots_after_reboot(self):
        # Only 2 samples taken so far; the trailing zeros are unwritten slots,
        # not 0%-drop samples.
        hist = {"current": "2", "pop_ping_drop_rate": [0.5, 0.5, 0.0, 0.0]}
        self.assertEqual(plugin.ping_success_pct(hist), 50.0)

    def test_none_when_no_samples_taken(self):
        # current == 0 is omitted by MessageToDict; the buffer is all unwritten.
        hist = {"pop_ping_drop_rate": [0.0] * 900}
        self.assertIsNone(plugin.ping_success_pct(hist))

    def test_uses_only_last_15_minutes_of_longer_buffer(self):
        # 1000-slot ring, 1100 samples taken: sample i lives at i % 1000.
        # The last 900 samples (200..1099) occupy slots 200..999 and 0..99;
        # slots 100..199 still hold samples 100..199, which are too old.
        drops = [0.0] * 1000
        for slot in range(100, 200):
            drops[slot] = 1.0
        hist = {"current": "1100", "pop_ping_drop_rate": drops}
        self.assertEqual(plugin.ping_success_pct(hist), 100.0)


class RenderTests(unittest.TestCase):
    def test_healthy(self):
        out = plugin.render(HEALTHY)
        lines = out.splitlines()
        self.assertEqual(lines[0], "🛰 🟢 93.9%")
        self.assertIn("---", lines)
        self.assertIn("Connected | color=#3cb371", out)
        self.assertIn("Ping success (15m): 93.9%", out)
        self.assertIn("Latency: 19 ms  ·  Drop: 0.0%", out)
        self.assertIn("↓ 18.2 Mbps   ↑ 0.8 Mbps", out)
        self.assertIn("Obstruction: 42.8%", out)
        self.assertIn("Uptime: 1h 7m", out)
        self.assertIn("Alerts: none", out)
        self.assertIn("Open Starlink UI | href=http://192.168.100.1", out)
        self.assertIn("Refresh | refresh=true", out)

    def test_alert_lists_alerts(self):
        status = dict(HEALTHY, alerts={"thermal_throttle": True})
        out = plugin.render(status)
        self.assertEqual(out.splitlines()[0], "🛰 🟠 93.9%")
        self.assertIn("Alert | color=orange", out)
        self.assertIn("⚠ Thermal throttle | color=orange", out)
        self.assertNotIn("Alerts: none", out)

    def test_unreachable(self):
        out = plugin.render(None)
        lines = out.splitlines()
        self.assertEqual(lines[0], "🛰 ⚪️")
        self.assertIn("Dish not reachable", out)
        self.assertIn("Refresh | refresh=true", out)

    def test_error_has_no_traceback(self):
        out = plugin.render(None, error="boom")
        lines = out.splitlines()
        self.assertEqual(lines[0], "🛰 ⚠️")
        self.assertIn("Error: boom | color=red", out)

    def test_missing_fields_do_not_crash(self):
        # MessageToDict omits zero/empty fields; render must tolerate a bare dict.
        out = plugin.render({"alerts": {}, "disablement_code": "OKAY"})
        # no ping_success_15m key -> menu bar shows the dot alone, no percentage
        self.assertEqual(out.splitlines()[0], "🛰 🟢")
        self.assertIn("Latency: — ms", out)
        self.assertIn("Uptime: 0m", out)


class ErrorTextTests(unittest.TestCase):
    def test_multiline_message_reduced_to_first_line(self):
        exc = Exception("<_InactiveRpcError of RPC that terminated with:\n"
                        "\tstatus = StatusCode.UNIMPLEMENTED\n\tdetails = x>")
        self.assertEqual(plugin.error_text(exc),
                         "<_InactiveRpcError of RPC that terminated with:")

    def test_prefers_grpc_details(self):
        class FakeRpcError(Exception):
            def details(self):
                return "Method not found"
        self.assertEqual(plugin.error_text(FakeRpcError("noisy\nrepr")),
                         "Method not found")

    def test_pipe_cannot_inject_swiftbar_params(self):
        self.assertNotIn("|", plugin.error_text(Exception("a | href=x")))

    def test_truncates_long_messages(self):
        self.assertLessEqual(len(plugin.error_text(Exception("x" * 500))), 120)

    def test_empty_message_falls_back_to_type_name(self):
        self.assertEqual(plugin.error_text(KeyError()), "KeyError")


class MainTests(unittest.TestCase):
    def test_fetch_error_renders_single_error_line(self):
        def failing_fetch():
            raise RuntimeError("line one | color=green\nline two")
        out = io.StringIO()
        with mock.patch.object(plugin, "fetch_status", failing_fetch), \
                contextlib.redirect_stdout(out):
            plugin.main([])
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "🛰 ⚠️")
        self.assertEqual(lines[2].count("|"), 1)
        self.assertTrue(lines[2].startswith("Error: line one"))
        self.assertTrue(lines[2].endswith("| color=red"))
        self.assertNotIn("line two", out.getvalue())


def load_tests(loader, tests, ignore):
    """unittest hook: also run the plugin module's doctests."""
    tests.addTests(doctest.DocTestSuite(plugin))
    return tests


if __name__ == "__main__":
    unittest.main()
