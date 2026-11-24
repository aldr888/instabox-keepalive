# InstaBox keepalive

Keeps a free-tier InstaBox machine from being paused when its owner's own
computer is switched off. Runs on GitHub's scheduled runners, outside the
sandbox, so it still works while the machine is suspended.

Adapted from:

- [ashuai168/instabox-keepalive](https://github.com/ashuai168/instabox-keepalive) — activity-lease mode (MIT)
- [googbad/instabox-keepalive](https://github.com/googbad/instabox-keepalive) — rotate the run before the platform limit
- [btpp03/instabox-keepalive-hermes](https://github.com/btpp03/instabox-keepalive-hermes) — external scheduler approach

## What each run does

1. Reads the machine state from `GET /v1/machines/{id}`.
2. Machine not running and not in cooldown → `POST /start`.
3. Machine running and close to `maxRunMinutes` → `POST /suspend`, then `POST /start`
   (a forced pause by the platform starts a cooldown that grows with each repeat;
   rotating first avoids it, and processes inside the sandbox survive).
4. Otherwise renews the activity lease (`PUT /v1/machines/{id}/activity-leases/keepalive`),
   so the idle auto-suspend never fires.

## Setup

Repository secrets:

| Secret | Meaning |
| --- | --- |
| `INSTABOX_API_KEY` | `ibk_...` key from the InstaBox dashboard |
| `INSTABOX_MACHINE_ID` | `m_...` machine id |

Optional environment tweaks in the workflow: `TTL_SECONDS` (default `900`),
`ROTATE_BEFORE` (default `10` minutes before the run limit).

Run it once by hand with **Actions → instabox-keepalive → Run workflow** to
check the log line `lease renewed, expires ...`.
