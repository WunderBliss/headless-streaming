# DRM/KMS reconnaissance: AMD Strix Halo, KDE Plasma Wayland

Date: 2026-08-10 (Asia/Tokyo)

Scope: read-only inspection. No system configuration, display state, services, packages, `/sys`, or `/proc` were changed. The only write was creation of this report.

## Executive conclusions

### A. Topology summary

- One GPU: AMD Strix Halo at PCI `0000:c5:00.0`, device `1002:1586`, subsystem `2014:801d`, driven by `amdgpu`.
- The amdgpu device is DRM `card1`; its render node is `renderD128`. (`minor 0` was initially occupied by `simpledrm`; amdgpu initialized on minor 1.)
- Kernel DRM exposes one connected `HDMI-A-1`, eight disconnected DP connectors (`DP-1` through `DP-8`), and one disabled writeback connector.
- The connected HDMI sink supplies a 256-byte EDID and modes up to 2560x1600. All disconnected DP connectors have zero-byte EDIDs and no modes.
- KWin sees only `HDMI-A-1`; it does not expose any of the disconnected DP connectors as outputs.
- The active desktop is KDE Plasma on Wayland. KWin uses HDMI at 2560x1600@60 Hz, scaled 1.25 (logical geometry 2048x1280), priority 1.
- VCN encode hardware is enumerated by amdgpu (two VCN 4.0.5 instances). `/dev/dri/renderD128` exists and maps to the GPU, but `vainfo` is not installed, so codec/profile support was not verified through VAAPI.
- Sunshine is not installed as a package or executable, and no user/system Sunshine unit exists.

### B. Best synthetic-display candidate

`card1-DP-1` is the simplest first candidate, but only by convention: it is the first of eight otherwise indistinguishable disconnected DP connectors on the target amdgpu card. It has status `disconnected`, is disabled, has no EDID, and has no modes. The same kernel-visible facts apply to `DP-2` through `DP-8`; this reconnaissance found no evidence that one is electrically or logically superior. A later privileged, read-only inspection of the per-connector debugfs tree should decide the candidate based on which connector actually has the required controls.

Do not use `Writeback-1` as the EDID-override candidate: it is a DRM writeback connector, not a disconnected physical DP/HDMI sink, and its status is `unknown` rather than `disconnected`.

### C. Native debugfs EDID override viability

**Plausible, but not confirmed on this running system.** Positive evidence:

- `CONFIG_DRM=y`, `CONFIG_DRM_KMS_HELPER=y`, `CONFIG_DRM_LOAD_EDID_FIRMWARE=y`, `CONFIG_DRM_AMDGPU=m`, and `CONFIG_DEBUG_FS=y`.
- The native amdgpu DC stack enumerates eight disconnected DP connectors that could potentially be supplied an override EDID and forced on.
- Debugfs is mounted on the host at `/sys/kernel/debug` as `rw,nosuid,nodev,noexec,relatime`.
- amdgpu module parameters show `modeset=-1`, `dc=-1`, and `virtual_display=(null)`; this is the native DC/KMS path, with no amdgpu virtual-display parameter configured.

The important limitation is that an EDID override does not create a brand-new DRM connector. It can only make one of the already enumerated connectors advertise synthetic sink data, normally together with a connector force/hotplug operation. Whether this kernel exposes the needed controls under `/sys/kernel/debug/dri/1/...` could not be checked: `/sys/kernel/debug` is mode `0700 root:root`, the current user cannot traverse it, and passwordless sudo is unavailable. Therefore the presence and permissions of `edid_override`, `force`, and `trigger_hotplug` remain unverified. No write was attempted.

### D. Blockers and uncertainties

- **Debugfs control files unverified:** the mount exists and is host-writable by root, but traversal is root-only. `sudo -n` reported that a password is required.
- **KWin ignores disconnected connectors:** `kscreen-doctor -o` lists only HDMI. A successful override/force plus hotplug would need to make the chosen connector appear connected before KWin could manage it.
- **Physical routing unknown:** sysfs and boot logs enumerate DP-1..DP-8 but do not identify which USB-C/DP alt-mode or board connector each name represents. No DP connector is distinguishable as the best candidate from current evidence.
- **VAAPI profiles unverified:** a render node and VCN encode engines exist, but `vainfo` is absent. The installed Mesa package provides `libva-mesa-driver` on this system, but actual encode entry points were not exercised.
- **No Sunshine installation to inspect:** package database, executable lookup, and service checks were all negative.
- **Kernel warnings:** boot logs contain `Failed to setup vendor infoframe on connector HDMI-A-1: -22` and two `REG_WAIT timeout ... optc35_disable_crtc` messages. The display subsequently came up and no further DRM failure was visible in the filtered current-boot log, but these are relevant DC/display warnings.
- **Session metadata limitation:** environment variables clearly identify KDE Wayland, and KScreen successfully queried KWin. `loginctl show-session self` failed because the reconnaissance process was not considered part of a known logind session; `loginctl list-sessions` showed user session 8 on seat0/tty1 and user manager session 3.

## 1. Basic platform

- OS: Arch Linux (rolling).
- Kernel: `7.1.6-arch1-1` ([redacted], 04 Aug 2026 11:19:27 +0000 x86_64`).
- Mesa: `1:26.1.6-1`.
- libva: `2.24.1-1`; libdrm: `2.4.134-1`.
- GPU: AMD/ATI Strix Halo (Radeon 8050S/8060S family), PCI `1002:1586`, revision `c1`, subsystem `2014:801d`, at `0000:c5:00.0`.
- Kernel driver/module: `amdgpu`.
- Display Core: v3.2.378 on DCN 3.5.1; DMUB firmware `0x09004A00`.
- Graphics/encode IP observed: gfx11, two VCN 4.0.5 instances, JPEG 4.0.5.
- Memory reported by driver: 32768 MiB VRAM, 32768 MiB BAR, 512 MiB GART.

Relevant visible amdgpu parameters:

| Parameter | Value | Relevance |
|---|---:|---|
| `modeset` | `-1` | default KMS behavior |
| `dc` | `-1` | default Display Core behavior |
| `dcdebugmask` | `0` | no DC debug mask |
| `dcfeaturemask` | `2` | non-default-looking feature bitmask; meaning not inferred here |
| `virtual_display` | `(null)` | no virtual display parameter configured |
| `audio` | `-1` | default display-audio behavior |
| `hdmi_hpd_debounce_delay_ms` | `0` | no additional HDMI HPD delay configured |
| `forcelongtraining` | `0` | DP long training not forced |
| `seamless` | `-1` | default behavior |
| `deep_color` | `0` | disabled parameter |
| `sg_display` | `-1` | default behavior |

All readable amdgpu parameters were enumerated. `gartsize`, `gttsize`, `moverate`, and `vramlimit` returned permission denied; no values were changed.

## 2. DRM topology

`/sys/class/drm` contains:

```text
card1
card1-DP-1
card1-DP-2
card1-DP-3
card1-DP-4
card1-DP-5
card1-DP-6
card1-DP-7
card1-DP-8
card1-HDMI-A-1
card1-Writeback-1
renderD128
version
```

Every connector symlink resolves beneath PCI device `0000:c5:00.0/drm/card1`.

| Connector | Card | Type | ID | Status | Enabled | DPMS | EDID bytes read | Modes |
|---|---|---|---:|---|---|---|---:|---|
| `HDMI-A-1` | card1 | HDMI Type A | 438 | connected | enabled | On | 256 | 2560x1600, 2560x1440, 1920x1200, 1920x1080 (two entries), 1680x1050, 1440x900, 1280x800, 1280x720 (two), 1024x768, 800x600, 720x480 (four), 640x480 (three) |
| `DP-1` | card1 | DisplayPort | 448 | disconnected | disabled | Off | 0 | none |
| `DP-2` | card1 | DisplayPort | 455 | disconnected | disabled | Off | 0 | none |
| `DP-3` | card1 | DisplayPort | 461 | disconnected | disabled | Off | 0 | none |
| `DP-4` | card1 | DisplayPort | 467 | disconnected | disabled | Off | 0 | none |
| `DP-5` | card1 | DisplayPort | 473 | disconnected | disabled | Off | 0 | none |
| `DP-6` | card1 | DisplayPort | 479 | disconnected | disabled | Off | 0 | none |
| `DP-7` | card1 | DisplayPort | 485 | disconnected | disabled | Off | 0 | none |
| `DP-8` | card1 | DisplayPort | 491 | disconnected | disabled | Off | 0 | none |
| `Writeback-1` | card1 | DRM writeback | 497 | unknown | disabled | On | 0 | none |

The sysfs `edid` pseudo-files report a nominal `stat` size of zero, as is normal for dynamic sysfs attributes; reading them with `wc -c` returned 256 bytes for HDMI and zero for every other connector.

## 3. `/dev/dri`

Host view:

```text
/dev/dri/card1       crw-rw----+ root video  226,1
/dev/dri/renderD128  crw-rw-rw-  root render 226,128
```

By-path mapping:

```text
pci-0000:c5:00.0-card   -> ../card1
pci-0000:c5:00.0-render -> ../renderD128
```

Thus both nodes map unambiguously to Strix Halo `0000:c5:00.0`. User `owen` is not a member of `video` or `render` (groups are `owen,wheel`), but the card ACL explicitly grants `owen:rw-`, and the render node grants `other::rw-`.

The initial sandboxed view hid `/dev/dri`; the approved host-side read showed the nodes above.

## 4. DRM debugfs

- `/sys/kernel/debug` is a debugfs mount.
- Host mount options: `rw,nosuid,nodev,noexec,relatime`.
- `/sys/kernel/debug` permissions: `drwx------ root root`.
- Ordinary-user `ls`/`find` of `/sys/kernel/debug/dri` failed with `Permission denied`.
- A non-interactive read-only `sudo` attempt failed with `sudo: a password is required`.
- Consequently, the contents of `/sys/kernel/debug/dri/*`, per-connector directories, and the existence/mode/owner/group of `edid_override`, `force`, and `trigger_hotplug` could not be reported. Their absence must not be inferred from this permission failure.

No debugfs file was opened for writing and no connector state was changed.

## 5. KDE/KWin view

Environment:

```text
XDG_SESSION_TYPE=wayland
WAYLAND_DISPLAY=wayland-0
DISPLAY=:1
XDG_CURRENT_DESKTOP=KDE
KDE_FULL_SESSION=true
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
```

KScreen/libkscreen version: `6.7.4-1`.

`kscreen-doctor -o` reports one output:

- Output ID 1, name `HDMI-A-1`, UUID `80d84e01-911b-40ff-8dc1-05d964df0f95`.
- Connected and enabled.
- Priority 1 (the effective primary/highest-priority output).
- Current/preferred mode ID 1: 2560x1600@60.00.
- Logical geometry 0,0 2048x1280; scale 1.25; normal rotation.
- No custom modes; HDR and wide color gamut disabled; VRR policy Never.

KWin reports no disconnected outputs at all. In particular, DP-1 through DP-8 are visible to DRM sysfs but absent from KScreen's output list.

## 6. Sunshine-relevant capture and encode capability

- VAAPI-capable DRM render device is structurally present: `/dev/dri/renderD128` on the Strix Halo GPU.
- Kernel logs enumerate two VCN unified engines and report VCN firmware with encoder version 1.24.
- Mesa `1:26.1.6-1` is installed and provides the queried `libva-mesa-driver` package name; `libva 2.24.1-1` is installed.
- `vainfo` is not installed (`command not found`), so no VAAPI codec/profile output is available.
- `vulkan-radeon` and `lib32-mesa` are not installed, which is not itself a VAAPI blocker.
- No installed package name contains `sunshine`; `sunshine` is not on PATH; both user and system `sunshine.service` lookups returned “Unit ... could not be found.”

No encoder was opened and Sunshine configuration was not accessed or changed.

## 7. Kernel log findings

Key current-boot messages:

- `simpledrm` initialized on minor 0, then amdgpu initialized KMS for `1002:1586` and registered on minor 1.
- Native display IP block `dm` was detected; Display Core v3.2.378 initialized on DCN 3.5.1.
- HDMI-A-1 and DP-1 through DP-8 were all explicitly enumerated in PSR-capability messages.
- DMUB initialized successfully, and the driver reported DP-to-HDMI FRL PCON support.
- amdgpu initialized successfully and installed `amdgpudrmfb` as primary framebuffer.
- Warnings/errors of interest:
  - `Failed to setup vendor infoframe on connector HDMI-A-1: -22`
  - two `REG_WAIT timeout 1us * 100000 tries - optc35_disable_crtc` messages (lines 163 and 166)
- No additional amdgpu/DRM connector, KMS, DC, or hotplug errors appeared in the filtered current-boot journal.
- Direct `dmesg` produced no filtered output in this context; the journal supplied the boot evidence.

### E. Exact commands run

The commands below are reproduced as executed. They are read-only except that the report itself was later created with the workspace patch mechanism.

```bash
uname -a
uname -r
printf '%s\n' "$XDG_SESSION_TYPE" "$WAYLAND_DISPLAY" "$XDG_CURRENT_DESKTOP" "$KDE_FULL_SESSION"
printf '%s\n' '--- os-release ---'
sed -n '1,120p' /etc/os-release
printf '%s\n' '--- mesa packages ---'
pacman -Q mesa lib32-mesa vulkan-radeon libva-mesa-driver 2>&1
printf '%s\n' '--- PCI display devices ---'
lspci -Dnnk | sed -n '/VGA compatible controller\|Display controller\|3D controller/,+4p'
printf '%s\n' '--- amdgpu parameters ---'
for f in /sys/module/amdgpu/parameters/*; do printf '%s=' "$f"; cat "$f" 2>&1; done
```

```bash
printf '%s\n' '--- /sys/class/drm listing ---'
ls -la /sys/class/drm
printf '%s\n' '--- connector inventory ---'
for d in /sys/class/drm/card*-*; do
  [ -d "$d" ] || continue
  printf '\nCONNECTOR %s\n' "$(basename "$d")"
  printf 'realpath: '; readlink -f "$d"
  printf 'card: '; basename "$(dirname "$(readlink -f "$d")")"
  printf 'status: '; cat "$d/status" 2>&1
  printf 'enabled: '; cat "$d/enabled" 2>&1
  printf 'connector_id: '; cat "$d/connector_id" 2>&1
  printf 'dpms: '; cat "$d/dpms" 2>&1
  if [ -e "$d/edid" ]; then stat -c 'edid: size=%s bytes mode=%A owner=%U group=%G' "$d/edid"; else printf '%s\n' 'edid: absent'; fi
  printf '%s\n' 'modes:'
  if [ -r "$d/modes" ]; then sed -n '1,200p' "$d/modes"; else printf '%s\n' '(unreadable or absent)'; fi
done
printf '%s\n' '--- DRM device nodes ---'
ls -l /dev/dri 2>&1
printf '%s\n' '--- DRM node udev/sysfs mapping ---'
for n in /dev/dri/card* /dev/dri/renderD*; do
  [ -e "$n" ] || continue
  printf '\nNODE %s\n' "$n"
  stat -c 'mode=%A owner=%U group=%G major_minor=%t:%T' "$n"
  udevadm info -q path -n "$n" 2>&1
  udevadm info -q property -n "$n" 2>&1 | sed -n '/^DEVNAME=/p;/^DEVPATH=/p;/^ID_PATH=/p;/^ID_PATH_TAG=/p;/^ID_PCI_CLASS_FROM_DATABASE=/p;/^ID_VENDOR_ID=/p;/^ID_MODEL_ID=/p'
done
printf '%s\n' '--- drm card PCI linkage ---'
for c in /sys/class/drm/card[0-9]*; do printf '%s -> %s\n' "$(basename "$c")" "$(readlink -f "$c/device")"; done
```

```bash
printf '%s\n' '--- EDID readable byte counts ---'
for d in /sys/class/drm/card*-*; do [ -d "$d" ] || continue; printf '%s: ' "$(basename "$d")"; wc -c < "$d/edid" 2>&1; done
printf '%s\n' '--- debugfs mount ---'
findmnt -T /sys/kernel/debug -o TARGET,SOURCE,FSTYPE,OPTIONS 2>&1
printf '%s\n' '--- debugfs top and dri ---'
ls -ld /sys/kernel/debug /sys/kernel/debug/dri 2>&1
ls -la /sys/kernel/debug/dri 2>&1
printf '%s\n' '--- debugfs DRI trees (depth 3) ---'
find /sys/kernel/debug/dri -maxdepth 3 -printf '%M %u %g %s %p -> %l\n' 2>&1 | sed -n '1,1000p'
printf '%s\n' '--- override/control filenames in debugfs ---'
find /sys/kernel/debug/dri -maxdepth 6 \( -name edid_override -o -name force -o -name trigger_hotplug \) -printf '%M %u %g %s %p\n' 2>&1
printf '%s\n' '--- connector debugfs directories by expected connector name ---'
for c in DP-1 DP-2 DP-3 DP-4 DP-5 DP-6 DP-7 DP-8 HDMI-A-1 Writeback-1; do find /sys/kernel/debug/dri -maxdepth 4 -type d -name "$c" -print 2>&1; done
```

```bash
ls -l /dev/dri
findmnt -T /sys/kernel/debug -o TARGET,SOURCE,FSTYPE,OPTIONS
ls -ld /sys/kernel/debug /sys/kernel/debug/dri
ls -la /sys/kernel/debug/dri
find /sys/kernel/debug/dri -maxdepth 4 -printf '%M %u %g %s %p -> %l\n'
find /sys/kernel/debug/dri -maxdepth 7 \( -name edid_override -o -name force -o -name trigger_hotplug \) -printf '%M %u %g %s %p\n'
```

```bash
printf '%s\n' '--- session context ---'
printf 'XDG_SESSION_TYPE=%s\nWAYLAND_DISPLAY=%s\nDISPLAY=%s\nXDG_CURRENT_DESKTOP=%s\nKDE_FULL_SESSION=%s\nDBUS_SESSION_BUS_ADDRESS=%s\n' "$XDG_SESSION_TYPE" "$WAYLAND_DISPLAY" "$DISPLAY" "$XDG_CURRENT_DESKTOP" "$KDE_FULL_SESSION" "$DBUS_SESSION_BUS_ADDRESS"
printf '%s\n' '--- loginctl sessions ---'
loginctl list-sessions --no-legend 2>&1
loginctl show-session self -p Id -p Name -p User -p Type -p Class -p State -p Active -p Remote -p Desktop -p Display -p Leader 2>&1
printf '%s\n' '--- kscreen-doctor availability/version/output ---'
command -v kscreen-doctor 2>&1
kscreen-doctor --version 2>&1
kscreen-doctor -o 2>&1
printf '%s\n' '--- VAAPI and relevant tools ---'
ls -l /dev/dri 2>&1
command -v vainfo 2>&1
vainfo 2>&1
printf '%s\n' '--- Sunshine package/binaries/version/service state ---'
pacman -Q sunshine 2>&1
command -v sunshine 2>&1
sunshine --version 2>&1
systemctl --user status sunshine.service --no-pager 2>&1 | sed -n '1,120p'
systemctl status sunshine.service --no-pager 2>&1 | sed -n '1,120p'
```

```bash
sudo -n sh -c 'ls -ld /sys/kernel/debug/dri; ls -la /sys/kernel/debug/dri; find /sys/kernel/debug/dri -maxdepth 4 -printf "%M %u %g %s %p -> %l\\n"; find /sys/kernel/debug/dri -maxdepth 7 \( -name edid_override -o -name force -o -name trigger_hotplug \) -printf "%M %u %g %s %p\\n"'
```

```bash
printf '%s\n' '--- /dev/dri/by-path ---'
ls -l /dev/dri/by-path 2>&1
printf '%s\n' '--- all local Sunshine-like packages ---'
pacman -Qq 2>&1 | sed -n '/sunshine/Ip'
printf '%s\n' '--- kernel journal: DRM/amdgpu/display ---'
journalctl -b -k --no-pager 2>&1 | sed -n '/amdgpu\|\[drm\]\|drm:/Ip'
printf '%s\n' '--- dmesg fallback: DRM/amdgpu/display ---'
dmesg 2>&1 | sed -n '/amdgpu\|\[drm\]\|drm:/Ip'
```

```bash
printf '%s\n' '--- graphics package versions individually ---'
for p in mesa lib32-mesa vulkan-radeon libva-mesa-driver libva libdrm kscreen; do pacman -Q "$p" 2>&1; done
printf '%s\n' '--- DRM-related kernel config ---'
if [ -r /proc/config.gz ]; then zgrep -E '^CONFIG_(DEBUG_FS|DRM|DRM_AMDGPU|DRM_KMS_HELPER|DRM_LOAD_EDID_FIRMWARE)=' /proc/config.gz; elif [ -r "/boot/config-$(uname -r)" ]; then grep -E '^CONFIG_(DEBUG_FS|DRM|DRM_AMDGPU|DRM_KMS_HELPER|DRM_LOAD_EDID_FIRMWARE)=' "/boot/config-$(uname -r)"; else printf '%s\n' 'No readable kernel config found'; fi
printf '%s\n' '--- kscreen-doctor owning package ---'
pacman -Qo /usr/bin/kscreen-doctor 2>&1
printf '%s\n' '--- current user groups and ACLs ---'
id
getfacl -p /dev/dri/card1 /dev/dri/renderD128 2>&1
```

```bash
ls -ld notes 2>&1
rg --files notes 2>&1 | sed -n '1,80p'
```

```bash
wc -l -c notes/drm-recon.md
sed -n '1,80p' notes/drm-recon.md
printf '%s\n' '--- requested sections ---'
rg -n '^### [A-E]\.|^## [1-7]\.|^## Exact commands run' notes/drm-recon.md
printf '%s\n' '--- git status ---'
git status --short -- notes/drm-recon.md
```
