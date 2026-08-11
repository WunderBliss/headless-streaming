# Persistent virtual-display manual test plan

Date: 2026-08-10 (Asia/Tokyo)

## Safety gates

- Keep physical HDMI-A-1 attached through Phases 1-3.
- Keep SSH available.
- Never prefix `/usr/local/bin/virtual-display` with sudo.
- Do not change HDMI-A-1 mode, scale, position, priority, or enabled state.
- Do not start a Moonlight stream until Phases 1 and 2 pass.
- Record `virtual-display status` and relevant journals after any failure.
- Stop on an unrecognized EDID, unknown connector status, rollback failure, or any
  unexpected HDMI change.

The installation/enable steps in `notes/install.md` must be complete first.

## Phase 1: production helper sanity

### 1. Baseline

```bash
/usr/local/bin/virtual-display baseline
/usr/local/bin/virtual-display status
```

Require:

- DRM DP-1 connected;
- full managed VDS identity valid;
- active/generated mode approximately `1920x1080@59.96`;
- KWin DP-1 connected and enabled at 1920x1080, scale 1;
- display profile `baseline`; and
- HDMI-A-1 unchanged in `kscreen-doctor -o`.

### 2. Exact high-refresh retune

```bash
/usr/local/bin/virtual-display retune 2560 1600 120
/usr/local/bin/virtual-display status
```

Require log lines showing requested/effective exact
`2560x1600@120`, retune success, KWin approximately 119.96 Hz, scale 1, and
profile `retuned`.

### 3. Exact smaller retune

```bash
/usr/local/bin/virtual-display retune 1280 800 90
/usr/local/bin/virtual-display status
```

Require exact `1280x800@90`, KWin approximately 89.89 Hz, scale 1, and managed
identity. Confirm HDMI-A-1 did not flicker or change.

## Phase 2: fallback and no-partial-state tests

Record a starting snapshot:

```bash
before_edid="$(sha256sum /sys/class/drm/card1-DP-1/edid | awk '{print $1}')"
/usr/local/bin/virtual-display status
```

The read-only `card1` path is shown here only for the known current host. The
helper itself discovers the card dynamically.

### 1. Unsupported 4K refresh

```bash
/usr/local/bin/virtual-display retune 3840 2160 90
/usr/local/bin/virtual-display status
```

Require concise logs equivalent to:

```text
virtual-display: requested 3840x2160@90
virtual-display: exact mode unsupported: ...
virtual-display: using fallback 3840x2160@60
```

Status must show managed 3840x2160 at approximately 60 Hz and scale 1.

### 2. Over-width 5K request

```bash
/usr/local/bin/virtual-display retune 5120 2880 60
/usr/local/bin/virtual-display status
```

Require exact rejection because width exceeds 4095 and effective
`3840x2160@60`, with no aspect warning/error.

Optional additional aspect check:

```bash
/usr/local/bin/virtual-display retune 6016 3384 60
/usr/local/bin/virtual-display status
```

Expected effective mode is also aspect-exact `3840x2160@60`.

### 3. Invalid input must not mutate DRM

Capture the current EDID hash, issue malformed requests, and compare:

```bash
safe_edid="$(sha256sum /sys/class/drm/card1-DP-1/edid | awk '{print $1}')"
env SUNSHINE_CLIENT_WIDTH='3840x2160' \
    SUNSHINE_CLIENT_HEIGHT=2160 \
    SUNSHINE_CLIENT_FPS=60 \
    /usr/local/bin/virtual-display sunshine-up
test "$safe_edid" = "$(sha256sum /sys/class/drm/card1-DP-1/edid | awk '{print $1}')"

/usr/local/bin/virtual-display retune 0 2160 60
test "$safe_edid" = "$(sha256sum /sys/class/drm/card1-DP-1/edid | awk '{print $1}')"
```

Both helper calls must exit nonzero before sudo. The hashes must match, DP-1 must
remain connected/managed/active, and HDMI-A-1 must remain unchanged.

Restore baseline before Sunshine testing:

```bash
/usr/local/bin/virtual-display baseline
/usr/local/bin/virtual-display status
```

## Phase 3: first real Sunshine/Moonlight test with HDMI attached

### 1. Establish and record the safe start

```bash
/usr/local/bin/virtual-display baseline
/usr/local/bin/virtual-display status
kscreen-doctor -o
```

Confirm DP-1 baseline and HDMI-A-1 recovery output are both present. Confirm the
live Sunshine settings are `kwin`, `vaapi`, `DP-1`, with the fixed global prep do
command and empty undo. Confirm the selected application does not exclude global
prep commands.

### 2. Restart Sunshine manually and mark the journal time

```bash
test_started="$(date --iso-8601=seconds)"
systemctl --user restart app-dev.lizardbyte.app.Sunshine.service
systemctl --user status app-dev.lizardbyte.app.Sunshine.service --no-pager
journalctl --user -u app-dev.lizardbyte.app.Sunshine.service \
  --since "$test_started" --no-pager
```

Sunshine's startup probe must see DP-1. Do not proceed if the baseline unit or
Sunshine failed.

### 3. Connect the actual Moonlight client

From Moonlight, launch the intended application/Desktop and request a known
client-native resolution and FPS. Do this manually; there is no automated stream
start in the project.

Immediately inspect:

```bash
/usr/local/bin/virtual-display status
journalctl --user -u app-dev.lizardbyte.app.Sunshine.service \
  --since "$test_started" --no-pager | \
  rg 'virtual-display:|\[kwingrab\]|Encoder|Capture|error|warning'
```

Require all of the following:

- prep logged the exact client request;
- it logged exact or a documented fallback and the effective mode;
- DP-1 was retuned successfully;
- KWin DP-1 is enabled/current at the effective mode and scale 1;
- the stream shows video from the DP-1 desktop;
- audio works;
- keyboard/mouse/controller input works as applicable; and
- the journal contains exactly this targeting evidence:

  ```text
  [kwingrab] Screencasting output name DP-1
  ```

If that line is absent, targeting is not proven even if video appears correct.
Stop the test and inspect full logs. If the line names HDMI-A-1, stop immediately;
do not treat the session as a pass.

### 4. Persistence across disconnect/resume and quit

Disconnect the Moonlight client without quitting the Sunshine application.
Then run:

```bash
/usr/local/bin/virtual-display status
```

DP-1 must remain connected at the last effective mode. Reconnect/resume and
reconfirm the `[kwingrab] ... DP-1` line for the new capture start if one is
logged. Then use Moonlight's Quit Session and check status again. DP-1 must still
exist; no undo removes it.

Finally restore the conservative idle state manually:

```bash
/usr/local/bin/virtual-display baseline
```

## Phase 4: later cold boot without HDMI

Do not perform this phase until Phases 1-3 pass and SSH recovery has been tested.

1. Restore baseline and cleanly shut down through the normal OS workflow.
2. Disconnect HDMI-A-1 while powered off.
3. Cold boot; do not change kernel arguments.
4. Connect over SSH and check:

   ```bash
   systemctl status headless-virtual-display-drm.service --no-pager
   systemctl --user status headless-virtual-display-kwin.service --no-pager
   systemctl --user status app-dev.lizardbyte.app.Sunshine.service --no-pager
   /usr/local/bin/virtual-display status
   ```

5. Require DP-1 baseline before Sunshine, Plasma/KWin active DP-1 scale 1, and a
   running Sunshine service.
6. Connect Moonlight, request a dynamic mode, and repeat all Phase 3 targeting,
   video/audio/input, disconnect/resume, and persistence checks.
7. Keep SSH as the recovery path. Use `virtual-display baseline` first; use
   `virtual-display remove` only for explicit administrative recovery.

## Results to record

For every phase, record requested/effective modes, EDID identity, actual KWin
refresh/scale, helper exit status, relevant journal excerpts, any visible blanking,
whether DP-1 ever sampled disconnected, and any HDMI-A-1 change. Record the exact
Sunshine package version when Phase 3 is run because its output fallback behavior
is version-sensitive.
