from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from .delivery import AlertSender
from .detector import Detector, DetectorConfig
from .models import parse_line
from .sources import demo_stream, follow_file, follow_journal


@dataclass(frozen=True)
class SourceConfig:
    kind: str = "journal"
    path: str = ""
    from_start: bool = False
    unit: str = ""
    user: bool = False


class Monitor(threading.Thread):
    def __init__(self, source: SourceConfig, config: DetectorConfig, sender: AlertSender):
        super().__init__(name="log-monitor", daemon=True)
        self.source, self.sender = source, sender
        self.detector = Detector(config)
        self.stop_event = threading.Event()
        self.ui_events: queue.Queue = queue.Queue(maxsize=2000)
        self.alert_events: queue.Queue = queue.Queue(maxsize=500)
        self.messages: queue.Queue = queue.Queue(maxsize=100)
        self.lock = threading.Lock()
        self.metrics = self.detector.snapshot()
        self.ui_dropped = 0

    def status(self, message: str):
        try:
            self.messages.put_nowait(message)
        except queue.Full:
            pass

    def snapshot(self):
        with self.lock:
            return {**self.metrics, "ui_dropped": self.ui_dropped}

    @staticmethod
    def _put_recent(target: queue.Queue, value):
        try:
            target.put_nowait(value)
            return False
        except queue.Full:
            try:
                target.get_nowait()
            except queue.Empty:
                pass
            target.put_nowait(value)
            return True

    def run(self):
        label = self.source.path if self.source.kind == "file" else self.source.kind
        try:
            if self.source.kind == "file":
                stream = follow_file(self.source.path, self.stop_event, self.source.from_start, self.status)
            elif self.source.kind == "journal":
                stream = follow_journal(self.stop_event, self.source.unit, self.source.user, self.status)
            elif self.source.kind == "demo":
                stream = demo_stream(self.stop_event)
            else:
                raise ValueError("Unknown source")
            try:
                for line in stream:
                    if self.stop_event.is_set():
                        break
                    if line is None:
                        alerts = self.detector.tick()
                    else:
                        event = parse_line(line, label)
                        alerts = self.detector.process(event)
                        dropped = self._put_recent(self.ui_events, event)
                        if dropped:
                            with self.lock:
                                self.ui_dropped += 1
                    for alert in alerts:
                        self.sender.submit(alert)
                        self._put_recent(self.alert_events, alert)
                    with self.lock:
                        self.metrics = self.detector.snapshot()
            finally:
                stream.close()
        except Exception as exc:
            self.status(f"Monitoring stopped: {type(exc).__name__}: {exc}")
        finally:
            self.stop_event.set()
