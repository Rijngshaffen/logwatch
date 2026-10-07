from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class LogEvent:
    timestamp: str
    source: str
    service: str
    message: str
    level: str
    raw: str

    def as_dict(self) -> dict:
        return dict(timestamp=self.timestamp, source=self.source, service=self.service,
                    message=self.message, level=self.level, raw=self.raw)


SYSLOG = re.compile(r"^(?:<\d+>)?(?P<stamp>[A-Z][a-z]{2}\s+\d+\s+\d\d:\d\d:\d\d|\d{4}-\d\d-\d\dT\S+)\s+\S+\s+(?P<service>[\w./@-]+)(?:\[\d+\])?:\s*(?P<msg>.*)$")
ERROR = re.compile(r"\b(errors?|err|failed|failures?|fatal|panic|critical|segfault|segmentation fault|denied)\b", re.I)
# Zero counters and negations ("failed=0", "0 errors", "no failures") are not error evidence.
BENIGN = re.compile(r"\b(?:0|no|zero)\s+(?:errors?|failures?|failed)\b"
                    r"|\b(?:errors|errs|failures|failed)\s*[=:]\s*0\b(?![.\d])"
                    r"|\b(?:error|err|failure)=0\b(?![.\d])", re.I)
CRITICAL = re.compile(r"\b(fatal|panic|critical)\b", re.I)
WARN = re.compile(r"\b(warn(?:ing)?|timeout|timed out|retry)\b", re.I)
PRIORITIES = {0: "critical", 1: "critical", 2: "critical", 3: "error", 4: "warning", 5: "info", 6: "info", 7: "debug"}


def value_text(value: object) -> str:
    if isinstance(value, list) and all(isinstance(n, int) and 0 <= n <= 255 for n in value):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def parse_line(line: str, source: str) -> LogEvent:
    raw = line.rstrip("\r\n")[:65536]
    timestamp, service, message, level = utc_now(), "unknown", raw, ""
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        data = None
    if isinstance(data, dict):
        message = value_text(data.get("MESSAGE", data.get("message", data.get("msg", raw))))[:65536]
        service = value_text(data.get("_SYSTEMD_UNIT", data.get("SYSLOG_IDENTIFIER", data.get("service", "unknown"))))[:256]
        timestamp = value_text(data.get("timestamp", timestamp))
        if "__REALTIME_TIMESTAMP" in data:
            try:
                timestamp = datetime.fromtimestamp(int(data["__REALTIME_TIMESTAMP"]) / 1e6, timezone.utc).isoformat()
            except (ValueError, TypeError, OverflowError, OSError):
                pass
        if "PRIORITY" in data:
            try:
                level = PRIORITIES.get(int(data["PRIORITY"]), "")
            except (ValueError, TypeError):
                pass
        else:
            level = value_text(data.get("level", data.get("severity", ""))).lower()
            level = {"warn": "warning", "err": "error", "fatal": "critical"}.get(level, level)
    else:
        priority = re.match(r"^<(\d{1,3})>", raw)
        if priority:
            level = PRIORITIES[int(priority[1]) % 8]
        match = SYSLOG.match(raw)
        if match:
            # Traditional syslog lacks year/timezone; retain its original timestamp.
            timestamp, service, message = match["stamp"], match["service"], match["msg"]
    if level not in {"critical", "error", "warning", "info", "debug"}:
        text = BENIGN.sub(" ", message)
        level = "critical" if CRITICAL.search(text) else "error" if ERROR.search(text) else "warning" if WARN.search(text) else "info"
    return LogEvent(timestamp, source, service, message, level, raw)
