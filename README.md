# Headless virtual display for Sunshine

Headless Virtual Display creates a persistent synthetic monitor on a supported
AMDGPU connector so KDE Plasma Wayland can boot and Sunshine can stream without a
physical display. It retunes that monitor to each Moonlight client's requested
width, height, and frame rate while keeping the connector present for Sunshine's
startup probe.

Version 0.2 removes the original machine-specific source edits. Installation is
bound through one root-owned configuration to an explicit desktop user, PCI GPU,
driver, and connector. The unprivileged controller and privileged helper verify
that binding independently on every operation.

> [!IMPORTANT]
> The supported stack is currently Arch Linux, systemd, KDE Plasma 6 Wayland,
> KWin/KScreen, Sunshine KWin capture, and an AMDGPU Display Core device exposing
> `edid_override`, `force`, and `trigger_hotplug` debugfs controls. AMD Strix Halo
> `1002:1586` is the tested platform. Setup must pass on other AMDGPU hardware
> before it should be considered compatible. Intel, NVIDIA, other compositors,
> and other distributions are not yet supported.

## How it works

```text
boot
  -> root system service applies a conservative 1920x1080@60 EDID
  -> display manager and the configured Plasma session start
  -> user service enables the configured connector in KWin at scale 1
  -> Sunshine starts only after that output is ready

Moonlight launch
  -> Sunshine supplies requested width, height, and FPS
  -> virtual-display retunes the existing connector in place
  -> DRM, EDID, KWin mode, and scale are verified
  -> Sunshine captures the explicitly configured output
```

The privileged helper accepts only `apply`, `retune`, `remove`, and the read-only
`probe`. It does not execute a shell, accept paths or topology on the command
line, import Python, or trust environment variables. Connected physical or
otherwise unrecognized displays are rejected.

## Requirements

Runtime requirements on Arch are:

- `python`
- `kwin` and `libkscreen`
- `sudo` and `systemd`
- `v4l-utils` for `edid-decode`
- Sunshine for Moonlight streaming
- a kernel with debugfs and the required AMDGPU connector controls

Builds additionally require the normal `base-devel` toolchain.

## Build and install from source

The checks are unprivileged and do not touch DRM:

```bash
git clone https://github.com/WunderBliss/headless-streaming.git
cd headless-streaming
make check
sudo make install
```

Installation copies root-owned programs, support modules, the baseline EDID, and
systemd units. It does not choose hardware, write sudoers, enable services,
change Sunshine, or mutate DRM.

Discover the available AMDGPU topology:

```bash
headless-virtual-display-setup discover
```

Then configure an explicit unused connector. With multiple GPUs, also supply
`--pci-slot`:

```bash
sudo headless-virtual-display-setup configure \
  --user "$USER" \
  --connector DP-1
```

Interactive setup can prompt for the connector, but it never silently selects
one. A connected connector is accepted only when it already exposes this
project's managed EDID, which permits safe upgrades from the initial release.

Setup writes:

- `/etc/headless-virtual-display/topology.conf`
- `/etc/sudoers.d/headless-virtual-display`
- a Sunshine user-unit drop-in when its unit can be identified unambiguously

It validates the configuration, sudoers rule, complete PCI/DRM binding, and
debugfs controls. It still does not enable or start a service.

Run the reported next steps, beginning with the read-only diagnostic:

```bash
sudo systemctl daemon-reload
systemctl --user daemon-reload
virtual-display doctor
sudo systemctl enable --now headless-virtual-display-drm.service
systemctl --user enable --now headless-virtual-display-kwin.service
virtual-display status
```

The complete reviewed procedure, including migration and recovery, is in
[`notes/install.md`](notes/install.md).

## Sunshine configuration

Back up the Sunshine configuration, then merge the values printed by setup:

```ini
capture = kwin
encoder = vaapi
output_name = CONFIGURED_CONNECTOR
global_prep_cmd = [{"do":"/usr/local/bin/virtual-display sunshine-up","undo":""}]
```

Use `/usr/bin/virtual-display` instead when installed as an Arch package. Leave
application-level **Exclude global prep commands** disabled. Do not configure an
undo command that removes the persistent output.

For an unattended cold boot, the configured user must enter a Plasma Wayland
session without manual input. You may therefore choose display-manager
autologin, and may need to change or remove the KWallet password so the wallet
can unlock in that session. Both weaken security: autologin grants anyone with
physical access immediate desktop access, while an empty or weakened wallet
password reduces protection for stored credentials. Setup deliberately changes
neither setting; enable them only after assessing those risks.

## Usage

Run the controller as the configured Plasma user, never with `sudo`:

```bash
virtual-display doctor
virtual-display status
virtual-display baseline
virtual-display retune 2560 1600 120
virtual-display remove       # administrative recovery only
```

`sunshine-up` is for Sunshine's prep hook and reads only
`SUNSHINE_CLIENT_WIDTH`, `SUNSHINE_CLIENT_HEIGHT`, and `SUNSHINE_CLIENT_FPS`.

Exact modes are attempted first. Unsupported modes fall back without upscaling,
preserving aspect ratio within a `3840x2160@60` boundary when possible. The
emergency mode is `1920x1080@60`. Current base-EDID limitations include a
4095-pixel detailed-timing dimension limit, a 655.35 MHz clock limit, width
divisible by eight, and no HDR, VRR, CTA, or DisplayID extensions.

## Arch package

[`packaging/arch/PKGBUILD`](packaging/arch/PKGBUILD) builds the rolling
`headless-virtual-display-git` package. A tagged stable package can be produced
from it after the v0.2 release tag is cut.

## Verification and recovery

During a real stream, Sunshine must log the configured connector, for example:

```text
[kwingrab] Screencasting output name DP-1
```

Useful diagnostics are:

```bash
virtual-display doctor
virtual-display status
journalctl --user -u headless-virtual-display-kwin.service -b --no-pager
sudo journalctl -u headless-virtual-display-drm.service -b --no-pager
```

Use `virtual-display baseline` as the first recovery action. Keep SSH available
when validating the first headless boot.

## Documentation

- [`notes/production-design.md`](notes/production-design.md) — trust boundaries
  and runtime design
- [`notes/install.md`](notes/install.md) — installation, migration, recovery, and
  uninstall
- [`notes/test-plan.md`](notes/test-plan.md) — manual release validation
- [`SECURITY.md`](SECURITY.md) — security policy and safe reporting
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development workflow
- the remaining files below `notes/` document the original host reconnaissance
  and proof-of-concept history

## License

[MIT](LICENSE)
