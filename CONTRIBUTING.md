# Contributing

Contributions are welcome for the currently supported AMDGPU, KDE Plasma
Wayland, systemd, and Sunshine stack. Compatibility claims for another GPU,
driver, compositor, or distribution should include discovery output, package
versions, the manual test-plan results, and recovery details.

Before submitting a change:

```bash
make check
git diff --check
```

Changes to configuration parsing, the privileged helper, sudoers generation,
debugfs paths, EDID ownership validation, or rollback behavior need corresponding
negative tests. Preserve these rules:

- no caller-controlled privileged path or executable;
- no shell or subprocess from the root helper;
- no mutation of a connected unrecognized display;
- no KScreen setter outside the configured connector;
- no silent connector selection during setup;
- no automatic autologin or KWallet weakening.

Hardware tests must use a recovery output and SSH/console access. Sanitize logs
before attaching them to an issue or pull request.
