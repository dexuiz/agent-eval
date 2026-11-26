import json
import os
import queue
import signal
import subprocess
import threading
from tempfile import TemporaryFile
from time import monotonic


class CodexRPC:
    def __init__(self, argv, cwd, env, timeout):
        self.timeout = timeout
        self.events = queue.Queue()
        self.serial = 0
        self.stderr = TemporaryFile()
        try:
            self.process = subprocess.Popen(
                argv, cwd=cwd, env=env, text=True, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.stderr, start_new_session=True,
            )
        except Exception:
            self.stderr.close()
            raise
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.process.stdout:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                continue
        self.events.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def next(self, deadline):
        try:
            event = self.events.get(timeout=max(0, deadline - monotonic()))
        except queue.Empty:
            raise RuntimeError("Codex timed out") from None
        if event is None:
            self.stderr.seek(0)
            detail = self.stderr.read().decode(errors="replace").strip().splitlines()
            raise RuntimeError(f"Codex exited: {detail[-1] if detail else 'no diagnostic'}")
        return event

    def request(self, method, params):
        self.serial += 1
        request_id = self.serial
        self.send({"method": method, "params": params, "id": request_id})
        deadline = monotonic() + self.timeout
        while True:
            event = self.next(deadline)
            if "method" in event:
                self.deny(event)
            elif event.get("id") == request_id:
                if "error" in event:
                    raise RuntimeError(f"{method}: {event['error']['message']}")
                return event["result"]

    def deny(self, event):
        if "id" in event:
            self.send({"id": event["id"], "error": {"code": -32601,
                                                    "message": "Benchmark denies requests"}})

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
        self.process.stdout.close()
        self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
