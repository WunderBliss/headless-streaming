# Dynamic EDID / virtual-display proof of concept

Date: 2026-08-10

## Scope and result

This POC creates a minimal EDID 1.4 in memory and can apply it only to the already-proven amdgpu DP-1 debugfs connector. It does not integrate Sunshine, alter HDMI-A-1, configure KWin output properties, install packages, persist configuration, or change kernel/boot settings.

The checked-in sample is `test-data/generated-1920x1080-75.edid`. It is an original 128-byte EDID generated for this POC, not a copy or derivative of `known-good.edid` or the attached HDMI monitor.

No `up` or `down` mutation was run while building this POC. Only generation, validation, help, and the read-only `status` path were exercised.

## Tool inventory

Available:

- `/usr/bin/edid-decode`, from `v4l-utils 1.32.0-2`.
- `/usr/bin/cvt`, from `libxcvt 0.1.3-1`.
- `/usr/bin/decode-edid` and `/usr/bin/di-edid-decode` are also present.
- Python 3.14.6.
- `kscreen-doctor` from libkscreen 6.7.4.

Not available:

- `cvt12`
- `modeline2edid`
- `parse-edid` / `get-edid`
- `edid-generator` / `edidgen`
- Python modules or distributions named `edid`, `pyedid`, `displayid`, `cvt`, or `modeline`

No package was installed.

## Chosen implementation

`scripts/edid.py` is a small, standard-library-only generator and validator. It prefers progressive VESA CVT 1.2 normal blanking and falls back to CVT 1.2 reduced blanking v1 when a normal-blanking timing cannot fit in an EDID Detailed Timing Descriptor. It packs one preferred DTD into an EDID 1.4 base block. There are no CTA, DisplayID, audio, HDR, VRR, or extension blocks.

The implementation is self-contained because the required subset is small:

1. Validate dimensions and refresh against the representable EDID/CVT ranges.
2. Calculate CVT normal-blanking porches, sync widths, totals, polarity, and the 250 kHz-quantized pixel clock; retry with CVT reduced blanking v1 only if the normal timing exceeds DTD field limits.
3. Pack a single 128-byte EDID base block.
4. Validate header, length, extension count, every checksum, digital/preferred flags, identity, DTD fields, physical dimensions, and requested timing before opening any output file or privileged endpoint.
5. When installed, run `edid-decode --check -` against the in-memory bytes before saving or applying them. No temporary file is needed.

Using `cvt` as a required runtime parser would add subprocess/output-format coupling without reducing the EDID-packing work. Instead, its output is used as an independent cross-check. The generated 1920x1080@75 timing exactly matches installed `cvt`.

## Generated 1920x1080@75 EDID

Identity and display properties:

- EDID 1.4, one 128-byte base block, no extensions.
- Manufacturer `VDS`, product code `0xd150`; this signature lets `down` avoid removing a connected physical DP display.
- Digital DisplayPort input, 8 bits per component, RGB, sRGB, gamma 2.20.
- Preferred/native DTD: 1920x1080 at 74.905668 Hz.
- Pixel clock: 220.750 MHz.
- Horizontal timing: 1920 active, 136 front porch, 208 sync, 344 back porch, 2608 total, negative sync.
- Vertical timing: 1080 active, 3 front porch, 5 sync, 42 back porch, 1130 total, positive sync.
- Physical dimensions: 508×286 mm, calculated as 96 dpi to give KWin a sane virtual density. Base-block centimetre fields report 51×29 cm due to their coarser units.
- SHA-256: `a4d702e1f460af22f4f53698836095a73722cdf8a2f65bf0dfc5207b9c36b918`.

The 74.905668 Hz result is normal: CVT labels this as the 75 Hz mode, but quantizes the pixel clock to 220.75 MHz. Installed `cvt` reports the same 74.91 Hz result and byte-for-byte-equivalent timing values:

```text
# 1920x1080 74.91 Hz (CVT 2.07M9) hsync: 84.64 kHz; pclk: 220.75 MHz
Modeline "1920x1080_75.00"  220.75  1920 2056 2264 2608  1080 1083 1088 1130 -hsync +vsync
```

Internal validation output:

```text
EDID validation: PASS
  header: 00 ff ff ff ff ff ff 00
  length: 128 bytes (1 block)
  checksums: block 0=0x09 (sum modulo 256 = 0)
  version: 1.4
  identity: VDS product 0xd150
  preferred timing: 1920x1080@74.905668 Hz (requested 75 Hz)
  detailed timing: 220.750 MHz, H 1920 2056 2264 2608, V 1080 1083 1088 1130, -HSync +VSync
  physical dimensions: 508 mm x 286 mm
  extensions: none
  edid-decode --check: PASS (EDID conformity: PASS)
```

`edid-decode --check` concludes:

```text
edid-decode 1.32.0

EDID conformity: PASS
```

## Helper behavior and safety

`scripts/virtual-display-poc` supports:

```text
virtual-display-poc up WIDTH HEIGHT FPS
virtual-display-poc down
virtual-display-poc status
```

The target is deliberately hard-coded and cross-checked:

- sysfs connector: `/sys/class/drm/card1-DP-1`
- PCI device: `0000:c5:00.0`, vendor/device `1002:1586`, driver `amdgpu`
- debugfs connector: `/sys/kernel/debug/dri/0000:c5:00.0/DP-1`
- only write allowlist:
  - `edid_override`
  - `force`
  - `trigger_hotplug`

`up` performs all generation, internal/external EDID validation, sysfs identity/status checks, polling, and KWin queries as the invoking desktop user. It refuses to proceed unless DP-1 is disconnected and absent from KWin. It then uses narrowly scoped `sudo` child processes to check the exact root-only debugfs endpoints and applies EDID → `on` → hotplug using `/usr/bin/tee`. The normal-user parent requires a non-empty byte-identical sysfs EDID, the requested DRM mode, and a matching KWin mode. A failure after the first write triggers a best-effort automatic teardown.

`down` refuses to disable a connected DP-1 unless its current EDID has this POC's valid `VDS` / `0xd150` identity. It writes exact no-newline byte strings `unspecified` and `reset`, triggers hotplug, waits for sysfs `disconnected`, and waits until KWin no longer lists DP-1.

The no-newline behavior applies to the text controls: the helper supplies exact `on`, `unspecified`, and `reset` byte strings to `/usr/bin/tee`, which adds no newline. The EDID override payload is validated binary and may naturally contain any byte, including `0x0a`. Only the hotplug control deliberately receives the already-proven `1\n` payload.

The helper refuses to run as root or as a user other than the hard-coded desktop owner `owen`. KScreen therefore runs directly as `owen`. The helper pins `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` to `/run/user/UID`, verifies the session bus is a socket, and validates or discovers the user's Wayland socket. It never calls KScreen setters and never changes priority, primary status, scale, position, or HDMI-A-1.

Only these fixed privileged subprocess forms exist; no shell is involved and paths cannot come from command-line input:

```text
/usr/bin/sudo -- /usr/bin/test -f EXACT_DEBUGFS_ENDPOINT
/usr/bin/sudo -- /usr/bin/test -w EXACT_DEBUGFS_ENDPOINT
/usr/bin/sudo -- /usr/bin/tee -- EXACT_DEBUGFS_ENDPOINT
```

The `test` calls are needed because the debugfs parent is root-traversable only. The only privileged writes are the `tee` calls to the three hard-coded DP-1 endpoints. EDID bytes/control payloads are passed through the child process's standard input; no root-owned temporary file is created. `/usr/bin/sudo`, `/usr/bin/test`, and `/usr/bin/tee` are checked to be root-owned and not group/other-writable before use. Normal sudo authentication and timestamp caching apply; no sudoers change is required.

`status` is read-only and can run without root. In that case it reports debugfs permission denial rather than treating root-only traversal as proof that controls are missing.

## Manual test and teardown

From the project root, review the code and EDID first, then run:

```bash
./scripts/virtual-display-poc up 1920 1080 75
```

Always tear down with:

```bash
./scripts/virtual-display-poc down
```

Read-only inspection is available with:

```bash
./scripts/virtual-display-poc status
```

## Limitations and concerns

- This is intentionally tied to this machine's card, PCI address, connector, and GPU PCI ID. It is not a general connector discovery tool.
- It prefers CVT normal blanking and uses CVT reduced blanking v1 only when the normal timing exceeds EDID DTD field limits. Modes that still exceed the DTD's 655.35 MHz pixel-clock limit after reduced blanking are rejected.
- The reduced-blanking-v1 fallback supports refresh rates that are exact multiples of 60 Hz, matching the installed `cvt -r` implementation. A future dynamic tool will need CVT-RBv2 or a different timing policy for high-bandwidth 90 Hz and similar requests whose normal-blanking timing does not fit.
- EDID refresh is accepted only when the quantized DTD is within 0.5 Hz of the requested rate. For 1920x1080@75, the exact represented refresh is 74.905668 Hz.
- The EDID deliberately offers one mode and no CTA/audio/HDR/VRR data. This is appropriate for the POC but not a full consumer-display profile.
- KWin's output ID is dynamic. The helper identifies it by connector name `DP-1`, not by a hard-coded KScreen ID.
- If a write fails during teardown, the helper attempts all three teardown operations and reports every failure. SSH recovery remains important during POC testing.
- Running `down` from a disconnected state clears a possibly stale override. Running it while connected is guarded by the POC EDID signature.
