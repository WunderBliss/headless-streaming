# Production virtual-display installation and recovery

Date: 2026-08-10 (Asia/Tokyo)

Nothing in this repository installs itself. The commands below are a proposed,
review-first procedure. Do not run the root installation or change Sunshine until
the source, sudoers fragment, units, and diffs have been approved.

## Prerequisites and pre-install review

Run as `owen` from the project root:

```bash
git diff -- . ':(exclude)build'
make check
./scripts/virtual-display status
./scripts/edid.py normalize 2560 1600 120
./scripts/edid.py normalize 3840 2160 90
./scripts/edid.py normalize 5120 2880 60
/usr/bin/visudo -cf packaging/sudoers/headless-virtual-display
```

`make check` is unprivileged. It builds the C helper and baseline EDID below the
ignored `build/` directory, validates exact/fallback EDIDs with `edid-decode`,
checks Python syntax, compiles C with warnings as errors and hardening flags,
checks sudoers syntax, and verifies the systemd units. It does not touch DRM.

Inspect the proposed destinations:

```bash
sed -n '1,260p' packaging/sudoers/headless-virtual-display
sed -n '1,260p' packaging/systemd/system/headless-virtual-display-drm.service
sed -n '1,200p' packaging/systemd/user/headless-virtual-display-kwin.service
sed -n '1,160p' packaging/systemd/user/app-dev.lizardbyte.app.Sunshine.service.d/50-headless-virtual-display.conf
sed -n '1,120p' packaging/sunshine/sunshine.conf
```

## Root-owned file installation

After explicit approval, the only root installation command is:

```bash
sudo make install
```

That target requires the artifacts produced by the immediately preceding
unprivileged `make check`, verifies sudoers syntax again, and performs only fixed
file installation with root ownership. It does not execute the repository's
Python generator as root. It does not enable/start a unit, restart Sunshine,
change the live Sunshine configuration, reboot, or touch a DRM control.

Installed paths:

```text
/usr/local/bin/virtual-display
/usr/local/lib/headless-virtual-display/edid.py
/usr/local/libexec/headless-virtual-display-root
/usr/local/share/headless-virtual-display/baseline-1920x1080-60.edid
/etc/sudoers.d/headless-virtual-display
/etc/systemd/system/headless-virtual-display-drm.service
/etc/systemd/system/display-manager.service.d/50-headless-virtual-display.conf
/etc/systemd/user/headless-virtual-display-kwin.service
/etc/systemd/user/app-dev.lizardbyte.app.Sunshine.service.d/50-headless-virtual-display.conf
/usr/local/share/doc/headless-virtual-display/production-design.md
/usr/local/share/doc/headless-virtual-display/install.md
/usr/local/share/doc/headless-virtual-display/test-plan.md
```

Verify the installed privilege boundary before enabling anything:

```bash
sudo /usr/bin/visudo -cf /etc/sudoers.d/headless-virtual-display
sudo stat -c '%A %a %U:%G %n' \
  /usr/local/libexec/headless-virtual-display-root \
  /usr/local/bin/virtual-display \
  /usr/local/lib/headless-virtual-display/edid.py \
  /etc/sudoers.d/headless-virtual-display
sudo -l -U owen
```

Expected modes/owners are root:root `0755` for executables, `0644` for the EDID
module, and `0440` for sudoers. `sudo -l` must list only the fixed root helper's
three exact operations for this feature. Never add NOPASSWD rules for the project
script, installed unprivileged controller, Python, a shell, `tee`, Sunshine, or a
debugfs path.

## Enable the two-stage baseline

Reload both managers:

```bash
sudo systemctl daemon-reload
systemctl --user daemon-reload
```

With the HDMI recovery display still connected, enable and start the system DRM
stage deliberately:

```bash
sudo systemctl enable --now headless-virtual-display-drm.service
sudo systemctl status headless-virtual-display-drm.service --no-pager
```

This is the first live privileged DRM mutation. It applies the fixed baseline but
does not configure KWin or touch HDMI-A-1. Do not reboot.

Then enable/start the Plasma stage as `owen`:

```bash
systemctl --user enable --now headless-virtual-display-kwin.service
systemctl --user status headless-virtual-display-kwin.service --no-pager
/usr/local/bin/virtual-display status
```

Expected state is managed DP-1 connected, generated mode approximately
`1920x1080@59.96`, KWin DP-1 enabled/current at that mode, scale 1, and profile
`baseline`. HDMI-A-1 retains its prior mode/scale/priority.

The display-manager drop-in pulls and orders the root stage before SDDM on future
boots. The Sunshine drop-in requires the successful KWin stage before Sunshine.
No reboot is needed for the initial manual test.

## Sunshine configuration (proposed, not applied by installation)

Back up the current files first:

```bash
backup_suffix="$(date +%Y%m%d-%H%M%S)"
cp --archive ~/.config/sunshine/sunshine.conf \
  ~/.config/sunshine/sunshine.conf."$backup_suffix"
cp --archive ~/.config/sunshine/apps.json \
  ~/.config/sunshine/apps.json."$backup_suffix"
```

Use Sunshine's Web UI to merge these global settings, which avoids overwriting
unrelated configuration:

```text
capture       = kwin
encoder       = vaapi
output_name   = DP-1
global prep do   = /usr/local/bin/virtual-display sunshine-up
global prep undo = (empty)
```

For every application intended to use DP-1, leave "Exclude global prep
commands" disabled. An application that explicitly excludes global prep is not
safe with this capture configuration.

The equivalent proposed configuration is
`packaging/sunshine/sunshine.conf`. If the live file is still empty and has been
backed up, it may be installed as `owen` with:

```bash
install -m 0600 packaging/sunshine/sunshine.conf \
  ~/.config/sunshine/sunshine.conf
```

Do not add an undo command that removes or resets DP-1. The fixed production path
is used instead of the mutable checkout. After reviewing the saved Web UI state
or file diff, manually restart Sunshine:

```bash
systemctl --user restart app-dev.lizardbyte.app.Sunshine.service
systemctl --user status app-dev.lizardbyte.app.Sunshine.service --no-pager
journalctl --user -u app-dev.lizardbyte.app.Sunshine.service -b -n 200 --no-pager
```

Do not start Moonlight automatically. The first connection procedure is in
`notes/test-plan.md`.

## Normal operation and recovery

Show authoritative and transient state:

```bash
/usr/local/bin/virtual-display status
```

Restore/create the baseline and verify DRM/KWin:

```bash
/usr/local/bin/virtual-display baseline
```

Administratively remove only the recognized synthetic DP-1:

```bash
/usr/local/bin/virtual-display remove
```

Removal is never part of normal Sunshine lifecycle. To recreate it after an
administrative removal:

```bash
/usr/local/bin/virtual-display baseline
```

If a stream launch fails, inspect in this order:

```bash
/usr/local/bin/virtual-display status
journalctl --user -u app-dev.lizardbyte.app.Sunshine.service -b -n 300 --no-pager
journalctl --user -u headless-virtual-display-kwin.service -b --no-pager
sudo journalctl -u headless-virtual-display-drm.service -b --no-pager
```

Look for requested/effective/fallback lines, a nonzero prep exit, sudo denial,
managed EDID rejection, KWin mode/scale timeout, and the required KWin capture
line. SSH remains the recovery path. Do not experiment by changing HDMI-A-1.

## Uninstall

Perform uninstall from the active Plasma/SSH session while the installed helper
and sudo rule still exist.

1. Stop Sunshine and explicitly remove the recognized synthetic connector:

   ```bash
   systemctl --user stop app-dev.lizardbyte.app.Sunshine.service
   /usr/local/bin/virtual-display remove
   ```

2. Disable both baseline stages:

   ```bash
   systemctl --user disable --now headless-virtual-display-kwin.service
   sudo systemctl disable --now headless-virtual-display-drm.service
   ```

3. Restore the backed-up Sunshine configuration or remove the four proposed keys
   and the global prep row through the Web UI. Do not delete credentials/state.

4. Remove only these installed files:

   ```bash
   sudo rm -f \
     /etc/systemd/user/app-dev.lizardbyte.app.Sunshine.service.d/50-headless-virtual-display.conf \
     /etc/systemd/user/headless-virtual-display-kwin.service \
     /etc/systemd/system/display-manager.service.d/50-headless-virtual-display.conf \
     /etc/systemd/system/headless-virtual-display-drm.service \
     /etc/sudoers.d/headless-virtual-display \
     /usr/local/share/headless-virtual-display/baseline-1920x1080-60.edid \
     /usr/local/share/doc/headless-virtual-display/production-design.md \
     /usr/local/share/doc/headless-virtual-display/install.md \
     /usr/local/share/doc/headless-virtual-display/test-plan.md \
     /usr/local/lib/headless-virtual-display/edid.py \
     /usr/local/libexec/headless-virtual-display-root \
     /usr/local/bin/virtual-display
   sudo rmdir --ignore-fail-on-non-empty \
     /usr/local/share/headless-virtual-display \
     /usr/local/share/doc/headless-virtual-display \
     /usr/local/lib/headless-virtual-display
   ```

5. Reload managers:

   ```bash
   sudo systemctl daemon-reload
   systemctl --user daemon-reload
   ```

If `remove` failed, stop and recover it before deleting the privileged helper or
sudoers rule. No reboot is part of uninstall.
