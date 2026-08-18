# Changelog

All notable changes are documented here.

## [Unreleased]

## [0.2.0] - unreleased

### Added

- Root-owned, versioned topology configuration for the desktop user, PCI GPU,
  driver, and connector.
- Discovery and guarded setup utility with dry-run support, exact-user sudoers,
  Sunshine service ordering, and post-setup diagnostics.
- Read-only privileged `probe` and unprivileged `virtual-display doctor`.
- `/usr`/`/usr/local` and staged `DESTDIR` installation support.
- Arch `-git` packaging and GitHub Actions validation.
- Production EDID identity with legacy initial-release migration support.

### Changed

- Removed runtime source-code dependence on one username, Strix Halo device ID,
  and `DP-1` connector.
- Sunshine integration is generated for the selected connector and installed
  service instead of being fixed to one host.

[Unreleased]: https://github.com/WunderBliss/headless-streaming/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/WunderBliss/headless-streaming/releases/tag/v0.2.0
