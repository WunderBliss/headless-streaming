# Persistent AMDGPU virtual display: production design

Date: 2026-08-10 (Asia/Tokyo)

## Outcome

DP-1 is a persistent synthetic head, independent of Sunshine. Boot establishes a
conservative `1920x1080@60` EDID before the display manager. Plasma then enables
DP-1, selects its generated mode, and sets scale 1. Sunshine captures it by the
connector name `DP-1`; its launch prep only retunes an already-present connector.

No normal disconnect, pause, Sunshine exit, or Sunshine crash removes DP-1. The
last successfully requested mode remains active. `virtual-display baseline` is
the recovery/reset command, and `virtual-display remove` is an explicit
administrative operation.

## Components and trust boundaries

### Unprivileged controller

`scripts/virtual-display` is installed root-owned at
`/usr/local/bin/virtual-display`, but always runs as desktop user `owen`. It:

- strictly parses manual arguments or the three `SUNSHINE_CLIENT_*` variables;
- generates and validates the EDID in memory;
- discovers the unique AMD `1002:1586` card instead of trusting `card1`;
- reads DRM/sysfs state and resolves KScreen output/mode IDs by `DP-1` name;
- calls only the fixed privileged helper with `sudo -n`;
- polls DRM and KWin, enables only DP-1, selects its generated mode, and sets
  scale 1;
- verifies the fail-closed Sunshine conditions before returning success;
- serializes operations with a lock below `/run/user/<uid>/`; and
- stores only transient last-request/status metadata there.

The installed EDID module is root-owned at
`/usr/local/lib/headless-virtual-display/edid.py`. Repository execution uses the
adjacent development copy. Neither file ever executes with root privileges.

No KScreen numeric output ID is persisted. KScreen mode IDs are accepted only
after parsing the current JSON block whose connector name is exactly `DP-1`.
Every setter argument is independently restricted to `output.DP-1.*`. There is
no code path that names HDMI-A-1.

The public interface is:

```text
virtual-display up WIDTH HEIGHT FPS
virtual-display retune WIDTH HEIGHT FPS
virtual-display sunshine-up
virtual-display baseline
virtual-display status
virtual-display remove
```

`up` ensures the requested/normalized mode, creating DP-1 when absent or safely
retuning an existing managed DP-1. `retune` requires an already-connected managed
DP-1. `sunshine-up` is the stricter environment-driven retune and refuses a
missing persistent connector. `baseline` creates or retunes to 1920x1080@60.
`status` is read-only. `remove` is administrative only.

### Privileged helper

`src/headless-virtual-display-root.c` builds
`/usr/local/libexec/headless-virtual-display-root`. This is the complete privilege
boundary. It does not run a shell, execute subprocesses, import Python, read the
repository, accept a pathname, or interpret an environment variable.

Its complete command language is:

```text
headless-virtual-display-root apply
headless-virtual-display-root retune
headless-virtual-display-root remove
```

`apply` and `retune` read exactly 128 bytes from stdin. `remove` takes no data.
The helper independently requires:

- effective UID 0;
- exactly one PCI device with AMD vendor `1002`, Strix Halo device `1586`, and
  driver symlink `amdgpu`;
- a safely formed PCI BDF discovered from sysfs, not a compiled `card1` number;
- exactly one DRM card below that PCI device;
- connector `DP-1` resolving below that same PCI device;
- debugfs controls below `/sys/kernel/debug/dri/<discovered-BDF>/DP-1`;
- root-owned, regular, non-group/world-writable control files opened with
  `O_NOFOLLOW`; and
- a root-owned global operation lock in `/run/lock`.

Only `edid_override`, `force`, and `trigger_hotplug` pass the internal endpoint
allowlist. EDID validation covers the header, one-block structure, checksum,
EDID 1.4 digital/preferred flags, `VDS`/`0xd150`, zero serial, both full synthetic
text descriptors, dummy descriptor, progressive DTD bounds, physical size, and
represented refresh range. The production generator intentionally retains the
POC wire identity (`VIRTUAL-POC` / `VDS-POC-0001`) so an already-proven synthetic
display can be migrated in place; the helper requires the full layout, not just
manufacturer/product bytes.

If DP-1 is connected, every operation first requires that managed identity.
Thus a physical/unrecognized connected DP-1 is fail-closed. A failed initial
apply attempts reset/removal; a failed connected retune restores the complete
previous EDID. Text writes are exact and newline-free for `on`, `unspecified`,
and `reset`. The already-proven hotplug payload remains exactly `1\n`.

The sudoers rule authorizes user `owen` for those three exact argv forms only.
EDID bytes travel on stdin, so no caller-selected file path is privileged.

## Lifecycle and ordering

```text
boot
  -> headless-virtual-display-drm.service (system/root)
       discover Strix Halo -> apply fixed baseline EDID -> force on -> hotplug
  -> display-manager.service / SDDM
  -> Plasma/KWin user session
  -> headless-virtual-display-kwin.service (user/owen)
       virtual-display baseline -> poll KWin -> enable DP-1 -> mode -> scale 1
  -> Sunshine user service
       encoder/capture probe sees an existing DP-1

Moonlight launch
  -> Sunshine's pre-prep encoder/capture probe sees DP-1
  -> fixed global prep: virtual-display sunshine-up
       validate request -> normalize -> retune DP-1 -> verify DRM and KWin
  -> Sunshine freshly enumerates outputs
  -> KWin capture must log: [kwingrab] Screencasting output name DP-1

disconnect / quit / Sunshine crash
  -> no undo mutation; DP-1 remains at its last successful mode
```

The system unit is ordered before `display-manager.service` through a drop-in and
is also wanted by `multi-user.target`. It performs DRM work only; it does not try
to reach a user bus. The display manager has a `Wants`, not a `Requires`, so a GPU
failure does not unnecessarily eliminate the local recovery login.

The Plasma user unit is ordered after `plasma-kwin_wayland.service`, wanted by
`graphical-session.target`, and required before the Sunshine unit. Its baseline
operation is idempotent. If the early root stage worked, it does no privileged
write. If the early stage failed but sudo policy is installed, it can create the
baseline after KWin starts; Sunshine still cannot start until that verification
succeeds.

No new fixed sleep is used. DRM and KWin readiness use bounded state polling.
The packaged Sunshine unit's existing five-second `ExecStartPre` sleep is outside
this project and is not modified.

## Exact and fallback resolution policy

Requests use unsigned decimal width/height and unsigned decimal FPS (no signs,
exponents, units, shell expansion, or expressions). Width and height are bounded
at 16384, FPS at 1000, before normalization.

The algorithm is:

1. Generate and validate the exact requested width, height, and FPS. There is no
   global 3840x2160 cap on this step. Consequently modes such as
   `2560x1600@120`, `1920x1080@144`, and `1280x800@90` stay exact.
2. If exact generation fails, retain the specific rejection reason. Typical
   reasons are width/height DTD limits, width granularity, pixel-clock overflow,
   or the current CVT-RBv1 refresh limitation.
3. Set fallback FPS to the requested value clamped to the generator range
   `24..60`. This never preserves an unsupported high refresh above 60.
4. Bound fallback dimensions by both the original request and `3840x2160`, so a
   request is never enlarged merely to fill the box.
5. Enumerate widths from the largest fitting multiple of 8 downward. For each,
   derive the nearest integer height from the original aspect ratio. Reject
   widths below 320, heights below 200, dimensions outside either bound, and
   aspect rounding error above 0.5%.
6. Try candidates from largest uniform scale downward. Each candidate must pass
   internal generation/validation. This is the progressive conservative fallback
   if a larger timing cannot be represented.
7. Use the first valid candidate. Any nonzero integer-rounding aspect error is
   logged rather than hidden.
8. If no bounded generator-sized candidate can preserve the aspect ratio, try the
   guaranteed `1920x1080@60` emergency EDID. This exceptional aspect change is
   printed as an explicit uppercase warning; it is never silent.
9. Before sudo, require both internal validation and `edid-decode --check` PASS.
   The root helper then validates the binary independently a second time.

Current examples:

| Request | Effective | Decision |
| --- | --- | --- |
| 2560x1600@120 | 2560x1600@120 | exact CVT-RBv1 DTD |
| 1920x1080@144 | 1920x1080@144 | exact normal CVT DTD |
| 1280x800@90 | 1280x800@90 | exact normal CVT DTD |
| 3840x2160@90 | 3840x2160@60 | same dimensions/aspect, refresh fallback |
| 5120x2880@60 | 3840x2160@60 | 16:9 fit inside fallback box |
| 6016x3384@60 | 3840x2160@60 | 16:9 fit inside fallback box |

## Fail-closed Sunshine contract

`sunshine-up` exits zero only after all of these are simultaneously true:

- DRM reports the discovered target connector as `connected`;
- sysfs exposes the exact generated 128-byte managed EDID;
- DRM lists the effective resolution;
- KWin JSON contains exactly one connected `DP-1`;
- KWin exposes and actively selects a mode matching the effective dimensions and
  nominal refresh within 0.5 Hz;
- DP-1 is enabled; and
- scale equals 1 within 0.001.

It requires DP-1 to be connected before prep. It will not paper over a failed
boot baseline by relying on the attached HDMI monitor. This preserves the
architectural guarantee that Sunshine's earlier probe also saw the synthetic
head. Any failed condition returns nonzero, so Sunshine aborts launch instead of
reaching its dangerous first-output fallback.

The first real stream is not considered targeted until the service journal
contains the exact substring:

```text
[kwingrab] Screencasting output name DP-1
```

## State, logs, and status

The lock and last-success metadata live under
`/run/user/<uid>/headless-virtual-display/`, mode 0700. State writes are atomic,
mode 0600, and disappear on reboot. DRM/EDID remains the authority; state is only
diagnostic.

`virtual-display status` reports the dynamically discovered card/BDF, DRM state,
full synthetic identity result, DTD mode, DRM modes, baseline/retuned profile,
KWin enabled/current mode/scale, and transient last requested/effective/fallback
decision.

Useful failure logs are:

```bash
journalctl --user -u app-dev.lizardbyte.app.Sunshine.service -b --no-pager
journalctl --user -u headless-virtual-display-kwin.service -b --no-pager
sudo journalctl -u headless-virtual-display-drm.service -b --no-pager
```

## Known limitations and risks

- The base EDID DTD limits width/height to 4095 and pixel clock to 655.35 MHz.
- Width must be divisible by 8; height is 200..4095; generator refresh is
  24..240.
- CVT normal blanking is preferred. CVT-RBv1 is attempted for a DTD range
  overflow and presently accepts refreshes that are exact multiples of 60.
  CVT-RBv2/DisplayID is not implemented.
- The EDID contains one preferred mode and no CTA audio, HDR, VRR, or extensions.
- KWin/DRM hotplug can briefly blank or re-enumerate internally even when sampled
  connector state remains connected.
- The unique `1002:1586` rule deliberately fails if a future machine exposes two
  indistinguishable Strix Halo display functions.
- Sunshine 2026.516.143833 falls back to its first KWin output when `output_name`
  is missing. Helper verification reduces the risk, but only the real stream log
  proves the selected capture output.
- Sustained encode latency/performance at high resolution/refresh remains a live
  streaming test, not an EDID correctness property.
