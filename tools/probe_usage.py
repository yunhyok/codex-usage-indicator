from __future__ import annotations

import json
import queue
import subprocess
import threading
import time

from codex_usage_indicator.protocol import find_codex_executable, initialize_request


def main() -> int:
    executable = find_codex_executable()
    if executable is None:
        print("Codex executable not found")
        return 2
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(executable), "app-server", "-c", 'service_tier="fast"'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )
    assert process.stdin and process.stdout
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(
        target=lambda: [lines.put(line) for line in process.stdout], daemon=True
    ).start()
    process.stdin.write(json.dumps(initialize_request(1), separators=(",", ":")) + "\n")
    process.stdin.flush()
    deadline = time.time() + 20
    try:
        initialized = False
        while time.time() < deadline:
            try:
                payload = json.loads(lines.get(timeout=0.5))
            except queue.Empty:
                continue
            if payload.get("id") == 1 and not initialized:
                if "error" in payload:
                    print(json.dumps(payload["error"], ensure_ascii=False))
                    return 4
                for message in (
                    {"method": "initialized"},
                    {"id": 2, "method": "account/rateLimits/read"},
                ):
                    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                process.stdin.flush()
                initialized = True
                continue
            if payload.get("id") == 2:
                result = payload.get("result", {})
                safe = {
                    "rateLimits": result.get("rateLimits"),
                    "bucketIds": sorted((result.get("rateLimitsByLimitId") or {}).keys()),
                }
                print(json.dumps(safe, ensure_ascii=False, indent=2))
                return 0
        print("Timed out")
        return 3
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
