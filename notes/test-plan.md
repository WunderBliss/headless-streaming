# v0.2 manual release test plan

Keep a physical recovery output attached through the first streaming test and
keep SSH available. Never run `virtual-display` with sudo. Stop on an
unrecognized EDID, unknown connector state, rollback failure, or an unexpected
change to another output.

Record the configured connector from:

```bash
connector="$(sed -n 's/^connector=//p' /etc/headless-virtual-display/topology.conf)"
virtual-display doctor
virtual-display status
```

## Phase 1: clean installation and configuration

1. Build and test from a clean checkout:

   ```bash
   make check
   ```

2. Exercise a staged package layout:

   ```bash
   package_root="$(mktemp -d)"
   make PREFIX=/usr BUILD_DIR=build-package check
   make PREFIX=/usr BUILD_DIR=build-package DESTDIR="$package_root" install
   test -x "$package_root/usr/bin/virtual-display"
   test ! -e "$package_root/etc/sudoers.d/headless-virtual-display"
   ```

3. Install and run setup first with `--dry-run`, then for real. Require explicit
   connector selection, a root-owned configuration, a `visudo`-valid exact-user
   rule, and a successful root-helper probe.

4. Verify setup's final output mentions optional display-manager autologin and
   KWallet password changes, clearly states both reduce security, and confirms
   neither was changed automatically.

## Phase 2: baseline and exact modes

Enable both services as documented, then require:

```bash
virtual-display baseline
virtual-display status
```

- configured connector connected with the full managed identity;
- generated mode approximately `1920x1080@59.96`;
- KWin output connected and enabled at scale 1;
- every non-configured output unchanged.

Test exact transitions:

```bash
virtual-display retune 2560 1600 120
virtual-display status
virtual-display retune 1280 800 90
virtual-display status
```

Require exact modes near 119.96 and 89.89 Hz respectively, scale 1, managed
identity, and no change to another output.

## Phase 3: fallback and no-partial-state behavior

```bash
virtual-display retune 3840 2160 90
virtual-display status
```

Require explicit exact-mode rejection and effective `3840x2160@60`.

```bash
virtual-display retune 5120 2880 60
virtual-display status
```

Require width-limit rejection and aspect-exact `3840x2160@60` fallback.

Use the card and connector reported by `virtual-display status` to hash the
current EDID. Submit malformed Sunshine and CLI inputs, then prove the hash did
not change:

```bash
env SUNSHINE_CLIENT_WIDTH='3840x2160' \
    SUNSHINE_CLIENT_HEIGHT=2160 \
    SUNSHINE_CLIENT_FPS=60 \
    virtual-display sunshine-up

virtual-display retune 0 2160 60
```

Both commands must fail before a privileged mutation. Restore baseline.

## Phase 4: Sunshine with recovery display attached

1. Confirm the live Sunshine configuration names the configured connector and
   uses the installed `virtual-display sunshine-up` prep command with empty undo.
2. Confirm its application does not exclude global prep commands.
3. Restart the configured Sunshine user unit and note the journal time.
4. Launch a Moonlight client at a known native resolution/FPS.
5. Require:

   - prep logs requested and effective modes;
   - DRM and KWin verification succeeds;
   - video, audio, and applicable input work;
   - the stream shows the configured virtual desktop;
   - Sunshine logs `[kwingrab] Screencasting output name CONFIGURED_CONNECTOR`.

Disconnect and resume, then quit the application. The virtual connector must
remain at its last successful mode. Restore baseline manually.

## Phase 5: migration

On an initial-release installation with the legacy managed EDID active:

1. install v0.2 without first removing the connector;
2. configure the same user, PCI device, and connector;
3. require setup/probe to accept the complete legacy identity;
4. run `baseline` and require the new `HEADLESS-VDS` identity;
5. repeat one real stream and rollback test.

An unknown connected EDID must remain rejected.

## Phase 6: cold boot, suspend, and uninstall

Only after earlier phases pass:

1. Confirm SSH recovery.
2. Cold boot with every physical display disconnected.
3. Require root baseline before the display manager, configured Plasma session,
   KWin baseline before Sunshine, and a successful stream.
4. Suspend/resume and repeat status plus streaming verification.
5. Follow the uninstall sequence, removing the managed connector before helper
   and sudoers removal.
6. Reinstall from the package and repeat `doctor` plus baseline.

Record kernel, Mesa, Plasma, KScreen, Sunshine, GPU, requested/effective modes,
codec, visible blanking, rollback results, and journals for every release test.
