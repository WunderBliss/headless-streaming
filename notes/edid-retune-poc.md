# In-place EDID retune POC

Date: 2026-08-10 (Asia/Tokyo)

## Scope and current status

This development POC adds:

```text
./scripts/virtual-display-poc retune WIDTH HEIGHT FPS
```

It is intended to test the new persistent-display architecture: DP-1 is already
synthetically connected before Sunshine starts, and a Sunshine prep hook will
eventually retune that display rather than create/remove it per session.

No display mutation was executed while implementing this operation. DP-1 was
still `disconnected` at the end of preparation, and KWin still exposed only the
physical HDMI-A-1 recovery monitor. Sunshine configuration was not touched.

## What Linux 7.1.6 implements

The running package is `linux 7.1.6.arch1-1` (`uname -r` reports
`7.1.6-arch1-1`). Its relevant DRM behavior was checked at the matching upstream
stable tag. Arch may carry packaging patches, so the manual runtime result remains
authoritative:

- DRM's [`edid_override` write handler](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/drm_debugfs.c?h=v7.1.6)
  treats exactly five bytes of `reset` as the reset command; every other write is
  passed as one complete EDID blob to `drm_edid_override_set()`.
- [`drm_edid_override_set()`](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/drm_edid.c?h=v7.1.6)
  allocates and validates the new EDID first. Only after validation succeeds does
  it take `edid_override_mutex`, free the old override, and replace the pointer.
  A separate reset is therefore neither required nor desirable for this test.
- Writing the override does not itself send a hotplug event. The generic DRM
  `force` handler only updates `connector->force`; it also does not hotplug.
- AMDGPU's [`trigger_hotplug=1` handler](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/amd/display/amdgpu_dm/amdgpu_dm_debugfs.c?h=v7.1.6)
  performs HPD link detection, updates the connector, restores DRM connector
  state, and emits a connector hotplug event. Its own comment explicitly says it
  performs link rediscovery and link disable/enable.

The supported transaction is therefore:

```text
complete validated replacement EDID -> force remains/is set on -> trigger_hotplug=1
```

There is no source requirement to write `reset`, `unspecified`, or `off` between
the two EDIDs. The new helper does not do so in either the forward transaction or
rollback.

The mutex makes replacement of the kernel's EDID override pointer safe, but it
does not promise uninterrupted scanout. AMDGPU's hotplug handler deliberately
redetects and disables/enables the link. The manual test must distinguish:

- DRM connector status remaining logically `connected`;
- KWin temporarily showing stale modes or briefly losing/rediscovering DP-1;
- visible blanking, window movement, or other compositor effects shorter than
  the helper's 250 ms poll interval.

The helper fails immediately if a sampled DRM status is anything other than
`connected`. Its success output reports sample counts for stale EDID, stale DRM
mode, missing/disabled KWin output, and stale KWin mode. Zero counts are useful,
but cannot prove there was no sub-250-ms transient.

## EDID generator change for the test modes

The original generator used CVT normal blanking only. That cannot represent
`2560x1600@120` in an EDID base-block Detailed Timing Descriptor: normal blanking
needs about 734.75 MHz, while a DTD can encode at most 655.35 MHz.

`scripts/edid.py` now preserves normal blanking when it fits and falls back to
CVT 1.2 reduced blanking v1 only when normal blanking exceeds a DTD field limit.
The installed `cvt -r 2560 1600 120` independently reports the same reduced
timing used by the generator:

```text
Modeline "2560x1600R"  552.75  2560 2608 2640 2720  1600 1603 1609 1694 +hsync -vsync
```

All three planned EDIDs remain minimal 128-byte EDID 1.4 base blocks with one
preferred DTD, the full POC identity (`VDS/0xd150`, `VIRTUAL-POC`,
`VDS-POC-0001`, zero numeric serial, and the expected no-extension layout), and
successful internal plus `edid-decode --check` validation:

| Request | Represented refresh | Clock/blanking | Physical size | Checksum |
| --- | --- | --- | --- | --- |
| 1920x1080@60 | 59.962844 Hz | 173.000 MHz, CVT normal | 508 x 286 mm | `0xfd` |
| 2560x1600@120 | 119.962758 Hz | 552.750 MHz, CVT-RBv1 | 677 x 423 mm | `0x8f` |
| 1280x800@90 | 89.887410 Hz | 131.250 MHz, CVT normal | 339 x 212 mm | `0x64` |

The 2560x1600 timing is DTD-representable and standards-checks successfully.
The reduced-blanking-v1 fallback is limited to exact multiples of 60 Hz, as is
the installed `cvt -r`; a future general client-mode generator will need RBv2
or another timing policy for high-bandwidth rates such as 90 Hz when normal
blanking does not fit. Whether AMD Display Core accepts this 120 Hz timing on
the forced connector and whether KWin handles the live transition cleanly
remain part of the manual test.

## `retune` safety and transaction

Before any privileged write, `retune` requires all of the following:

1. It is running as desktop user `owen`, not root.
2. The hard-coded card1/DP-1, PCI BDF `0000:c5:00.0`, PCI ID `1002:1586`, and
   `amdgpu` driver topology still match.
3. DRM reports DP-1 as already `connected`.
4. DP-1 exposes a non-empty, internally valid EDID with all of this POC's
   identity/layout markers, not merely the `VDS/0xd150` pair.
5. KWin JSON exposes exactly one connected, enabled output named `DP-1`, with a
   current mode matching the synthetic EDID's preferred timing.
6. The new EDID passes internal and installed `edid-decode` validation and differs
   from the current EDID.
7. The same three fixed debugfs endpoints used by the existing POC pass the
   root-only preflight.

The forward transaction is:

1. Save the previous synthetic EDID, current KScreen mode characteristics, and
   scale in normal-user memory.
2. Write the new complete binary EDID directly to `edid_override`.
3. Write exact no-newline `on` to `force`; never write `off` or `unspecified`.
4. Write the proven `1\n` hotplug payload.
5. On every poll, require DRM status `connected`.
6. Wait for byte-identical sysfs EDID, the requested DRM resolution, and a
   connected/enabled KWin `DP-1` containing a mode within 0.5 Hz of the request.
7. Resolve that KScreen mode ID from the JSON block selected by connector name.
8. In one KScreen invocation, set only `output.DP-1.mode.MODE_ID` and
   `output.DP-1.scale.1`.
9. Verify DP-1's current KWin mode and scale 1, and recheck the EDID/status.

No KScreen argument names HDMI-A-1. Retune does not set priority, position,
rotation, primary status, or any HDMI property.

If any step after the first debugfs write fails, rollback directly replaces the
override with the previously saved synthetic EDID, writes `force=on`, triggers
hotplug, resolves the previous mode again by DP-1 name, and restores the previous
mode and scale. Rollback never resets or forces off the connector. If rollback
also fails, the error explicitly reports that DP-1 may need manual recovery;
HDMI-A-1 is still not targeted.

## Manual test sequence

Run these commands from `~/projects/headless-streaming` as `owen`, without
prefixing the helper itself with sudo. It will request sudo only for its fixed
debugfs endpoint operations.

First confirm the recovery monitor and starting state:

```bash
./scripts/virtual-display-poc status
```

### A. Bring up the baseline at 1920x1080@60

```bash
./scripts/virtual-display-poc up 1920 1080 60
```

### B. Retune in place to 2560x1600@120

```bash
./scripts/virtual-display-poc retune 2560 1600 120
```

### C. Inspect DRM/KWin

```bash
./scripts/virtual-display-poc status
tr -d '\n' </sys/class/drm/card1-DP-1/status; printf '\n'
wc -c </sys/class/drm/card1-DP-1/edid
sed -n '1,40p' /sys/class/drm/card1-DP-1/modes
edid-decode --check /sys/class/drm/card1-DP-1/edid
kscreen-doctor -o
```

Expected essentials: status remains `connected`, EDID is 128 bytes, DRM exposes
`2560x1600`, KWin's DP-1 current mode is approximately 119.96 Hz, and scale is 1.
Also record the helper's retune observation counters and any visible transient.

### D. Retune in place to 1280x800@90

```bash
./scripts/virtual-display-poc retune 1280 800 90
```

### E. Inspect DRM/KWin again

```bash
./scripts/virtual-display-poc status
tr -d '\n' </sys/class/drm/card1-DP-1/status; printf '\n'
wc -c </sys/class/drm/card1-DP-1/edid
sed -n '1,40p' /sys/class/drm/card1-DP-1/modes
edid-decode --check /sys/class/drm/card1-DP-1/edid
kscreen-doctor -o
```

Expected essentials: status remains `connected`, EDID is 128 bytes, DRM exposes
`1280x800`, KWin's DP-1 current mode is approximately 89.89 Hz, and scale is 1.

### F. Tear down using the existing operation

```bash
./scripts/virtual-display-poc down
```

Then verify recovery state:

```bash
./scripts/virtual-display-poc status
```

## Observations to record after the manual run

This file intentionally does not claim the runtime retune has succeeded yet.
After running the sequence, record:

- Whether any sampled DRM status became disconnected.
- Retune observation counters from both transitions.
- Whether DP-1 vanished/reappeared or merely changed modes in KWin.
- Whether KWin retained DP-1's position/priority and whether any windows moved.
- Whether HDMI-A-1 flickered or changed in any way.
- Approximate visible blanking duration, if any.
- Whether both requested mode/scale transitions verified on the first attempt.
- Whether teardown still worked after multiple direct replacements.

No Sunshine configuration, boot integration, sudoers rule, or systemd unit should
be added until this test result is recorded.
