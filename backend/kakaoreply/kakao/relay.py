"""Private bounded stdio relay. No protocol interpretation and no diagnostics.

The SDK's line reader has no frame bound. This subprocess rejects oversized or
unterminated frames before forwarding them and owns the server process group.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading

MAX_FRAME_BYTES = 1_200_000


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    process = subprocess.Popen(sys.argv[1:], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    stopping = threading.Event()

    def stop(*_args):
        if stopping.is_set():
            return
        stopping.set()
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # readline may be blocked on a child that ignores TERM. Escalation must
        # run independently of that reader and include descendants.
        def escalate():
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        threading.Thread(target=escalate, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def feed():
        try:
            while not stopping.is_set():
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    break
                process.stdin.write(chunk)
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            stop()

    threading.Thread(target=feed, daemon=True).start()
    try:
        while not stopping.is_set():
            line = process.stdout.readline(MAX_FRAME_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_FRAME_BYTES or not line.endswith(b'\n'):
                return 3
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
        return 0
    except (BrokenPipeError, OSError):
        return 4
    finally:
        stop()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        # A server can exit on TERM while its children retain stdout and ignore
        # TERM. Reaping only the immediate child is insufficient.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.exit(5)
