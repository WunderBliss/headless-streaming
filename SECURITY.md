# Security policy

## Supported versions

Security fixes are currently developed on the latest release branch. The
initial machine-specific release is unsupported after v0.2 becomes available.

## Reporting a vulnerability

Do not open a public issue for a suspected privilege-boundary bypass, arbitrary
debugfs access, unsafe sudo authorization, configuration race, or managed-EDID
identity bypass. Use GitHub's private vulnerability reporting feature for this
repository and include the affected commit, platform, reproduction steps, and
the least destructive evidence available.

Do not test a report on a connector carrying a physical display or on a machine
without SSH/console recovery. Never include Sunshine credentials, private keys,
wallet contents, or unrelated journal data in a report.

## Security model

Only the installed C helper crosses the root boundary. It accepts four fixed
verbs, reads topology from one root-owned fixed path, and never executes another
program. The Python controller and Sunshine must remain unprivileged. Any change
that authorizes Python, a shell, `tee`, an arbitrary path, or a mutable checkout
as passwordless root is outside the supported security model.
