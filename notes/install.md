# Installation, migration, and recovery

This procedure targets the supported Arch Linux, AMDGPU, Plasma Wayland, and
systemd stack. Keep a physical recovery monitor and SSH available through the
first real stream and cold-boot test.

## 1. Build without privilege

```bash
git diff -- . ':(exclude)build'
make check
./scripts/headless-virtual-display-setup discover
```

`make check` compiles the C helper with warnings-as-errors and hardening flags,
validates current and legacy managed EDIDs, tests configuration and input
parsers, checks the generated sudoers rule, and verifies the systemd units. It
does not write configuration or touch DRM.

## 2. Install static files

```bash
sudo make install
```

For distribution packaging, use a staged install without root:

```bash
make PREFIX=/usr BUILD_DIR=build-package check
make PREFIX=/usr BUILD_DIR=build-package DESTDIR="$package_root" install
```

The source install places programs below `/usr/local`, support data and docs
below `/usr/local/share`, and units below `/etc/systemd`. It does not install a
topology configuration or sudoers rule, enable a service, modify Sunshine, or
mutate DRM.

## 3. Bind the installation to this machine

List candidates:

```bash
headless-virtual-display-setup discover
```

Choose an unused connector explicitly:

```bash
sudo headless-virtual-display-setup configure \
  --user "$USER" \
  --connector DP-1
```

Use `--pci-slot 0000:bb:dd.f` when more than one supported AMDGPU device exists.
Use `--sunshine-unit UNIT.service` when Sunshine's user unit is not detected
uniquely. `--dry-run` prints the intended files without writing them.

Setup performs these safety checks:

- the desktop account exists, is non-root, and is bound by name and UID;
- PCI BDF, vendor, device, driver, DRM card, and connector resolve together;
- the selected connector is disconnected, or already has a recognized managed
  EDID from this project;
- the required debugfs controls are root-owned regular files and are not
  group/world-writable;
- the generated sudoers fragment authorizes only the fixed helper operations;
- the installed root helper independently parses the new config and probes the
  same topology.

The root-owned runtime configuration is:

```text
/etc/headless-virtual-display/topology.conf
```

Do not source it as shell code. Both implementations use strict parsers that
reject unknown, duplicate, missing, malformed, or unsafe values.

### Migrating the initial machine-specific release

Install the new files over the old installation, then run `configure` for the
same user, PCI device, and connector. The setup and runtime validators accept the
legacy `VIRTUAL-POC`/`VDS-POC-0001` EDID only for safe ownership recognition.
The next successful baseline or retune replaces it with the production
`HEADLESS-VDS` identity. No remove/recreate cycle is required.

If a different configuration already exists, setup is idempotent when values
match and otherwise requires `--force`. Inspect the old and proposed bindings
carefully before using that option.

## 4. Review and enable services

Run as the configured desktop user except where `sudo` is shown:

```bash
sudo systemctl daemon-reload
systemctl --user daemon-reload
virtual-display doctor
```

`doctor` is read-only. It checks configuration ownership, account identity,
runtime dependencies, topology, sudo authorization, debugfs controls, the
Wayland session, and KWin visibility.

With the recovery display still connected:

```bash
sudo systemctl enable --now headless-virtual-display-drm.service
sudo systemctl status headless-virtual-display-drm.service --no-pager

systemctl --user enable --now headless-virtual-display-kwin.service
systemctl --user status headless-virtual-display-kwin.service --no-pager
virtual-display status
```

The system stage applies the baseline before the display manager. The user stage
enables only the configured connector in KWin, selects the generated mode, and
sets scale 1. It does not target other connectors.

## 5. Configure Sunshine

Back up the live configuration and application list first:

```bash
backup_suffix="$(date +%Y%m%d-%H%M%S)"
cp --archive ~/.config/sunshine/sunshine.conf \
  ~/.config/sunshine/sunshine.conf."$backup_suffix"
cp --archive ~/.config/sunshine/apps.json \
  ~/.config/sunshine/apps.json."$backup_suffix"
```

Use Sunshine's Web UI to merge the exact values printed by setup:

```text
capture       = kwin
encoder       = vaapi
output_name   = CONFIGURED_CONNECTOR
global prep do   = INSTALLED_PREFIX/bin/virtual-display sunshine-up
global prep undo = (empty)
```

Leave **Exclude global prep commands** disabled for streamed applications. Do
not add an undo command that removes the persistent display. Restart Sunshine
only after reviewing the saved configuration or Web UI state.

```bash
systemctl --user restart app-dev.lizardbyte.app.Sunshine.service
systemctl --user status app-dev.lizardbyte.app.Sunshine.service --no-pager
```

If Sunshine uses another unit name, substitute it in these commands and supply
that name to setup so the ordering drop-in is generated correctly.

## Unattended-login decision

A truly headless cold boot requires the configured user to enter a Plasma
Wayland session automatically. You may therefore want to enable SDDM or another
display manager's autologin. Because an autologin session does not receive a
login password, you may also need to change or remove the KWallet password if
Sunshine or related software needs credentials from the wallet.

These are security tradeoffs, not routine installation steps:

- autologin gives anyone with physical access immediate access to the desktop;
- an empty, removed, or weakened KWallet password reduces protection for stored
  credentials;
- a remotely reachable unattended session increases the impact of a Sunshine,
  desktop, or account compromise.

This project deliberately does not change autologin or KWallet. Follow the
current KDE/SDDM documentation only after assessing the machine's physical
security, disk encryption, account privileges, and network exposure.

## Normal recovery

```bash
virtual-display doctor
virtual-display status
virtual-display baseline
```

Use `baseline` first. `remove` is an administrative recovery operation and is
not part of the normal Sunshine lifecycle:

```bash
virtual-display remove
```

The configured sudoers policy authorizes only the root helper's `apply`,
`retune`, `remove`, and read-only `probe` operations. Never authorize Python, a
shell, `tee`, the checkout, or the unprivileged controller as root.

## Uninstall

While the helper and sudoers policy still exist:

1. Stop Sunshine and remove the managed connector:

   ```bash
   systemctl --user stop app-dev.lizardbyte.app.Sunshine.service
   virtual-display remove
   ```

2. Disable the two stages:

   ```bash
   systemctl --user disable --now headless-virtual-display-kwin.service
   sudo systemctl disable --now headless-virtual-display-drm.service
   ```

3. Restore the Sunshine backup and remove its generated ordering drop-in.

4. Remove the installed package, or for a `/usr/local` source install remove only
   the paths printed by `make install`, plus:

   ```text
   /etc/headless-virtual-display/topology.conf
   /etc/sudoers.d/headless-virtual-display
   /etc/systemd/user/CONFIGURED_SUNSHINE_UNIT.d/50-headless-virtual-display.conf
   ```

5. Reload both systemd managers.

If `virtual-display remove` fails, recover it before deleting the privileged
helper or sudoers rule.
