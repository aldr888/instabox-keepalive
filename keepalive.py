#!/usr/bin/env python3
"""InstaBox keepalive (GitHub Actions edition).

Adapted from the community projects ashuai168/instabox-keepalive (activity
lease, MIT) and googbad/instabox-keepalive (rotate before the run limit).
Runs on an external always-on runner, so it can still act while the sandbox
is suspended.

Each run:
  1. reads the machine state;
  2. if not running and not in cooldown -> POST /start;
  3. if running and the current run is close to maxRunMinutes -> suspend, then
     start, so the platform never force-pauses it (forced pauses have a
     cooldown that grows with each repeat);
  4. renews an activity lease so the 30-minute idle pause never fires.

Environment:
  INSTABOX_API_KEY    required, ibk_... key from the InstaBox dashboard
  INSTABOX_MACHINE_ID required, m_... machine id
  TTL_SECONDS         optional, default 900
  ROTATE_BEFORE       optional minutes before maxRun, default 10
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

API = "https://api.instabox.sh"
MID = os.environ.get("INSTABOX_MACHINE_ID", "").strip()
KEY = os.environ.get("INSTABOX_API_KEY", "").strip()
LEASE = "keepalive"
TTL = int(os.environ.get("TTL_SECONDS", "900"))
ROTATE_BEFORE = int(os.environ.get("ROTATE_BEFORE", "10"))
DRY = "--dry-run" in sys.argv
FORCE_ROTATE = "--rotate-now" in sys.argv


def log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + msg, flush=True)


def call(method, path, body=None, idem=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"X-API-Key": KEY, "Content-Type": "application/json"}
    if method != "GET":
        headers["Idempotency-Key"] = idem or uuid.uuid4().hex
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read() or b"{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b"{}"
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"raw": raw[:200].decode("utf-8", "replace")}
        return exc.code, payload
    except Exception as exc:  # network, DNS, TLS
        return 0, {"error": str(exc)}


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def minutes_since(moment):
    return (datetime.now(timezone.utc) - moment).total_seconds() / 60.0


def action_with_wait(name, want_states, timeout=90):
    status, body = call("POST", "/v1/machines/%s/%s" % (MID, name))
    log("%s -> HTTP %s %s" % (name, status, "" if status < 400 else json.dumps(body)[:200]))
    if status >= 400:
        return status
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        _, current = call("GET", "/v1/machines/%s" % MID)
        if current.get("state") in want_states:
            return 200
    return 0


def main():
    if not MID or not KEY:
        log("missing INSTABOX_MACHINE_ID or INSTABOX_API_KEY")
        return 1

    status, info = call("GET", "/v1/machines/%s" % MID)
    if status != 200:
        log("GET machine failed HTTP %s: %s" % (status, json.dumps(info)[:200]))
        return 1

    state = info.get("state")
    max_run = info.get("maxRunMinutes", 0)
    run_start = parse_time(info.get("runStartedAt"))
    cooldown = parse_time(info.get("cooldownUntil"))
    run_min = minutes_since(run_start) if run_start else None

    log("state=%s maxRun=%s runMin=%s cooldown=%s" % (
        state, max_run, None if run_min is None else round(run_min, 1),
        "" if not cooldown else cooldown.isoformat()))

    if DRY:
        log("dry run, no changes")
        return 0

    # 1. Bring it back if it is down and allowed to wake.
    if state != "running":
        if cooldown and cooldown > datetime.now(timezone.utc):
            log("in cooldown until %s, skip start" % cooldown.isoformat())
            return 0
        log("machine is %s, starting" % state)
        action_with_wait("start", {"running"})
        return 0

    # 2. Rotate before the platform's own max-run pause.
    should_rotate = FORCE_ROTATE
    if not should_rotate and max_run and max_run > 0 and run_min is not None:
        should_rotate = run_min >= max(15, max_run - ROTATE_BEFORE)

    if should_rotate:
        log("rotating run (runMin=%.1f, maxRun=%s)" % (run_min or 0, max_run))
        if action_with_wait("suspend", {"suspended", "paused", "stopped"}, timeout=60) == 200:
            status, body = call("POST", "/v1/machines/%s/start" % MID)
            log("start after rotate -> HTTP %s %s" % (status, "" if status < 400 else json.dumps(body)[:200]))
        return 0

    # 3. Renew the activity lease so the 30-minute idle pause never fires.
    status, body = call("PUT", "/v1/machines/%s/activity-leases/%s" % (MID, LEASE),
                        {"ttlSeconds": TTL})
    if status == 200:
        log("lease renewed, expires %s" % body.get("expiresAt"))
        return 0
    log("lease renew failed HTTP %s: %s" % (status, json.dumps(body)[:200]))
    status, info = call("GET", "/v1/machines/%s" % MID)
    if status == 200 and info.get("state") != "running":
        log("machine is now %s, will start next run" % info.get("state"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
