"""Interruptible live sources; no shell execution or privileged operations."""
from __future__ import annotations

import os
import selectors
import shutil
import stat
import subprocess
import threading
from pathlib import Path
from typing import Callable, Iterator


class LineFramer:
    """Bound partial lines and truncate oversized records without splitting them."""
    def __init__(self, limit: int = 65536):
        self.limit = limit
        self.pending = bytearray()
        self.truncated = False

    def feed(self, chunk: bytes) -> list[str]:
        result = []
        parts = chunk.split(b"\n")
        for i, part in enumerate(parts):
            room = max(0, self.limit - len(self.pending))
            self.pending.extend(part[:room])
            self.truncated |= len(part) > room
            if i < len(parts) - 1:
                suffix = f" [record truncated at {self.limit} bytes]" if self.truncated else ""
                text = self.pending.decode("utf-8", "replace").rstrip("\r")
                result.append(text[:max(0, self.limit - len(suffix))] + suffix if suffix else text)
                self.pending.clear()
                self.truncated = False
        return result


def open_regular(path: Path):
    """Open without blocking on FIFOs or devices; return None unless it is a regular file."""
    stream = os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb")
    if stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        return stream
    stream.close()
    return None


def tail_anchor(stream) -> tuple[bytes, int]:
    offset = max(0, stream.tell() - 64)
    return os.pread(stream.fileno(), stream.tell() - offset, offset), offset


def follow_file(path: str, stop: threading.Event, from_start: bool = False,
                status: Callable[[str], None] = lambda _: None) -> Iterator[str | None]:
    path_obj = Path(path).expanduser()
    if not path_obj.is_file():
        raise ValueError("Select an existing regular log file")
    stream = open_regular(path_obj)
    if stream is None:
        raise ValueError("Select a regular log file")
    try:
        anchor = b""
        anchor_offset = 0
        if not from_start:
            stream.seek(0, os.SEEK_END)
            # Anchor existing content so truncation is noticed before the first new line.
            anchor, anchor_offset = tail_anchor(stream)
        framer = LineFramer()
        missing = False
        while not stop.is_set():
            # Copy-truncate can regrow past the old position between polls.
            size = os.fstat(stream.fileno()).st_size
            replaced_content = bool(anchor and os.pread(stream.fileno(), len(anchor), anchor_offset) != anchor)
            if size < stream.tell() or replaced_content:
                stream.seek(0)
                anchor = b""
                framer = LineFramer()
                status("Log file truncated; following from its new beginning")
            chunk = stream.read(65536)
            if chunk:
                anchor, anchor_offset = tail_anchor(stream)
                for line in framer.feed(chunk):
                    if stop.is_set():
                        return
                    if line:
                        yield line
                continue
            available = True
            try:
                current = path_obj.stat()
                opened = os.fstat(stream.fileno())
                if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                    replacement = open_regular(path_obj)
                    if replacement is not None:
                        stream.close()
                        stream = replacement
                        framer, anchor = LineFramer(), b""
                        if missing:
                            missing = False
                            status("Log path available again")
                        status("Log file rotated; following the replacement file")
                        continue
                    # A FIFO, directory, or device at the path is not followed.
                    available = False
            except FileNotFoundError:
                available = False
            if available and missing:
                missing = False
                status("Log path available again")
            elif not available and not missing:
                status("Log path temporarily missing; waiting for rotation to finish")
                missing = True
            yield None
            stop.wait(0.1)
    finally:
        stream.close()


def follow_journal(stop: threading.Event, unit: str = "", user: bool = False,
                   status: Callable[[str], None] = lambda _: None) -> Iterator[str | None]:
    executable = shutil.which("journalctl")
    if not executable:
        raise RuntimeError("journalctl is unavailable; use file monitoring instead")
    command = [executable, "--follow", "--lines=0", "--output=json", "--no-pager", "--all"]
    if unit:
        command += ["--unit", unit]
    if user:
        command.append("--user")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    selector = selectors.DefaultSelector()
    framer, error_framer = LineFramer(), LineFramer()
    try:
        for pipe, kind in ((process.stdout, "log"), (process.stderr, "status")):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, kind)
        while not stop.is_set():
            for key, _ in selector.select(timeout=0.1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = framer if key.data == "log" else error_framer
                for line in target.feed(chunk):
                    if stop.is_set():
                        return
                    if key.data == "log" and line:
                        yield line
                    elif line:
                        status("journalctl: " + line)
            yield None
            if process.poll() is not None and not selector.get_map():
                raise RuntimeError(f"journalctl exited with status {process.returncode}; check journal permissions")
    finally:
        selector.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        process.stdout.close()
        process.stderr.close()


def demo_stream(stop: threading.Event) -> Iterator[str | None]:
    """Deterministic demo: a normal baseline, an error burst, then recovery."""
    import json
    for i in range(120):
        if stop.is_set():
            return
        yield json.dumps(dict(service="demo.service", level="info", message=f"Completed job {i} in 12 ms"))
        stop.wait(0.025)
    i = 0
    while not stop.is_set():
        if i % 80 == 0:
            yield json.dumps(dict(service="kernel", message="Out of memory: oom-killer terminated process 812"))
        elif i % 80 == 1:
            yield json.dumps(dict(service="sshd", message="Failed password for invalid user admin from 192.0.2.7 port 2214"))
        elif i % 80 < 8:
            yield json.dumps(dict(service="demo.service", message=f"ERROR connection failed for worker {i}"))
        elif i % 80 == 8:
            yield json.dumps(dict(service="demo.service", message="Unexpected supervisor restart requested"))
        else:
            yield json.dumps(dict(service="demo.service", level="info", message=f"Completed job {i} in 12 ms"))
        i += 1
        stop.wait(0.15)
