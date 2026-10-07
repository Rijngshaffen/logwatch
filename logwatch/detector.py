"""Bounded, adaptive baseline using normalized templates and median/MAD windows."""
from __future__ import annotations

import re
import socket
import statistics
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass

from .models import LogEvent, utc_now


@dataclass(frozen=True)
class DetectorConfig:
    warmup_events: int = 100
    window_seconds: float = 10
    baseline_windows: int = 60
    min_windows: int = 6
    threshold: int = 60
    cooldown_seconds: float = 60
    max_templates: int = 4096

    def __post_init__(self):
        if self.warmup_events < 1 or self.window_seconds <= 0 or self.min_windows < 3:
            raise ValueError("Warmup, window duration, and minimum windows must be positive")
        if self.baseline_windows < self.min_windows or self.max_templates < 1:
            raise ValueError("Baseline capacity is too small")
        if not 1 <= self.threshold <= 100 or self.cooldown_seconds < 0:
            raise ValueError("Invalid alert threshold or cooldown")


RULES = [
    ("kernel_failure", 98, re.compile(r"(?:\b(kernel panic|segfault|segmentation fault)\b|(?-i:\bBUG:))", re.I)),
    ("resource_exhaustion", 95, re.compile(r"\b(out of memory|oom[- ]killer|no space left on device|disk full)\b", re.I)),
    ("storage_failure", 92, re.compile(r"\b(I/O error|filesystem corruption|read-only file system)\b", re.I)),
    ("authentication_failure", 70, re.compile(r"\b(failed password|authentication failure|invalid user|permission denied)\b", re.I)),
]


def normalize(message: str) -> str:
    text = message.lower()
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<uuid>", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", text)
    text = re.sub(r"\b0x[0-9a-f]+\b", "<hex>", text)
    text = re.sub(r"\b\d+\b", "<n>", text)
    return re.sub(r"\s+", " ", text).strip()[:2048]


class Detector:
    def __init__(self, config: DetectorConfig | None = None, now: float | None = None):
        self.config = config or DetectorConfig()
        self.events = 0
        self.alerts = 0
        self.suppressed = 0
        self.templates: OrderedDict[str, int] = OrderedDict()
        self.cooldowns: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self.volumes = deque(maxlen=self.config.baseline_windows)
        self.ratios = deque(maxlen=self.config.baseline_windows)
        self.window_start = time.monotonic() if now is None else now
        self.count = self.errors = 0
        self.last_event: LogEvent | None = None

    @property
    def ready(self) -> bool:
        return self.events >= self.config.warmup_events

    def snapshot(self) -> dict:
        return dict(events=self.events, alerts=self.alerts, suppressed=self.suppressed,
                    templates=len(self.templates), ready=self.ready,
                    warmup_events=self.config.warmup_events, baseline_windows=len(self.volumes))

    def _alert(self, event: LogEvent, score: int, reasons: list[dict], key: str, now: float) -> dict | None:
        if score < self.config.threshold:
            return None
        previous = self.cooldowns.get(key)
        if previous is not None and now - previous[0] < self.config.cooldown_seconds and score <= previous[1]:
            self.suppressed += 1
            return None
        self.cooldowns[key] = (now, score)
        self.cooldowns.move_to_end(key)
        while len(self.cooldowns) > self.config.max_templates:
            self.cooldowns.popitem(last=False)
        self.alerts += 1
        return dict(schema_version="1.0", alert_id=str(uuid.uuid4()), timestamp=utc_now(),
                    host=socket.gethostname(), category="log_anomaly",
                    severity="critical" if score >= 90 else "high" if score >= 75 else "medium",
                    score=score, detector="adaptive-statistical-v1", reasons=reasons,
                    event=event.as_dict(), baseline=self.snapshot())

    def process(self, event: LogEvent, now: float | None = None) -> list[dict]:
        now = time.monotonic() if now is None else now
        alerts = self.tick(now)
        template = event.service + ":" + normalize(event.message)
        seen = self.templates.get(template, 0)
        score, reasons = 0, []
        for name, weight, pattern in RULES:
            if pattern.search(event.message):
                score = max(score, weight)
                reasons.append(dict(type=name, description="Matched a known system failure pattern"))
        if event.level in {"error", "critical"}:
            score = max(score, 90 if event.level == "critical" else 60)
            reasons.append(dict(type="error_severity", level=event.level))
        if self.ready and seen == 0:
            score = max(score, 65)
            reasons.append(dict(type="novel_template", template=template,
                                description="Message template absent from the current learned baseline"))
        self.events += 1
        self.count += 1
        self.errors += event.level in {"error", "critical"}
        self.last_event = event
        self.templates[template] = seen + 1
        self.templates.move_to_end(template)
        while len(self.templates) > self.config.max_templates:
            self.templates.popitem(last=False)
        if reasons:
            alert = self._alert(event, score, reasons, "event:" + template, now)
            if alert:
                alerts.append(alert)
        return alerts

    def tick(self, now: float | None = None) -> list[dict]:
        now = time.monotonic() if now is None else now
        if now - self.window_start < self.config.window_seconds:
            return []
        alerts = self._finish_window(now)
        # Account for idle windows without a loop proportional to elapsed time.
        skipped = int((now - self.window_start) // self.config.window_seconds) - 1
        for _ in range(min(skipped, self.config.baseline_windows)):
            self.volumes.append(0)
        self.window_start += (skipped + 1) * self.config.window_seconds
        self.count = self.errors = 0
        return alerts

    def _finish_window(self, now: float) -> list[dict]:
        reasons, score = [], 0
        if len(self.volumes) >= self.config.min_windows and self.last_event and self.count:
            median = statistics.median(self.volumes)
            mad = statistics.median(abs(n - median) for n in self.volumes)
            limit = max(20, median * 3, median + 6 * max(1, 1.4826 * mad))
            if self.count > limit:
                score = 85
                reasons.append(dict(type="volume_spike", observed=self.count,
                                    baseline_median=median, threshold=round(limit, 2),
                                    window_seconds=self.config.window_seconds))
        if len(self.ratios) >= self.config.min_windows and self.count >= 10:
            ratio = self.errors / self.count
            median = statistics.median(self.ratios)
            mad = statistics.median(abs(n - median) for n in self.ratios)
            limit = min(1.0, max(0.3, median + 6 * max(0.03, 1.4826 * mad)))
            if self.errors >= 5 and ratio > limit:
                score = max(score, 85)
                reasons.append(dict(type="error_rate_spike", observed=round(ratio, 4),
                                    baseline_median=round(median, 4), threshold=round(limit, 4),
                                    error_count=self.errors, event_count=self.count,
                                    window_seconds=self.config.window_seconds))
        # Compare before updating: the anomalous window cannot hide its own spike.
        self.volumes.append(self.count)
        if self.count >= 10:
            self.ratios.append(self.errors / self.count)
        if reasons and self.last_event:
            key = "window:" + ",".join(r["type"] for r in reasons)
            alert = self._alert(self.last_event, score, reasons, key, now)
            return [alert] if alert else []
        return []
