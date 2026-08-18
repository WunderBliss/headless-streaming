# Production design and trust boundaries

## Outcome

A configured, unused AMDGPU connector remains synthetically connected from boot
through Sunshine startup and streaming. Boot establishes `1920x1080@60`; a
Moonlight launch retunes the existing connector to an exact or documented
fallback mode. Disconnect, application exit, and Sunshine failure leave the last
successful mode present. `baseline` is the reset operation and `remove` is
explicit administration.

## Machine binding

Setup writes `/etc/headless-virtual-display/topology.conf` with exactly:

```text
schema_version
desktop_user
desktop_uid
pci_slot
pci_vendor
pci_device
driver
connector
```

The file is root-owned and not group/world-writable. Unknown, duplicate, missing,
non-ASCII, overlong, or malformed values are rejected. The file is opened with
`O_NOFOLLOW` and checked before and after opening on the privileged side.

Topology is configuration rather than caller input. The privileged helper still
accepts no GPU, connector, path, username, or executable through arguments,
stdin, or environment variables. An administrator with root access may retarget
the installation by deliberately replacing the configuration; an ordinary
authorized desktop user may not.

## Unprivileged controller

`virtual-display` runs only as the configured username and UID. It:

- parses manual or Sunshine mode input strictly;
- verifies the configured PCI identity, driver, DRM card, and connector;
- generates and validates the EDID internally and with `edid-decode`;
- calls only the installed root helper through `sudo -n`;
- resolves KWin output and mode IDs from current KScreen JSON by the configured
  connector name;
- constructs setters only below `output.CONFIGURED_CONNECTOR.*`;
- verifies DRM status, byte-identical EDID, DRM mode, KWin mode, enabled state,
  and scale before success;
- serializes operations and stores diagnostic state below `/run/user/<uid>`.

The installed support modules are root-owned and non-writable by the desktop
user. Development execution loads only adjacent checkout modules and still calls
the fixed installed root helper.

## Privileged helper

`headless-virtual-display-root` is the complete privilege boundary. Its command
language is:

```text
apply    # exactly one 128-byte managed EDID on stdin
retune   # exactly one 128-byte managed EDID on stdin
remove   # no stdin payload
probe    # read-only topology and endpoint validation
```

It does not run a shell, execute subprocesses, import Python, use a caller path,
or read the checkout. It independently validates:

- root execution and the root-owned fixed configuration;
- configured BDF, vendor, device, driver, unique DRM card, and connector;
- connector containment below the configured PCI device;
- debugfs endpoints below the configured BDF and connector;
- root ownership, regular-file type, non-writable metadata, `O_NOFOLLOW`, and
  stable device/inode for opened controls;
- EDID header, size, checksum, EDID 1.4 flags, detailed timing, refresh bounds,
  physical dimensions, and full managed identity.

Current generated EDIDs use `HEADLESS-VDS` / `HVD-00000001`. The validator also
recognizes the initial release's complete `VIRTUAL-POC` / `VDS-POC-0001`
identity so an existing connector can be upgraded in place. No partial or
manufacturer/product-only legacy match is accepted.

If a connector is already connected, every mutating operation first requires a
managed EDID. A physical or otherwise unknown connected connector is fail-closed.
Failed initial apply removes the partial override; failed retune restores the
complete prior EDID. A root-owned global lock serializes privileged operations.

The generated sudoers rule authorizes one configured desktop username for the
four exact argv forms. No passwordless Python, shell, `tee`, debugfs pathname, or
unprivileged controller is authorized.

## Ordering

```text
headless-virtual-display-drm.service
  -> fixed baseline EDID through root helper
  -> display-manager.service
  -> configured Plasma graphical session
  -> headless-virtual-display-kwin.service
  -> configured Sunshine user service
```

The system unit mutates DRM only and never accesses a user bus. The user unit
waits for Plasma/KWin, runs `baseline`, and verifies KWin. Setup creates a
Sunshine drop-in for the detected or explicitly supplied unit name, making the
KWin stage required and ordered before Sunshine.

No fixed readiness sleep is introduced. DRM and KWin convergence use bounded
polling. A failed prep exits nonzero so Sunshine aborts launch.

## Mode policy

1. Attempt the exact requested width, height, and refresh.
2. If it cannot be represented, retain and report the rejection reason.
3. Clamp fallback refresh to `24..60` Hz.
4. Bound fallback size by the request and `3840x2160`, never upscaling merely to
   fill the box.
5. Search largest-to-smallest width multiples of eight while preserving aspect
   ratio within 0.5%.
6. Validate every candidate internally and through `edid-decode`.
7. If no candidate works, use `1920x1080@60` and report the aspect change
   prominently.

The base EDID currently carries one preferred DTD. Its limits include 4095-pixel
active dimensions, 655.35 MHz pixel clock, width divisible by eight, no
extensions, and incomplete arbitrary high-refresh reduced blanking. CTA audio,
HDR, VRR, and DisplayID are not implemented.

## Known operational risks

- AMDGPU hotplug rediscovery may briefly blank or re-enumerate the output.
- Setup is tested on Strix Halo; other AMDGPU devices must pass the complete
  preflight and manual stream test.
- KWin and Sunshine unit/protocol behavior can change between releases.
- Sunshine may fall back when an output name is absent; a real stream is accepted
  only after its log names the configured connector.
- Encode capability is not yet part of EDID normalization; high modes require
  live codec/latency validation.
- Autologin and weakening or removing a KWallet password may be useful for
  unattended boot but materially reduce physical-access and credential security.
