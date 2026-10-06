"""Local JSONL persistence plus bounded asynchronous HTTP delivery."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class DeliveryConfig:
    output: str
    endpoint: str = ""
    token: str = ""

    def validate(self) -> None:
        if not self.output.strip():
            raise ValueError("Choose an alert output file")
        if self.endpoint:
            url = urllib.parse.urlsplit(self.endpoint)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("Endpoint must be an HTTP(S) URL without credentials or fragments")
            _ = url.port  # Reject malformed port numbers before starting delivery.
        if "\n" in self.token or "\r" in self.token:
            raise ValueError("Token cannot contain line breaks")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward a log payload or bearer token to a redirected destination.
        return None


class AlertSender(threading.Thread):
    def __init__(self, config: DeliveryConfig, status: Callable[[str], None]):
        super().__init__(name="alert-delivery", daemon=True)
        config.validate()
        self.config, self.status = config, status
        self.pending: queue.Queue = queue.Queue(maxsize=256)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.saved = self.delivered = self.failed = self.dropped = self.save_failed = 0
        self.opener = urllib.request.build_opener(NoRedirect())
        output = Path(config.output).expanduser()
        if output.exists() and not output.is_file():
            raise ValueError("Alert output must be a regular file")
        output.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(output, maxBytes=10 * 1024 * 1024,
                                           backupCount=3, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(message)s"))

    def submit(self, alert: dict):
        payload = json.dumps(alert, ensure_ascii=False, allow_nan=False)
        # Persist before enqueueing: a saturated HTTP queue does not lose local alerts.
        try:
            if self.handler.shouldRollover(logging.makeLogRecord({"msg": payload})):
                self.handler.doRollover()
            self.handler.stream.write(payload + "\n")
            self.handler.flush()
            with self.lock:
                self.saved += 1
        except OSError as exc:
            with self.lock:
                self.save_failed += 1
            self.status(f"Alert persistence failed: {exc}")
        if self.config.endpoint:
            try:
                self.pending.put_nowait((alert["alert_id"], payload.encode("utf-8")))
            except queue.Full:
                with self.lock:
                    self.dropped += 1
                self.status("HTTP delivery queue full; alert was not queued. Check the local JSONL file.")

    def snapshot(self):
        with self.lock:
            return dict(saved=self.saved, delivered=self.delivered, failed=self.failed,
                        dropped=self.dropped, save_failed=self.save_failed, pending=self.pending.qsize())

    def close(self):
        self.stop_event.set()
        self.join(timeout=4)
        self.handler.close()

    def run(self):
        while not self.stop_event.is_set():
            try:
                alert_id, payload = self.pending.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._send(alert_id, payload)
            finally:
                self.pending.task_done()

    def _send(self, alert_id: str, payload: bytes):
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "Idempotency-Key": alert_id, "User-Agent": "Linux-LogWatch/1.0"}
        if self.config.token:
            headers["Authorization"] = "Bearer " + self.config.token
        for attempt in range(3):
            if self.stop_event.is_set():
                return
            try:
                request = urllib.request.Request(self.config.endpoint, data=payload, headers=headers, method="POST")
                with self.opener.open(request, timeout=3) as response:
                    if not 200 <= response.status < 300:
                        raise OSError(f"HTTP status {response.status}")
                with self.lock:
                    self.delivered += 1
                return
            except (OSError, ValueError, urllib.error.URLError) as exc:
                retry = not isinstance(exc, urllib.error.HTTPError) or exc.code in {408, 429} or exc.code >= 500
                if isinstance(exc, urllib.error.HTTPError):
                    exc.close()
                if attempt == 2 or not retry:
                    with self.lock:
                        self.failed += 1
                    # Do not display URLs, credentials, or server bodies from exceptions.
                    code = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
                    self.status(f"HTTP delivery failed ({code}); alert {alert_id} remains in the local JSONL file if saved.")
                    return
                if self.stop_event.wait(0.5 * (2 ** attempt)):
                    return
