#define main headless_virtual_display_privileged_main
#include "../src/headless-virtual-display-root.c"
#undef main

static bool parses(char *text)
{
    struct runtime_config config = {0};
    return parse_config_text(text, &config);
}

int main(void)
{
    char valid[] =
        "schema_version=1\n"
        "desktop_user=alice\n"
        "desktop_uid=1000\n"
        "pci_slot=0000:c5:00.0\n"
        "pci_vendor=1002\n"
        "pci_device=1586\n"
        "driver=amdgpu\n"
        "connector=DP-3\n";
    struct runtime_config config = {0};
    if (!parse_config_text(valid, &config) ||
        strcmp(config.desktop_user, "alice") != 0 ||
        config.desktop_uid != 1000U ||
        strcmp(config.pci_slot, "0000:c5:00.0") != 0 ||
        strcmp(config.connector, "DP-3") != 0) {
        return 1;
    }

    char duplicate[] =
        "schema_version=1\n"
        "schema_version=1\n"
        "desktop_user=alice\n"
        "desktop_uid=1000\n"
        "pci_slot=0000:c5:00.0\n"
        "pci_vendor=1002\n"
        "pci_device=1586\n"
        "driver=amdgpu\n"
        "connector=DP-3\n";
    char unsafe_connector[] =
        "schema_version=1\n"
        "desktop_user=alice\n"
        "desktop_uid=1000\n"
        "pci_slot=0000:c5:00.0\n"
        "pci_vendor=1002\n"
        "pci_device=1586\n"
        "driver=amdgpu\n"
        "connector=DP-3/../../HDMI-A-1\n";
    char unknown[] =
        "schema_version=1\n"
        "desktop_user=alice\n"
        "desktop_uid=1000\n"
        "pci_slot=0000:c5:00.0\n"
        "pci_vendor=1002\n"
        "pci_device=1586\n"
        "driver=amdgpu\n"
        "connector=DP-3\n"
        "command=/bin/sh\n";
    return parses(duplicate) || parses(unsafe_connector) || parses(unknown)
               ? 1
               : 0;
}
