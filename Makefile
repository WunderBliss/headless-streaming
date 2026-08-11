PREFIX ?= /usr/local
SYSCONFDIR ?= /etc
BUILD_DIR ?= build
CC ?= cc
CFLAGS ?= -O2
HARDENING_CFLAGS := -std=c17 -Wall -Wextra -Wpedantic -Werror -D_FORTIFY_SOURCE=3 -fstack-protector-strong -fPIE
HARDENING_LDFLAGS := -pie -Wl,-z,relro,-z,now

ROOT_HELPER := $(BUILD_DIR)/headless-virtual-display-root
ROOT_VALIDATOR_TEST := $(BUILD_DIR)/root-helper-validator-test
BASELINE_EDID := $(BUILD_DIR)/baseline-1920x1080-60.edid

.PHONY: all check install clean

all: $(ROOT_HELPER) $(BASELINE_EDID)

$(BUILD_DIR):
	mkdir -p "$@"

$(ROOT_HELPER): src/headless-virtual-display-root.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(HARDENING_CFLAGS) $(HARDENING_LDFLAGS) -o "$@" "$<"

$(ROOT_VALIDATOR_TEST): tests/root_helper_validator_test.c src/headless-virtual-display-root.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(HARDENING_CFLAGS) $(HARDENING_LDFLAGS) -o "$@" "$<"

$(BASELINE_EDID): scripts/edid.py | $(BUILD_DIR)
	PYTHONDONTWRITEBYTECODE=1 ./scripts/edid.py generate 1920 1080 60 "$@"

check: all $(ROOT_VALIDATOR_TEST)
	PYTHONDONTWRITEBYTECODE=1 python -c 'import ast, pathlib; [ast.parse(pathlib.Path(path).read_text()) for path in ("scripts/edid.py", "scripts/virtual-display")]'
	PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
	PYTHONDONTWRITEBYTECODE=1 ./scripts/edid.py normalize 2560 1600 120 >/dev/null
	PYTHONDONTWRITEBYTECODE=1 ./scripts/edid.py normalize 3840 2160 90 >/dev/null
	PYTHONDONTWRITEBYTECODE=1 ./scripts/edid.py normalize 5120 2880 60 >/dev/null
	PYTHONDONTWRITEBYTECODE=1 python -c 'import json, pathlib; lines = pathlib.Path("packaging/sunshine/sunshine.conf").read_text().splitlines(); value = next(line.split("=", 1)[1].strip() for line in lines if line.startswith("global_prep_cmd")); commands = json.loads(value); assert commands == [{"do": "/usr/local/bin/virtual-display sunshine-up", "undo": ""}]'
	"$(ROOT_VALIDATOR_TEST)" "$(BASELINE_EDID)"
	! "$(ROOT_VALIDATOR_TEST)" "$(BASELINE_EDID)" corrupt >/dev/null 2>&1
	/usr/bin/visudo -cf packaging/sudoers/headless-virtual-display
	sed 's|/usr/local/libexec/headless-virtual-display-root|$(abspath $(ROOT_HELPER))|' packaging/systemd/system/headless-virtual-display-drm.service >"$(BUILD_DIR)/headless-virtual-display-drm.verify.service"
	sed 's|/usr/local/bin/virtual-display|$(abspath scripts/virtual-display)|' packaging/systemd/user/headless-virtual-display-kwin.service >"$(BUILD_DIR)/headless-virtual-display-kwin.verify.service"
	/usr/bin/systemd-analyze verify "$(BUILD_DIR)/headless-virtual-display-drm.verify.service" "$(BUILD_DIR)/headless-virtual-display-kwin.verify.service"

install:
	@test "$$(id -u)" -eq 0 || { echo 'make install must run as root' >&2; exit 1; }
	@test -x "$(ROOT_HELPER)" -a -r "$(BASELINE_EDID)" || { echo 'run make check as owen before make install' >&2; exit 1; }
	/usr/bin/visudo -cf packaging/sudoers/headless-virtual-display
	install -D -o root -g root -m 0755 "$(ROOT_HELPER)" "$(PREFIX)/libexec/headless-virtual-display-root"
	install -D -o root -g root -m 0755 scripts/virtual-display "$(PREFIX)/bin/virtual-display"
	install -D -o root -g root -m 0644 scripts/edid.py "$(PREFIX)/lib/headless-virtual-display/edid.py"
	install -D -o root -g root -m 0644 "$(BASELINE_EDID)" "$(PREFIX)/share/headless-virtual-display/baseline-1920x1080-60.edid"
	install -D -o root -g root -m 0440 packaging/sudoers/headless-virtual-display "$(SYSCONFDIR)/sudoers.d/headless-virtual-display"
	/usr/bin/visudo -cf "$(SYSCONFDIR)/sudoers.d/headless-virtual-display"
	install -D -o root -g root -m 0644 packaging/systemd/system/headless-virtual-display-drm.service "$(SYSCONFDIR)/systemd/system/headless-virtual-display-drm.service"
	install -D -o root -g root -m 0644 packaging/systemd/system/display-manager.service.d/50-headless-virtual-display.conf "$(SYSCONFDIR)/systemd/system/display-manager.service.d/50-headless-virtual-display.conf"
	install -D -o root -g root -m 0644 packaging/systemd/user/headless-virtual-display-kwin.service "$(SYSCONFDIR)/systemd/user/headless-virtual-display-kwin.service"
	install -D -o root -g root -m 0644 packaging/systemd/user/app-dev.lizardbyte.app.Sunshine.service.d/50-headless-virtual-display.conf "$(SYSCONFDIR)/systemd/user/app-dev.lizardbyte.app.Sunshine.service.d/50-headless-virtual-display.conf"
	install -D -o root -g root -m 0644 notes/production-design.md "$(PREFIX)/share/doc/headless-virtual-display/production-design.md"
	install -D -o root -g root -m 0644 notes/install.md "$(PREFIX)/share/doc/headless-virtual-display/install.md"
	install -D -o root -g root -m 0644 notes/test-plan.md "$(PREFIX)/share/doc/headless-virtual-display/test-plan.md"
	@echo 'Files installed but no unit was enabled/started and Sunshine configuration was not changed.'

clean:
	@echo "Remove the generated $(BUILD_DIR) directory manually after confirming its path."
