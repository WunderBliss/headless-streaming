PREFIX ?= /usr/local
DESTDIR ?=
SYSCONFDIR ?= /etc
BUILD_DIR ?= build
CC ?= cc
CPPFLAGS ?=
CFLAGS ?= -O2

BINDIR := $(PREFIX)/bin
LIBDIR := $(PREFIX)/lib/headless-virtual-display
LIBEXECDIR := $(PREFIX)/libexec
DATADIR := $(PREFIX)/share/headless-virtual-display
DOCDIR := $(PREFIX)/share/doc/headless-virtual-display
SYSTEMD_SYSTEM_DIR ?= $(SYSCONFDIR)/systemd/system
SYSTEMD_USER_DIR ?= $(SYSCONFDIR)/systemd/user
CONFIG_PATH := $(SYSCONFDIR)/headless-virtual-display/topology.conf

HARDENING_CFLAGS := -std=c17 -Wall -Wextra -Wpedantic -Werror -D_FORTIFY_SOURCE=3 -fstack-protector-strong -fPIE
HARDENING_LDFLAGS := -pie -Wl,-z,relro,-z,now
CONFIG_CPPFLAG := -DCONFIG_PATH='"$(CONFIG_PATH)"'

ROOT_HELPER := $(BUILD_DIR)/headless-virtual-display-root
ROOT_VALIDATOR_TEST := $(BUILD_DIR)/root-helper-validator-test
ROOT_CONFIG_TEST := $(BUILD_DIR)/root-helper-config-test
BASELINE_EDID := $(BUILD_DIR)/baseline-1920x1080-60.edid
GENERATED_CONFIG_MODULE := $(BUILD_DIR)/config.py
GENERATED_DRM_UNIT := $(BUILD_DIR)/headless-virtual-display-drm.service
GENERATED_KWIN_UNIT := $(BUILD_DIR)/headless-virtual-display-kwin.service
GENERATED_SUDOERS := $(BUILD_DIR)/headless-virtual-display.sudoers
CHECK_STAMP := $(BUILD_DIR)/check.stamp

.PHONY: all check install clean

all: $(ROOT_HELPER) $(BASELINE_EDID) $(GENERATED_CONFIG_MODULE) $(GENERATED_DRM_UNIT) $(GENERATED_KWIN_UNIT)

$(BUILD_DIR):
	mkdir -p "$@"

$(ROOT_HELPER): src/headless-virtual-display-root.c Makefile | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CONFIG_CPPFLAG) $(CFLAGS) $(HARDENING_CFLAGS) $(HARDENING_LDFLAGS) -o "$@" "$<"

$(ROOT_VALIDATOR_TEST): tests/root_helper_validator_test.c src/headless-virtual-display-root.c Makefile | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CONFIG_CPPFLAG) $(CFLAGS) $(HARDENING_CFLAGS) $(HARDENING_LDFLAGS) -o "$@" "$<"

$(ROOT_CONFIG_TEST): tests/root_helper_config_test.c src/headless-virtual-display-root.c Makefile | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CONFIG_CPPFLAG) $(CFLAGS) $(HARDENING_CFLAGS) $(HARDENING_LDFLAGS) -o "$@" "$<"

$(BASELINE_EDID): scripts/edid.py | $(BUILD_DIR)
	PYTHONDONTWRITEBYTECODE=1 ./scripts/edid.py generate 1920 1080 60 "$@"

$(GENERATED_CONFIG_MODULE): scripts/config.py Makefile | $(BUILD_DIR)
	sed 's|/etc/headless-virtual-display/topology.conf|$(CONFIG_PATH)|' "$<" >"$@"

$(GENERATED_DRM_UNIT): packaging/systemd/system/headless-virtual-display-drm.service Makefile | $(BUILD_DIR)
	sed 's|/usr/local|$(PREFIX)|g' "$<" >"$@"

$(GENERATED_KWIN_UNIT): packaging/systemd/user/headless-virtual-display-kwin.service Makefile | $(BUILD_DIR)
	sed 's|/usr/local|$(PREFIX)|g' "$<" >"$@"

$(GENERATED_SUDOERS): scripts/headless-virtual-display-setup scripts/config.py scripts/edid.py Makefile | $(BUILD_DIR)
	PYTHONDONTWRITEBYTECODE=1 python -c 'import runpy, pathlib; ns = runpy.run_path("scripts/headless-virtual-display-setup", run_name="setup_check"); pathlib.Path("$(GENERATED_SUDOERS)").write_text(ns["_sudoers_text"]("testuser", pathlib.Path("$(LIBEXECDIR)/headless-virtual-display-root")))'

check: all $(ROOT_VALIDATOR_TEST) $(ROOT_CONFIG_TEST) $(GENERATED_SUDOERS)
	PYTHONDONTWRITEBYTECODE=1 python -c 'import ast, pathlib; [ast.parse(pathlib.Path(path).read_text()) for path in ("scripts/config.py", "scripts/edid.py", "scripts/virtual-display", "scripts/headless-virtual-display-setup")]'
	PYTHONDONTWRITEBYTECODE=1 python -c 'import runpy, pathlib; ns = runpy.run_path("scripts/config.py", run_name="config_example_check"); ns["parse_config_text"](pathlib.Path("packaging/config/topology.conf.example").read_text())'
	PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
	PYTHONDONTWRITEBYTECODE=1 ./scripts/virtual-display --version >/dev/null
	PYTHONDONTWRITEBYTECODE=1 ./scripts/headless-virtual-display-setup --version >/dev/null
	PYTHONDONTWRITEBYTECODE=1 ./scripts/edid.py normalize 2560 1600 120 >/dev/null
	PYTHONDONTWRITEBYTECODE=1 ./scripts/edid.py normalize 3840 2160 90 >/dev/null
	PYTHONDONTWRITEBYTECODE=1 ./scripts/edid.py normalize 5120 2880 60 >/dev/null
	"$(ROOT_VALIDATOR_TEST)" "$(BASELINE_EDID)"
	"$(ROOT_VALIDATOR_TEST)" test-data/generated-1920x1080-75.edid
	! "$(ROOT_VALIDATOR_TEST)" "$(BASELINE_EDID)" corrupt >/dev/null 2>&1
	"$(ROOT_CONFIG_TEST)"
	/usr/bin/visudo -cf "$(GENERATED_SUDOERS)"
	sed 's|$(LIBEXECDIR)/headless-virtual-display-root|$(abspath $(ROOT_HELPER))|' "$(GENERATED_DRM_UNIT)" >"$(BUILD_DIR)/headless-virtual-display-drm.verify.service"
	sed 's|$(BINDIR)/virtual-display|$(abspath scripts/virtual-display)|' "$(GENERATED_KWIN_UNIT)" >"$(BUILD_DIR)/headless-virtual-display-kwin.verify.service"
	/usr/bin/systemd-analyze verify "$(BUILD_DIR)/headless-virtual-display-drm.verify.service" "$(BUILD_DIR)/headless-virtual-display-kwin.verify.service"
	! rg -n 'ow[e]n|1002:1586' scripts/virtual-display scripts/config.py scripts/headless-virtual-display-setup src packaging/systemd packaging/sunshine
	touch "$(CHECK_STAMP)"

install:
	@test -x "$(ROOT_HELPER)" -a -r "$(BASELINE_EDID)" -a -r "$(GENERATED_CONFIG_MODULE)" -a -r "$(GENERATED_DRM_UNIT)" -a -r "$(GENERATED_KWIN_UNIT)" -a -r "$(CHECK_STAMP)" || { echo 'required checked artifacts are missing; run make check as an unprivileged user first' >&2; exit 1; }
	@test -z "$$(find Makefile scripts src tests packaging/systemd packaging/config -type f -newer "$(CHECK_STAMP)" -print -quit)" || { echo 'source changed after make check; rerun make check as an unprivileged user' >&2; exit 1; }
	@if test -z "$(DESTDIR)"; then test "$$(id -u)" -eq 0 || { echo 'direct make install must run as root; package builds should set DESTDIR' >&2; exit 1; }; fi
	install -D -m 0755 "$(ROOT_HELPER)" "$(DESTDIR)$(LIBEXECDIR)/headless-virtual-display-root"
	install -D -m 0755 scripts/virtual-display "$(DESTDIR)$(BINDIR)/virtual-display"
	install -D -m 0755 scripts/headless-virtual-display-setup "$(DESTDIR)$(BINDIR)/headless-virtual-display-setup"
	install -D -m 0644 scripts/edid.py "$(DESTDIR)$(LIBDIR)/edid.py"
	install -D -m 0644 "$(GENERATED_CONFIG_MODULE)" "$(DESTDIR)$(LIBDIR)/config.py"
	install -D -m 0644 "$(BASELINE_EDID)" "$(DESTDIR)$(DATADIR)/baseline-1920x1080-60.edid"
	install -D -m 0644 packaging/config/topology.conf.example "$(DESTDIR)$(DATADIR)/topology.conf.example"
	install -D -m 0644 "$(GENERATED_DRM_UNIT)" "$(DESTDIR)$(SYSTEMD_SYSTEM_DIR)/headless-virtual-display-drm.service"
	install -D -m 0644 packaging/systemd/system/display-manager.service.d/50-headless-virtual-display.conf "$(DESTDIR)$(SYSTEMD_SYSTEM_DIR)/display-manager.service.d/50-headless-virtual-display.conf"
	install -D -m 0644 "$(GENERATED_KWIN_UNIT)" "$(DESTDIR)$(SYSTEMD_USER_DIR)/headless-virtual-display-kwin.service"
	install -D -m 0644 notes/production-design.md "$(DESTDIR)$(DOCDIR)/production-design.md"
	install -D -m 0644 notes/install.md "$(DESTDIR)$(DOCDIR)/install.md"
	install -D -m 0644 notes/test-plan.md "$(DESTDIR)$(DOCDIR)/test-plan.md"
	install -D -m 0644 README.md "$(DESTDIR)$(DOCDIR)/README.md"
	install -D -m 0644 CHANGELOG.md "$(DESTDIR)$(DOCDIR)/CHANGELOG.md"
	install -D -m 0644 SECURITY.md "$(DESTDIR)$(DOCDIR)/SECURITY.md"
	@echo 'Files installed but no topology was configured and no service was enabled or started.'
	@echo 'Run sudo $(BINDIR)/headless-virtual-display-setup configure --user USER next.'

clean:
	@echo "Remove the generated $(BUILD_DIR) directory manually after confirming its path."
