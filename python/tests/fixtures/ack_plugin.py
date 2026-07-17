"""Deterministic JSON-lines fixture for the out-of-process plugin contract."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def send(value: object) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    if request.get("type") == "initialize":
        send({"type": "ready", "protocolVersion": "1.0"})
    elif request.get("type") == "event":
        capture = Path(os.environ["CAPTURE_PATH"])
        with capture.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(request["event"], separators=(",", ":")) + "\n")
        send(
            {
                "type": "ack",
                "deliveryId": request["deliveryId"],
                "accepted": True,
            }
        )
    elif request.get("type") == "shutdown":
        raise SystemExit(0)
