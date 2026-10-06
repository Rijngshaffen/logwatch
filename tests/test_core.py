import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logwatch.delivery import AlertSender, DeliveryConfig
from logwatch.detector import Detector, DetectorConfig, normalize
from logwatch.models import parse_line
from logwatch.monitor import Monitor, SourceConfig
from logwatch.sources import LineFramer, follow_file


def event(message="Completed job 123", level="info"):
    return parse_line(json.dumps(dict(message=message, level=level, service="test.service")), "test")


class ParserTests(unittest.TestCase):
    def test_syslog_and_malformed_json(self):
        parsed = parse_line("Oct  6 12:01:03 host sshd[42]: Failed password for invalid user admin", "auth.log")
        self.assertEqual(parsed.service, "sshd")
        self.assertEqual(parsed.level, "error")
        self.assertEqual(parse_line("{bad json", "log").message, "{bad json")

    def test_journal_fields_and_binary_message(self):
        parsed = parse_line(json.dumps({"MESSAGE": [69, 82, 82, 79, 82], "PRIORITY": "2",
                                       "_SYSTEMD_UNIT": "kernel.service", "__REALTIME_TIMESTAMP": "1000000"}), "journal")
        self.assertEqual(parsed.message, "ERROR")
        self.assertEqual(parsed.level, "critical")
        self.assertTrue(parsed.timestamp.startswith("1970-01-01T00:00:01"))
        for priority in ([], {}, "bad"):
            self.assertEqual(parse_line(json.dumps({"PRIORITY": priority, "MESSAGE": "normal"}), "journal").level, "info")

    def test_normalization(self):
        self.assertEqual(normalize("Worker 812 from 192.0.2.1 at 0xabc failed"),
                         normalize("Worker 990 from 203.0.113.2 at 0xdef failed"))
        self.assertNotEqual(normalize("worker failed"), normalize("worker recovered"))

    def test_critical_words_and_syslog_priority(self):
        self.assertEqual(parse_line("FATAL service halted", "file").level, "critical")
        self.assertEqual(parse_line("<26>Oct  6 12:01:03 host worker: service halted", "file").level, "critical")
        frame = LineFramer()
        parsed = parse_line(frame.feed(b"x" * 70000 + b"\n")[0], "file")
        self.assertIn("record truncated", parsed.message)

    def test_line_framer_partial_utf8_and_limits(self):
        frame = LineFramer(limit=8)
        self.assertEqual(frame.feed(b"a\xc3"), [])
        self.assertEqual(frame.feed(b"\xa9\nnext\n"), ["aé", "next"])
        self.assertEqual(frame.feed(b"0123456789"), [])
        self.assertLessEqual(len(frame.pending), 8)
        self.assertIn("truncated", frame.feed(b"extra\n")[0])
        self.assertEqual(frame.feed(b"ok\n"), ["ok"])


class DetectorTests(unittest.TestCase):
    def test_warmup_novelty_cooldown_and_escalation(self):
        detector = Detector(DetectorConfig(warmup_events=3), now=0)
        for i in range(3):
            self.assertEqual(detector.process(event(f"Completed job {i}"), now=i), [])
        novel = detector.process(event("Supervisor restarted unexpectedly"), now=3)
        self.assertEqual(novel[0]["score"], 65)
        self.assertEqual(detector.process(event("Supervisor restarted unexpectedly"), now=4), [])
        first = detector.process(event("worker failed", "error"), now=5)
        self.assertEqual(first[0]["score"], 65)
        self.assertEqual(detector.process(event("worker failed", "error"), now=6), [])
        self.assertEqual(detector.process(event("worker failed", "critical"), now=7)[0]["score"], 90)

    def test_rules_during_warmup_and_threshold(self):
        detector = Detector(now=0)
        alert = detector.process(event("Out of memory: oom-killer invoked"), now=0)[0]
        self.assertEqual(alert["severity"], "critical")
        self.assertEqual(alert["reasons"][0]["type"], "resource_exhaustion")
        json.dumps(alert, allow_nan=False)
        strict = Detector(DetectorConfig(threshold=96), now=0)
        self.assertEqual(strict.process(event("Out of memory"), now=0), [])

    def test_volume_and_error_spikes(self):
        detector = Detector(DetectorConfig(warmup_events=10, cooldown_seconds=0), now=0)
        for window in range(6):
            for i in range(10):
                detector.process(event(), now=window * 10 + 1)
            self.assertEqual(detector.tick((window + 1) * 10), [])
        for i in range(40):
            detector.process(event("worker failed", "error"), now=61)
        alerts = detector.tick(70)
        types = {reason["type"] for reason in alerts[0]["reasons"]}
        self.assertEqual(types, {"volume_spike", "error_rate_spike"})
        self.assertEqual(alerts[0]["reasons"][0]["baseline_median"], 10)

    def test_idle_tick_and_bounded_state(self):
        detector = Detector(DetectorConfig(max_templates=4, warmup_events=1), now=0)
        for i in range(20):
            detector.process(event("new word " + chr(65 + i)), now=i / 10)
        self.assertLessEqual(len(detector.templates), 4)
        self.assertLessEqual(len(detector.cooldowns), 4)
        self.assertEqual(detector.tick(1000000), [])
        self.assertLessEqual(len(detector.volumes), 60)


class SourceTests(unittest.TestCase):
    def test_append_partial_rotation_and_copytruncate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            path.write_bytes(b"existing\n")
            stop = threading.Event()
            statuses = []
            stream = follow_file(str(path), stop, status=statuses.append)
            self.assertIsNone(next(stream))
            with path.open("ab") as output:
                output.write(b"new ")
            self.assertIsNone(next(stream))
            with path.open("ab") as output:
                output.write(b"line\n")
            self.assertEqual(next(stream), "new line")
            self.assertIsNone(next(stream))
            path.rename(path.with_suffix(".old"))
            path.write_text("rotated\n")
            self.assertEqual(next(stream), "rotated")
            self.assertIsNone(next(stream))
            # Truncate and regrow beyond the prior offset before a poll.
            path.write_text("rewritten longer content\n")
            self.assertEqual(next(stream), "rewritten longer content")
            self.assertTrue(any("rotated" in s for s in statuses))
            self.assertTrue(any("truncated" in s for s in statuses))
            stop.set()
            self.assertRaises(StopIteration, next, stream)

    def test_from_start_missing_and_fifo(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            path.write_text("first\nsecond\n")
            stream = follow_file(str(path), threading.Event(), from_start=True)
            self.assertEqual(next(stream), "first")
            self.assertEqual(next(stream), "second")
            stream.close()
            self.assertRaises(ValueError, next, follow_file(str(path.parent / "absent"), threading.Event()))
            fifo = path.parent / "pipe"
            os.mkfifo(fifo)
            self.assertRaises(ValueError, next, follow_file(str(fifo), threading.Event()))


class Receiver(BaseHTTPRequestHandler):
    status_code = 200
    requests = []
    def do_POST(self):
        type(self).requests.append((dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
        status = type(self).status_code
        if isinstance(status, list):
            status = status.pop(0) if len(status) > 1 else status[0]
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "/other")
        self.end_headers()
    def log_message(self, *_):
        pass


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = str(Path(self.temp.name) / "alerts.jsonl")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        Receiver.requests = []
        Receiver.status_code = 200
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/alerts"
        self.sender = None

    def tearDown(self):
        if self.sender:
            self.sender.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join()
        self.temp.cleanup()

    def make_sender(self, endpoint=None):
        self.messages = []
        self.sender = AlertSender(DeliveryConfig(self.output, endpoint or self.endpoint, "test-token"), self.messages.append)
        self.sender.start()
        return self.sender

    def send_one(self):
        alert = Detector(now=0).process(event("kernel panic"), now=0)[0]
        self.sender.submit(alert)
        self.sender.pending.join()
        return alert

    def test_json_persistence_and_http_headers(self):
        self.make_sender()
        alert = self.send_one()
        self.assertEqual(json.loads(Path(self.output).read_text()), alert)
        headers, payload = Receiver.requests[0]
        self.assertEqual(json.loads(payload), alert)
        self.assertEqual(headers["Idempotency-Key"], alert["alert_id"])
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(self.sender.snapshot()["delivered"], 1)

    def test_transient_retry_reuses_id_and_permanent_error(self):
        Receiver.status_code = [503, 200]
        self.make_sender()
        self.send_one()
        self.assertEqual(len(Receiver.requests), 2)
        self.assertEqual(Receiver.requests[0][0]["Idempotency-Key"], Receiver.requests[1][0]["Idempotency-Key"])
        Receiver.requests = []
        Receiver.status_code = 400
        self.send_one()
        self.assertEqual(len(Receiver.requests), 1)
        self.assertEqual(self.sender.snapshot()["failed"], 1)

    def test_redirect_not_followed(self):
        Receiver.status_code = 302
        self.make_sender()
        self.send_one()
        self.assertEqual(len(Receiver.requests), 1)
        self.assertEqual(self.sender.snapshot()["failed"], 1)

    def test_queue_saturation_retains_local_alert(self):
        self.sender = AlertSender(DeliveryConfig(self.output, self.endpoint), lambda _: None)
        # No sender thread consumes the queue in this deterministic capacity check.
        alert = Detector(now=0).process(event("kernel panic"), now=0)[0]
        for _ in range(257):
            self.sender.submit(alert)
        self.assertEqual(self.sender.snapshot()["dropped"], 1)
        self.assertEqual(len(Path(self.output).read_text().splitlines()), 257)
        self.sender.start()
        self.sender.stop_event.set()

    def test_endpoint_validation(self):
        for endpoint in ("file:///tmp/log", "https://user:pass@example.org", "http://host:bad", "http://host/#secret"):
            self.assertRaises(ValueError, DeliveryConfig(self.output, endpoint).validate)


class MonitorTests(unittest.TestCase):
    def test_end_to_end_file_and_prompt_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.log"
            source.write_text("INFO worker completed\nOut of memory: oom-killer\n")
            output = Path(directory) / "alerts.jsonl"
            sender = AlertSender(DeliveryConfig(str(output)), lambda _: None)
            sender.start()
            monitor = Monitor(SourceConfig("file", str(source), True), DetectorConfig(), sender)
            monitor.start()
            deadline = time.monotonic() + 3
            while monitor.snapshot()["events"] < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            monitor.stop_event.set()
            monitor.join(timeout=2)
            sender.close()
            self.assertFalse(monitor.is_alive())
            self.assertEqual(monitor.snapshot()["events"], 2)
            alert = json.loads(output.read_text())
            self.assertEqual(alert["score"], 95)
            self.assertEqual(alert["event"]["source"], str(source))


if __name__ == "__main__":
    unittest.main()
