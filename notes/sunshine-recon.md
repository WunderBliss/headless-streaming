# Sunshine integration reconnaissance

Date: 2026-08-10 (Asia/Tokyo)

## Scope and safety state

This was a reconnaissance/design pass. No Sunshine configuration, `apps.json`,
service/unit, sudoers rule, package, display setting, or boot setting was changed.
Sunshine and KWin were not restarted, no stream was started, and none of the
virtual-display helper's `up`/`down` paths were invoked.

At the end of inspection:

- `/sys/class/drm/card1-DP-1/status` was `disconnected`.
- KWin listed only the physical `HDMI-A-1` output.
- `git status --short` was clean before this report was added; this report is the
  only change made by this task.

Running `sunshine --version` caused Sunshine to emit its normal version log to
`~/.config/sunshine/sunshine.log`. That is runtime logging, not a configuration
change. The active service's authoritative history is still in the user journal.

## Executive conclusions (A-H)

### A. Exact Sunshine version/package

- Pacman package: `sunshine 2026.516.143833-4`, x86_64.
- Upstream Sunshine version: `2026.516.143833`.
- Exact upstream commit:
  `14ffa6fdaa53f7b51512be2b3d24f3939695403c`.
- Package publisher/packager: LizardByte / `LizardByte-bot`.
- Source is the configured third-party pacman repository `lizardbyte`, not an
  AUR/foreign package and not the Arch `core`/`extra` repositories. Its configured
  server is
  `https://github.com/LizardByte/pacman-repo/releases/latest/download`.
- Package homepage: <https://app.lizardbyte.dev/Sunshine>.

### B. Recommended capture method

Use `capture = kwin` for this KDE Plasma Wayland system.

The installed build has working KWin ScreenCast support through KWin's private
Wayland screencast protocol and PipeWire/DMABUF. A local encoder probe successfully
created KWin screencast streams for `HDMI-A-1`. This keeps capture in the active
KDE session and avoids choosing direct DRM/KMS capture for normal operation.

KMS capture is also compiled and operational enough to enumerate the attached
HDMI monitor and initialize it during encoder probing. It is what the current
empty/default configuration auto-selects. It requires the packaged
`CAP_SYS_ADMIN` mechanism and addresses monitors differently. It is not the
preferred integration for this KWin-managed virtual output.

### C. Recommended encoder

Use `encoder = vaapi`. Sunshine's own probe found all three VAAPI encoders:

- `h264_vaapi`
- `hevc_vaapi`
- `av1_vaapi`

Codec choice can remain client-negotiated. AV1 is preferred where the Moonlight
client has a good hardware decoder, HEVC is the practical compatibility/efficiency
fallback, and H.264 is the broadest-compatibility fallback. The separate Vulkan
encoder probe failed with `VK_ERROR_INCOMPATIBLE_DRIVER`; there is no reason to use
it while VAAPI is working.

### D. Strix Halo VAAPI encode capabilities

Both direct DRM and Wayland `vainfo` paths report:

- VA-API 1.24, libva 2.24.0.
- Mesa Gallium `26.1.6-arch1.1`.
- `AMD Radeon 8060S Graphics (radeonsi, strix_halo, ACO, DRM 3.64,
  7.1.6-arch1-1)`.

Encode profiles exposed through `VAEntrypointEncSlice`:

| Codec | Encode profiles | Driver-reported maximum picture size |
| --- | --- | --- |
| H.264 | Constrained Baseline, Main, High | 4096 x 4096 |
| HEVC | Main, Main10 | 8192 x 4352 |
| AV1 | Profile 0 | 8192 x 4352 |

All of those encode profiles advertise CBR, VBR, CQP, and QVBR rate control.
HEVC Main10 and AV1 Profile 0 advertise 10-bit YUV 4:2:0 formats. Sunshine's own
probe successfully created H.264, HEVC, and AV1 VAAPI encoders, including its
10-bit HEVC/AV1 checks. AV1 emitted a non-fatal warning that the codec cannot
control the multiple slices Sunshine requested.

Decode-only profiles also include JPEG baseline and VP9 Profile 0/Profile 2;
those are not Sunshine encode capabilities.

### E. Reliably target DP-1

With KWin capture, configure Sunshine's capture output as the connector name:

```text
capture = kwin
encoder = vaapi
output_name = DP-1
```

This recommendation comes from the exact installed commit's implementation,
not only the generic Web UI wording:

1. `kwingrab.cpp` enumerates `wl_output` objects and returns their Wayland output
   names, such as `HDMI-A-1` and `DP-1`.
2. `video.cpp` compares `config::video.output_name` with those names.
3. `kwingrab.cpp` selects the output whose name exactly equals `output_name`.

Do not hard-code KScreen's numeric output ID; it is dynamic. The production
helper should continue locating the KScreen block/mode ID by connector name.
After a future test stream starts, require the Sunshine log to say
`[kwingrab] Screencasting output name DP-1` before considering targeting proven.

Important safety wrinkle: this Sunshine release silently falls back to its first
Wayland output if the configured KWin name is absent. Therefore the `up` helper
must not return success until `kscreen-doctor -o` sees an enabled `DP-1` with the
requested mode. Even with that guard, capture of DP-1 has not yet been tested in
a real stream under this task's restrictions.

Setting DP-1 to KScreen priority 1 is not required for Sunshine targeting;
`output_name = DP-1` is stronger and does not depend on compositor ordering.
Changing priority to 1 can indirectly reorder HDMI-A-1. If making the virtual
desktop primary is desired for application placement, the future helper can do
it atomically with scale/mode setup and verify it, but it should not be treated
as the capture-selection mechanism.

### F. Prep timing and lifecycle result

There are two different answers:

**With the physical HDMI monitor attached, the proposed prep hook should work.**
The launch order at this exact commit is:

```text
Moonlight /launch request
  -> Sunshine display-device configuration
  -> encoder/capture probe (DP-1 does not exist yet; HDMI permits this to pass)
  -> proc::execute()
       -> populate SUNSHINE_CLIENT_WIDTH/HEIGHT/FPS
       -> run and synchronously wait for prep “do” commands
       -> abort launch if a prep command fails
  -> raise RTSP launch session
  -> video capture thread freshly enumerates current outputs
  -> exact-match output_name=DP-1
```

The fresh enumeration in the actual capture thread is specifically documented
in the source as obtaining the most up-to-date monitor list. If `virtual-display
up` waits for KWin before exiting, DP-1 exists by then and actual capture should
select it.

**A truly headless first launch is not reliable with a Sunshine prep command.**
Sunshine runs `display_device::configure_display()` and `video::probe_encoders()`
*before* global or per-application prep commands. With no HDMI and no already
existing DP-1, the KWin capture/encoder probe can fail before the hook that would
create DP-1 is reached. Global prep does not help: global entries are merged into
each application's prep list and execute at the same late point.

Sunshine also probes encoders during process startup. A failed startup probe does
not prevent the Web UI from starting, but it leaves no proven encoder; `/launch`
then repeats the pre-prep probe and can reject the session. A baseline display
therefore needs to exist before Sunshine startup as well as before first launch.

There is a second lifecycle mismatch: prep `undo` runs on application termination,
including Moonlight's `/cancel` / “Quit Session,” but a plain network/client
disconnect leaves the Desktop application alive for resume and does not call the
undo list. That behavior is useful for reconnect/resume but is not equivalent to
“down on every disconnect.” A Sunshine crash also cannot run undo, so `down` must
remain idempotent and recovery-safe.

Before true-headless implementation, choose one lifecycle:

1. **Lowest-risk operational design:** create a conservative baseline DP-1 before
   Sunshine needs to probe, keep it present while Sunshine is available, let the
   app prep hook replace it with the requested mode before actual capture, and
   restore the baseline rather than remove it on pause/disconnect. This changes
   the original “only exists while connected” requirement.
2. **Exact dynamic lifecycle:** change/patch Sunshine so virtual-display prep is a
   pre-probe phase, with explicit rollback, or provide an out-of-band broker that
   receives the client dimensions before `/launch`. This preserves dynamic
   create/remove semantics but is more engineering and maintenance.
3. **Development only:** keep HDMI attached. The current ordering should work,
   but it masks the true-headless pre-probe problem.

The report recommends option 1 for the smallest reliable system, unless removal
at idle is a hard requirement. If it is, option 2 is required; the present
global/per-app hook position cannot guarantee it.

### G. Recommended privilege architecture

Use one root-owned, fixed-purpose helper plus one exact `NOPASSWD` authorization
for that helper later. Do not grant Sunshine root, generic `tee`, arbitrary
debugfs access, or `CAP_SYS_ADMIN` for virtual-display management.

Recommended split:

- `scripts/virtual-display` remains an unprivileged `[redacted]` program. It validates
  client inputs, generates/validates EDID, reads sysfs, polls DRM/KWin, invokes
  `kscreen-doctor`, and performs rollback orchestration.
- Install a separate single-purpose helper in a root-controlled path such as
  `/usr/local/libexec/headless-virtual-display-root`. It must not import code from
  this user-writable repository.
- The privileged helper hard-codes the same PCI/card/connector identity and only
  opens these three absolute endpoints:
  `edid_override`, `force`, and `trigger_hotplug` under
  `/sys/kernel/debug/dri/0000:c5:00.0/DP-1/`.
- It accepts only tightly validated `apply` and `remove` operations. `apply`
  consumes a bounded EDID blob, independently checks header/length/checksum,
  POC identity and requested mode, checks DP-1 is disconnected, then performs
  EDID -> exact `on` -> hotplug. `remove` verifies the current synthetic EDID (or
  safely handles an already-disconnected state), then writes exact no-newline
  `unspecified` and `reset`, followed by hotplug.
- It must use no shell, no user-selected path, no arbitrary command, and no
  user-controlled debugfs target. Add locking and fail-safe rollback.
- The unprivileged helper invokes it with `sudo -n` so an unattended prep command
  fails immediately rather than waiting for a password prompt.

A system service/socket with a narrow authenticated API can be stronger and
avoids sudoers, but it adds a daemon, protocol, lifecycle, and polkit/systemd
policy surface for only three writes. For this single-user machine, the root-owned
helper plus one exact sudoers grant is the smallest auditable boundary. No rule
was added in this task.

The current POC's narrow `sudo /usr/bin/tee` calls are appropriate for interactive
testing but cannot run unattended without cached credentials and should not be
the production sudoers interface. Never authorize the user-writable
`scripts/virtual-display` itself as root.

The packaged `/usr/bin/sunshine` already has
`cap_sys_admin,cap_sys_nice=p` for features such as KMS. The live process currently
has an empty effective capability set but retains `CAP_SYS_ADMIN` and
`CAP_SYS_NICE` in its permitted set; its KWin probe logged that it dropped
elevated privileges. Do not reuse or expand that authority for the display helper.
A future KWin-only packaging/hardening pass should separately assess whether the
Sunshine file capabilities can be removed.

### H. Blockers and unknowns before implementation

1. The true-headless pre-probe ordering needs the lifecycle decision in section F.
2. “Disconnect” must be defined: transient disconnect/pause is resumable and does
   not run prep undo; “Quit Session”/application termination does.
3. KWin capture falls back to the first output when `DP-1` is missing. A real
   two-monitor test stream must verify the log names DP-1 and never HDMI-A-1.
4. No unattended privilege authorization exists yet. The existing POC may prompt
   for sudo and is intentionally unsuitable as a Sunshine hook.
5. The future root helper must be installed root-owned; running a user-writable
   Python script under passwordless sudo would invalidate the privilege boundary.
6. KScreen's scale/mode/priority mutation has not been exercised in this task.
   Priority is unnecessary for capture and may indirectly reorder HDMI.
7. The hard-coded `card1` and PCI BDF are safe fail-closed checks on this boot, but
   card numbering/BDF stability across firmware/kernel changes should be decided
   before making the helper permanent.
8. `vainfo` proves exposed driver capabilities, and Sunshine's probe proves codec
   initialization; sustained performance/latency at target high modes remains a
   later streaming benchmark.
9. The exact mechanism that originally started this disabled user unit is not
   retained by systemd. Its current ownership/cgroup is unambiguous.

## Installed locations and current state

### Configuration, applications, unit, logs, executable

| Item | Location/state |
| --- | --- |
| Configuration | `~/.config/sunshine/sunshine.conf`; 0 bytes, mode 0644, owner `[redacted]:[redacted]` |
| Applications | `~/.config/sunshine/apps.json`; 679 bytes, mode 0644, identical to packaged `/usr/share/sunshine/apps.json` |
| Packaged user unit | `/usr/lib/systemd/user/app-dev.lizardbyte.app.Sunshine.service` |
| Unit alias | `sunshine.service` in the user manager only |
| KWin permission desktop file | `/usr/share/applications/dev.lizardbyte.app.Sunshine.kwin.desktop` |
| Per-user file log | `~/.config/sunshine/sunshine.log`; currently contains the version inspection output |
| Service log | user journal: `journalctl --user -u app-dev.lizardbyte.app.Sunshine.service` |
| Executable | `/usr/bin/sunshine`; root-owned mode 0755, 22,451,640 bytes |
| File capabilities | `cap_sys_admin,cap_sys_nice=p` |

`~/.config/sunshine/sunshine_state.json` and the `credentials/` certificate files
also exist. Their contents were not printed or copied because they are unrelated
sensitive state.

The current `apps.json` is the packaged example: Desktop, a sample XRandR-based
Low Res Desktop, and Steam Big Picture. There is no virtual-display hook yet.

### Service/session ownership

Sunshine is currently the main process of the **user** unit
`app-dev.lizardbyte.app.Sunshine.service`:

- PID 36313, UID/GID 1000 (`[redacted]`), parent PID 1028 (`systemd --user`).
- Active/running since 2026-08-10 21:11:49 JST.
- Unit file state `disabled` (preset enabled); there are no drop-ins.
- No system `sunshine.service` exists and no separate manually launched Sunshine
  process was found.
- The active desktop login is logind session 8: `[redacted]`, `sddm`, KDE, Wayland,
  seat0/tty1, active. Session 3 is the user's systemd-manager session.

The user manager environment that starts Sunshine contains the required desktop
context:

```text
HOME=/home/[redacted]
XDG_RUNTIME_DIR=/run/user/1000
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
WAYLAND_DISPLAY=wayland-0
DISPLAY=:1
XDG_SESSION_TYPE=wayland
XDG_CURRENT_DESKTOP=KDE
XDG_SESSION_DESKTOP=KDE
KDE_FULL_SESSION=true
KDE_SESSION_VERSION=6
```

Reading `/proc/36313/environ` was denied, likely because the file-capability
executable is non-dumpable. The unit declares no `Environment=` overrides, and
Sunshine's process launcher starts from its own current environment. A clean-room
invocation containing only the manager values above successfully ran
`/usr/bin/kscreen-doctor -o` and queried the live KWin session. This is strong
evidence that non-elevated Sunshine prep commands can use KScreen as `[redacted]`.
The remaining direct proof would require temporarily adding a prep command, which
was intentionally not done.

At inspection time KScreen reported only:

```text
Output: 1 HDMI-A-1
  enabled, connected, priority 1
  mode 2560x1600@60.00
  scale 1.25
```

DP-1 was absent from KWin and disconnected in DRM.

## Installed feature support

### Capture and encoding backends

The installed Web UI exposes Linux capture choices `nvfbc`, `wlr`, `kms`, `x11`,
`kwin`, and `portal`, plus automatic selection. It exposes encoders `nvenc`,
`vaapi`, and `vulkan`, plus automatic selection. Runtime/link evidence relevant
to this machine:

- KWin: built and successfully probed through PipeWire.
- KMS: built, enumerated `Monitor 0 is HDMI-A-1: GWD ARZOPA`, and is the current
  auto-selected capture path.
- VAAPI: linked through libva/libva-drm and successfully selected.
- PipeWire, Wayland, GBM, and libdrm are linked by the executable.
- `libva-mesa-driver` is installed as Sunshine's AMD encoding dependency.

### Global/per-application prep and client variables

The installed UI and exact source support both:

- Global `global_prep_cmd` entries, run before/after any application unless that
  application sets `exclude-global-prep-cmd`.
- Per-application `prep-cmd` entries with `do` and `undo` commands.

On Linux these commands are non-elevated. Every command receives, among other
variables:

```text
SUNSHINE_CLIENT_WIDTH
SUNSHINE_CLIENT_HEIGHT
SUNSHINE_CLIENT_FPS
```

The exact source populates them from the launch session before running prep.
Each `do` command is launched synchronously; Sunshine waits for it and aborts the
application launch if it exits nonzero. Undo commands run in reverse order and
their failures are warnings rather than launch errors.

For the future app entry, avoid shell interpolation entirely. Add a fixed
unprivileged command such as:

```text
/home/[redacted]/projects/headless-streaming/scripts/virtual-display sunshine-up
```

and have that subcommand read and strictly validate the three `SUNSHINE_CLIENT_*`
variables itself. The fixed undo command can be:

```text
/home/[redacted]/projects/headless-streaming/scripts/virtual-display down
```

This is a future design example only; neither command was configured or run.

## Review of the current POC and next helper design

### Current POC

`scripts/virtual-display-poc` and `scripts/edid.py` retain the right basic split:

- EDID generation/validation, sysfs reads, polling, and KScreen calls run as
  normal desktop user `[redacted]`.
- Only fixed debugfs endpoint tests/writes run through sudo.
- The helper pins card1, DP-1, PCI BDF `0000:c5:00.0`, AMD vendor/device
  `1002:1586`, and the amdgpu driver.
- `up` refuses an already-connected connector and verifies DRM/KWin after hotplug.
- `down` protects a physical display by requiring the POC EDID identity when
  connected.
- Text controls use exact no-newline `on`, `unspecified`, and `reset`; only the
  proven hotplug payload is `1\n`.
- The EDID is generated in memory and independently validated with `edid-decode`.

The main production gaps are unattended privilege, locking/idempotence across
Sunshine lifecycle events, KScreen configuration, and the pre-probe ordering.

### Proposed `scripts/virtual-display`

Keep the public interface and add an environment-oriented entry point:

```text
virtual-display up WIDTH HEIGHT FPS
virtual-display down
virtual-display status
virtual-display sunshine-up
```

Recommended `up` transaction:

1. Refuse root/wrong user; take a per-user lock so manual and Sunshine calls
   cannot overlap.
2. Validate numeric bounds, GPU/card/connector identity, DP-1 disconnected, and
   DP-1 absent from KWin.
3. Generate and validate an EDID in memory.
4. Call the root-owned helper with `sudo -n` for the fixed apply transaction.
5. Poll DRM status/EDID/mode and KWin discovery exactly as the POC does.
6. Resolve the KScreen output and mode IDs by connector name, not numeric output
   ID. In one atomic KScreen call, enable DP-1, select the exact generated mode,
   and set scale 1. Use the parsed mode ID because CVT clock quantization means a
   request such as 75 Hz is exposed as about 74.91 Hz.
7. Only if primary-desktop behavior is actually required, also set
   `output.DP-1.priority.1`; otherwise leave priorities untouched.
8. Re-query and require enabled/connected, scale 1, requested mode, and optional
   priority before returning 0. Any failure rolls back through the root helper.

Recommended `down` transaction:

1. Take the same lock and query KWin before mutation.
2. If connected, require the managed EDID identity.
3. Call the fixed root helper's idempotent remove transaction using `sudo -n`.
4. Poll DRM disconnected and KWin absence. Treat an already-removed managed
   connector as success, but never remove an unrecognized physical DP display.

Keep transient ownership/state under `/run/user/1000`, not in persistent KDE or
Sunshine configuration. The helper should log concise state transitions to
stderr so they appear in the Sunshine user journal.

## Source-confirmed timing details

The conclusions above were checked against the exact packaged commit:

- [`src/nvhttp.cpp`](https://github.com/LizardByte/Sunshine/blob/14ffa6fdaa53f7b51512be2b3d24f3939695403c/src/nvhttp.cpp)
  performs display configuration and encoder probing before `proc::proc.execute`,
  then raises the RTSP launch session.
- [`src/process.cpp`](https://github.com/LizardByte/Sunshine/blob/14ffa6fdaa53f7b51512be2b3d24f3939695403c/src/process.cpp)
  merges global/per-app prep, injects client variables, waits for `do`, and runs
  reverse-order `undo` on process termination.
- [`src/video.cpp`](https://github.com/LizardByte/Sunshine/blob/14ffa6fdaa53f7b51512be2b3d24f3939695403c/src/video.cpp)
  freshly enumerates output names when the real capture thread starts.
- [`src/platform/linux/kwingrab.cpp`](https://github.com/LizardByte/Sunshine/blob/14ffa6fdaa53f7b51512be2b3d24f3939695403c/src/platform/linux/kwingrab.cpp)
  enumerates Wayland output names, exact-matches `output_name`, and falls back to
  its first output when no match exists.
- [`src/platform/linux/misc.cpp`](https://github.com/LizardByte/Sunshine/blob/14ffa6fdaa53f7b51512be2b3d24f3939695403c/src/platform/linux/misc.cpp)
  selects the KWin/KMS backend and drops effective elevated privileges after the
  KMS path is passed.
- [`src/stream.cpp`](https://github.com/LizardByte/Sunshine/blob/14ffa6fdaa53f7b51512be2b3d24f3939695403c/src/stream.cpp)
  keeps an application running when the last client session ends, supporting
  pause/resume rather than invoking prep undo.
- Installed app UI links to the official
  [Sunshine application examples](https://docs.lizardbyte.dev/projects/sunshine/latest/md_docs_2app__examples.html).

## I. Files inspected

Project files:

- `scripts/virtual-display-poc`
- `scripts/edid.py`
- `notes/edid-poc.md`

Installed/user Sunshine files:

- `/usr/bin/sunshine`
- `/usr/lib/systemd/user/app-dev.lizardbyte.app.Sunshine.service`
- `/usr/share/applications/dev.lizardbyte.app.Sunshine.kwin.desktop`
- `/usr/share/sunshine/apps.json`
- `/usr/share/sunshine/web/apps.html`
- `/usr/share/sunshine/web/assets/locale/en.json`
- `/usr/share/sunshine/web/assets/config-*.js`
- `~/.config/sunshine/sunshine.conf`
- `~/.config/sunshine/apps.json`
- `~/.config/sunshine/sunshine.log`
- names/metadata only for `~/.config/sunshine/sunshine_state.json` and
  `~/.config/sunshine/credentials/*`
- `/etc/pacman.conf`

Runtime paths/interfaces:

- `/sys/class/drm/card1-DP-1/status`
- `/proc/36313/status`
- user systemd manager/unit state and environment
- user journal for `app-dev.lizardbyte.app.Sunshine.service`
- logind session metadata
- KWin/KScreen's read-only output query
- `/dev/dri/renderD128` through `vainfo`

Exact upstream commit files inspected over HTTPS are listed in the prior section,
plus `src/display_device.cpp`, `src/rtsp.cpp`, and `src/main.cpp`.

## Exact commands run

Commands were read-only except for Sunshine's normal logging side effect described
at the top and creation of this Markdown report. Pipes only filtered output.

```bash
pacman -Qi sunshine
pacman -Si sunshine
pacman -Qm | rg -i '^sunshine' || true
pacman -Qo /usr/bin/sunshine /usr/lib/systemd/user/app-dev.lizardbyte.app.Sunshine.service /usr/share/sunshine/apps.json /usr/share/applications/dev.lizardbyte.app.Sunshine.kwin.desktop
pacman-conf --repo-list
pacman-conf lizardbyte 2>/dev/null || true
rg -n '^\[lizardbyte\]|^Server|^Include' /etc/pacman.conf /etc/pacman.d/*.conf 2>/dev/null || true
sed -n '96,112p' /etc/pacman.conf

/usr/bin/sunshine --version
/usr/bin/sunshine --help 2>&1 | sed -n '1,140p'
stat -c '%A %a %U:%G %s %n' /usr/bin/sunshine /usr/lib/systemd/user/app-dev.lizardbyte.app.Sunshine.service /usr/share/sunshine/apps.json "$HOME/.config/sunshine/sunshine.conf" "$HOME/.config/sunshine/apps.json" "$HOME/.config/sunshine/sunshine.log"
getcap /usr/bin/sunshine
ldd /usr/bin/sunshine | rg -i 'va|drm|pipewire|wayland|gbm'

find "$HOME/.config/sunshine" -maxdepth 2 -printf '%M %u:%g %s %p\n' | sort
cmp -s "$HOME/.config/sunshine/apps.json" /usr/share/sunshine/apps.json; printf 'apps.json matches packaged default: %s\n' "$?"
sed -n '1,240p' "$HOME/.config/sunshine/apps.json"
sed -n '1,240p' /usr/share/sunshine/apps.json
sed -n '1,120p' "$HOME/.config/sunshine/sunshine.log"
sed -n '1,220p' /usr/lib/systemd/user/app-dev.lizardbyte.app.Sunshine.service
sed -n '1,160p' /usr/share/applications/dev.lizardbyte.app.Sunshine.kwin.desktop

systemctl --user status app-dev.lizardbyte.app.Sunshine.service --no-pager --full
systemctl --user is-enabled app-dev.lizardbyte.app.Sunshine.service || true
systemctl --user show app-dev.lizardbyte.app.Sunshine.service -p FragmentPath -p DropInPaths -p MainPID -p User -p Group -p Environment -p ExecStart -p ActiveState -p SubState -p UnitFileState
systemctl --user cat app-dev.lizardbyte.app.Sunshine.service
systemctl status sunshine.service --no-pager --full || true
pgrep -a -u [redacted] -x sunshine || true
sun_pid=$(systemctl --user show app-dev.lizardbyte.app.Sunshine.service -p MainPID --value); ps -o pid=,ppid=,user=,group=,lstart=,cmd= -p "$sun_pid"; getpcaps "$sun_pid"; sed -n '/^Cap/p;/^Uid:/p;/^Gid:/p;/^Groups:/p;/^NoNewPrivs:/p' "/proc/$sun_pid/status"
sun_pid=$(systemctl --user show app-dev.lizardbyte.app.Sunshine.service -p MainPID --value); tr '\0' '\n' < "/proc/$sun_pid/environ"
systemctl --user show-environment | rg '^(HOME|PATH|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS|DISPLAY|WAYLAND_DISPLAY|XDG_SESSION_TYPE|XDG_CURRENT_DESKTOP|XDG_SESSION_DESKTOP|KDE_FULL_SESSION|KDE_SESSION_VERSION)='

loginctl list-sessions --no-legend
loginctl show-session 1 -p Id -p Name -p User -p Type -p Class -p State -p Active -p Remote -p Leader -p Service -p Desktop -p Display -p TTY 2>/dev/null || true
loginctl show-user [redacted] -p UID -p State -p Linger -p Sessions -p Display
loginctl show-session 8 -p Id -p Name -p User -p Type -p Class -p State -p Active -p Remote -p Leader -p Service -p Desktop -p Display -p TTY
loginctl show-session 3 -p Id -p Name -p User -p Type -p Class -p State -p Active -p Remote -p Leader -p Service -p Desktop -p Display -p TTY

journalctl --user -u app-dev.lizardbyte.app.Sunshine.service --since '2026-08-10 21:11:00' --no-pager -o cat | rg -i 'sunshine version|commit|capture|screencast|monitor|display|kms|kwin|pipewire|vaapi|h\.264|hevc|av1|vulkan|warning|error|privilege|capabilit'

vainfo --display drm --device /dev/dri/renderD128
vainfo --display wayland
vainfo --help 2>&1 | sed -n '1,160p'
vainfo --all --display drm --device /dev/dri/renderD128

env -i HOME=/home/[redacted] USER=[redacted] LOGNAME=[redacted] PATH=/usr/local/sbin:/usr/local/bin:/usr/bin XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=KDE XDG_SESSION_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 WAYLAND_DISPLAY=wayland-0 DISPLAY=:1 /usr/bin/kscreen-doctor -o
kscreen-doctor --help
kscreen-doctor --help-all 2>/dev/null || true
strings /usr/bin/kscreen-doctor | rg -i -C 2 'priority|primary'

rg -n -i -m 80 'KWin Screencast|KMS|VA-API|VAAPI|global_prep_cmd|prep-cmd|exclude-global-prep-cmd|SUNSHINE_CLIENT_(WIDTH|HEIGHT|FPS)|output_name' /usr/share/sunshine /usr/share/applications /usr/lib/systemd/user 2>/dev/null
sed -n '80,180p' /usr/share/sunshine/web/apps.html
sed -n '345,415p' /usr/share/sunshine/web/apps.html
rg -n '"(capture|capture_desc|capture_kms|capture_kwin|encoder|encoder_vaapi|global_prep_cmd|global_prep_cmd_desc|output_name|output_name_desc_unix)"' /usr/share/sunshine/web/assets/locale/en.json
rg -o 'value:"(autodetect|nvfbc|wlr|kms|x11|kwin|portal|nvenc|vaapi|vulkan)"' /usr/share/sunshine/web/assets/config-*.js | sort -u

sed -n '1,280p' scripts/virtual-display-poc
sed -n '260,620p' scripts/virtual-display-poc
sed -n '1,320p' scripts/edid.py
sed -n '320,700p' scripts/edid.py
sed -n '1,280p' notes/edid-poc.md
printf 'DP-1 status: '; tr -d '\n' </sys/class/drm/card1-DP-1/status; printf '\n'
git status --short
git diff -- scripts/virtual-display-poc scripts/edid.py notes/edid-poc.md

test -s notes/sunshine-recon.md
rg -n '[[:blank:]]+$' notes/sunshine-recon.md || true
printf 'DP-1: '; tr -d '\n' </sys/class/drm/card1-DP-1/status; printf '\n'
systemctl --user is-active app-dev.lizardbyte.app.Sunshine.service
/usr/bin/kscreen-doctor -o | sed -n '1,8p'
git status --short
wc -l -c notes/sunshine-recon.md
```

Exact-version upstream source was inspected with `curl -fsSL` from the raw URLs
under this prefix, then filtered with `rg`, `nl`, and `sed` for the named symbols
and line ranges:

```text
https://raw.githubusercontent.com/LizardByte/Sunshine/14ffa6fdaa53f7b51512be2b3d24f3939695403c/
```

The inspected paths/symbols were:

```text
src/nvhttp.cpp             launch, proc::proc.execute, launch_session_raise
src/process.cpp            execute, prep_cmds, SUNSHINE_CLIENT_*, terminate, parse
src/video.cpp              reset_display, refresh_displays, captureThread, probe_encoders
src/platform/linux/kwingrab.cpp  get_output_names, start, kwin_display_names
src/platform/linux/kmsgrab.cpp   output-name search
src/platform/linux/misc.cpp      display_names, display, capability drop
src/display_device.cpp      configure_display, map_output_name
src/stream.cpp              last-session teardown/pause behavior
src/rtsp.cpp                session_count, terminate_sessions
src/main.cpp                process-termination reference search
```

One attempted `jq` extraction failed because `jq` is not installed; no package was
installed. Four guessed upstream display-device paths were checked by HTTP status
to locate `src/display_device.cpp`/`.h`; the two `src/display_device/display_*`
guesses returned 404. No local source checkout or temporary source file was
created.
