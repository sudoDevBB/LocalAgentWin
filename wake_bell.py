"""Wake the local Soundroom server task and trigger a scheduled room bell."""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "data" / "config.json"


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        return 2
    bell_id = sys.argv[1]
    try:
        secret = json.loads(CONFIG.read_text(encoding="utf-8"))["secret"]
    except (OSError, KeyError, json.JSONDecodeError):
        return 1
    endpoint = f"http://127.0.0.1:8765/internal/wake-bell/{bell_id}"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        request = urllib.request.Request(endpoint, method="POST", headers={"X-Soundroom-Wake-Key": secret})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return 0 if response.status == 200 else 1
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(2)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
