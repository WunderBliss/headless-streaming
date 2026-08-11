# Headless Sunshine streaming on AMD Strix Halo

This project creates a persistent virtual monitor on an otherwise disconnected
AMDGPU `DP-1` connector, allowing a KDE Plasma Wayland desktop to boot and stream
through [Sunshine](https://github.com/LizardByte/Sunshine) with no physical
display attached.

Unlike a fixed dummy-plug EDID, the virtual display is retuned for each Moonlight
client. Sunshine passes the requested width, height, and frame rate to a prep
command; the command generates a matching EDID, applies it without disconnecting
the display, configures KWin, and returns only when the requested output is ready
to capture.

This is working on the machine it was built for, including a cold boot with no
HDMI display attached, Plasma autologin, dynamic `2560x1600` streaming to a
tablet, VAAPI encoding, audio, and touch input.

> [!IMPORTANT]
> This is currently a hardware- and user-specific implementation, not a generic
> virtual-display installer. It deliberately accepts only AMD PCI device
> `1002:1586` (Strix Halo), connector `DP-1`, the `amdgpu` driver, and desktop
> user `owen`. Read the compatibility and installation sections before running
> anything as root. You will need to adjust for your own usage.

## What it does

- Creates synthetic `DP-1` at a conservative `1920x1080@60` before the display
  manager starts.
- Keeps the connector alive independently of Sunshine and Moonlight sessions.
- Reads `SUNSHINE_CLIENT_WIDTH`, `SUNSHINE_CLIENT_HEIGHT`, and
  `SUNSHINE_CLIENT_FPS` when an application launches.
- Uses the exact requested mode whenever it fits the current EDID generator.
- Falls back to a validated, aspect-preserving mode when it does not.
- Enables only `DP-1` through KScreen, selects the effective mode, and enforces
  scale 1.
- Fails closed if DRM, the synthetic EDID, or KWin state cannot be verified.
- Leaves physical `HDMI-A-1` configuration alone.

The persistent lifecycle is:

```text
boot
  -> root system service injects the baseline EDID into DP-1
  -> display manager and Plasma start
  -> user service verifies DP-1 in KWin at scale 1
  -> Sunshine starts with DP-1 already available for its capture probe

Moonlight launch
  -> Sunshine prep requests WIDTH x HEIGHT @ FPS
  -> existing DP-1 is retuned in place
  -> DRM and KWin state are verified
  -> Sunshine captures DP-1

disconnect / quit
  -> DP-1 remains connected at its last successful mode
```

## Compatibility

The implementation was developed and tested with:

- AMD Strix Halo graphics, PCI ID `1002:1586`, using `amdgpu`
- an unused/disconnected DRM connector named `DP-1`
- Arch Linux
- KDE Plasma on Wayland with KWin and KScreen
- Sunshine using KWin capture and VAAPI encoding
- systemd system and user services

The privileged helper independently verifies that complete identity and refuses
ambiguous or unexpected hardware. Supporting another GPU, connector, desktop
user, or display stack requires a deliberate code review and adaptation; simply
loosening the checks is not recommended.

The normal controller is also currently pinned to user `owen`. Before installing
for another account, update `EXPECTED_DESKTOP_USER` in
[`scripts/virtual-display`](scripts/virtual-display) and the username in
[`packaging/sudoers/headless-virtual-display`](packaging/sudoers/headless-virtual-display),
then review all resulting changes.

## Resolution behavior

Exact requests are attempted first. `3840x2160` is a fallback boundary, not a
global resolution cap.

| Client request | Effective mode | Result |
| --- | --- | --- |
| `2560x1600@120` | `2560x1600@120` | exact |
| `1920x1080@144` | `1920x1080@144` | exact |
| `1280x800@90` | `1280x800@90` | exact |
| `3840x2160@90` | `3840x2160@60` | refresh fallback |
| `5120x2880@60` | `3840x2160@60` | aspect-preserving size fallback |

Fallbacks never upscale the client request merely to fill the bounding box.
They preserve aspect ratio, fit within `3840x2160`, cap refresh at 60 Hz, and
must pass both internal validation and `edid-decode`. If progressively smaller
candidates all fail, the final emergency mode is `1920x1080@60`, with any aspect
change reported explicitly rather than silently hidden.

Current EDID limitations include a 4095-pixel DTD dimension limit, width divisible
by 8, a 655.35 MHz pixel-clock limit, and incomplete representation of arbitrary
high-refresh CVT timings. There is currently no CTA audio, HDR, VRR, DisplayID,
or extension-block support.

## Components

- [`scripts/virtual-display`](scripts/virtual-display) — unprivileged controller,
  KWin integration, locking, normalization, verification, and status.
- [`scripts/edid.py`](scripts/edid.py) — EDID generation, validation, and fallback
  selection.
- [`src/headless-virtual-display-root.c`](src/headless-virtual-display-root.c) —
  narrowly scoped privileged debugfs helper.
- [`packaging/systemd`](packaging/systemd) — early DRM and graphical-session
  ordering.
- [`packaging/sudoers/headless-virtual-display`](packaging/sudoers/headless-virtual-display)
  — passwordless access to only the root helper's three fixed operations.

The root helper accepts only `apply`, `retune`, and `remove`. EDID data is passed
through standard input; it does not accept paths or commands, execute a shell,
or import code from the repository. It validates the GPU, driver, connector,
debugfs endpoints, EDID structure, checksums, and synthetic identity before
writing anything.

## Build and installation

Runtime/build requirements include Python 3, a C compiler, GNU Make,
`edid-decode`, `kscreen-doctor`, `sudo`, systemd, debugfs, Plasma Wayland, and a
working Sunshine installation.

First review the implementation and run the unprivileged checks:

```bash
git clone https://github.com/WunderBliss/headless-streaming.git
cd headless-streaming
make check
```

`make check` compiles and tests the helper, validates generated EDIDs, checks the
sudoers fragment, and verifies the systemd units. It does not touch DRM or install
anything.

After adapting the hard-coded desktop user if necessary and reviewing the files,
install the fixed artifacts:

```bash
sudo make install
```

Installation alone does **not** enable services, modify the live Sunshine
configuration, inject an EDID, restart Sunshine, configure display-manager
autologin, or reboot. Follow the review-first procedure in
[`notes/install.md`](notes/install.md) to verify ownership and sudo scope, enable
the two systemd stages, and merge the Sunshine settings.

The required Sunshine settings are:

```ini
capture = kwin
encoder = vaapi
output_name = DP-1
global_prep_cmd = [{"do":"/usr/local/bin/virtual-display sunshine-up","undo":""}]
```

Leave application-level **Exclude global prep commands** disabled. Do not add an
undo command that removes the display.

For a fully unattended cold boot, the selected desktop user must enter a Plasma
Wayland graphical session automatically; this repository intentionally does not
configure SDDM autologin or KWallet policy.

## Usage

Run the controller as the normal Plasma user, never with `sudo`:

```bash
# Inspect DRM, EDID, generated mode, KWin mode/scale, and transient state
virtual-display status

# Create or restore the conservative idle mode
virtual-display baseline

# Apply a manual exact/fallback request
virtual-display retune 2560 1600 120

# Administrative recovery only; not part of the Sunshine lifecycle
virtual-display remove
```

`sunshine-up` is intended for Sunshine's prep hook and strictly reads its request
from the three `SUNSHINE_CLIENT_*` environment variables.

## Verification and recovery

The complete staged validation procedure is in
[`notes/test-plan.md`](notes/test-plan.md). During the first real stream, verify
that Sunshine's journal contains:

```text
[kwingrab] Screencasting output name DP-1
```

This matters because the tested Sunshine KWin capture implementation can fall
back to its first output if the configured name is missing.

Useful diagnostics are:

```bash
virtual-display status
journalctl --user -u app-dev.lizardbyte.app.Sunshine.service -b --no-pager
journalctl --user -u headless-virtual-display-kwin.service -b --no-pager
sudo journalctl -u headless-virtual-display-drm.service -b --no-pager
```

Use `virtual-display baseline` as the first recovery action. Explicit removal and
the full uninstall sequence are documented in [`notes/install.md`](notes/install.md).
SSH access is strongly recommended while testing headless boot.

## Documentation

- [`notes/production-design.md`](notes/production-design.md) — architecture,
  trust boundaries, normalization algorithm, and known risks
- [`notes/install.md`](notes/install.md) — reviewed installation, Sunshine setup,
  recovery, and uninstall
- [`notes/test-plan.md`](notes/test-plan.md) — manual validation from baseline
  through cold headless boot
- [`notes/drm-recon.md`](notes/drm-recon.md) — initial AMDGPU/DRM reconnaissance
- [`notes/edid-poc.md`](notes/edid-poc.md) and
  [`notes/edid-retune-poc.md`](notes/edid-retune-poc.md) — proof-of-concept history
- [`notes/sunshine-recon.md`](notes/sunshine-recon.md) — Sunshine capture, encoder,
  output targeting, and prep ordering research

## License

[MIT](LICENSE)
