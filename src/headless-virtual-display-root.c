#define _GNU_SOURCE

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define EDID_SIZE 128U
#define STATUS_SIZE 32U
#define TEXT_SIZE 64U
#define CONFIG_SIZE 4096U
#define CONFIG_SCHEMA_VERSION 1U
#ifndef CONFIG_PATH
#define CONFIG_PATH "/etc/headless-virtual-display/topology.conf"
#endif
#define LOCK_PATH "/run/lock/headless-virtual-display-root.lock"

struct runtime_config {
    char desktop_user[33];
    unsigned long desktop_uid;
    char pci_slot[13];
    char pci_vendor[5];
    char pci_device[5];
    char driver[33];
    char connector[65];
};

struct topology {
    char pci_slot[32];
    char pci_path[PATH_MAX];
    char card_name[32];
    char connector_path[PATH_MAX];
    char debugfs_path[PATH_MAX];
};

static void report_errno(const char *context, const char *path)
{
    fprintf(stderr, "headless-virtual-display-root: %s %s: %s\n",
            context, path, strerror(errno));
}

static bool append_path(char *destination, size_t size,
                        const char *left, const char *right)
{
    int written = snprintf(destination, size, "%s/%s", left, right);
    if (written < 0 || (size_t)written >= size) {
        fprintf(stderr, "headless-virtual-display-root: path is too long\n");
        return false;
    }
    return true;
}

static bool is_pci_slot(const char *value)
{
    static const size_t hex_positions[] = {0U, 1U, 2U, 3U, 5U,
                                           6U, 8U, 9U, 11U};
    if (strlen(value) != 12U || value[4] != ':' || value[7] != ':' ||
        value[10] != '.') {
        return false;
    }
    for (size_t index = 0; index < sizeof(hex_positions) / sizeof(hex_positions[0]);
         ++index) {
        if (!isxdigit((unsigned char)value[hex_positions[index]])) {
            return false;
        }
    }
    return (value[8] == '0' || value[8] == '1') &&
           value[11] >= '0' && value[11] <= '7';
}

static bool is_card_name(const char *value)
{
    if (strncmp(value, "card", 4) != 0 || value[4] == '\0') {
        return false;
    }
    for (const char *cursor = value + 4; *cursor != '\0'; ++cursor) {
        if (!isdigit((unsigned char)*cursor)) {
            return false;
        }
    }
    return true;
}

static bool copy_config_value(char *destination, size_t capacity,
                              const char *value)
{
    size_t length = strlen(value);
    if (length == 0U || length >= capacity) {
        return false;
    }
    memcpy(destination, value, length + 1U);
    return true;
}

static bool is_safe_user(const char *value)
{
    size_t length = strlen(value);
    if (length == 0U || length > 32U ||
        !(isalpha((unsigned char)value[0]) || value[0] == '_')) {
        return false;
    }
    for (size_t index = 1U; index < length; ++index) {
        if (!(isalnum((unsigned char)value[index]) || value[index] == '_' ||
              value[index] == '-')) {
            return false;
        }
    }
    return true;
}

static bool is_lower_hex4(const char *value)
{
    if (strlen(value) != 4U) {
        return false;
    }
    for (size_t index = 0U; index < 4U; ++index) {
        if (!(isdigit((unsigned char)value[index]) ||
              (value[index] >= 'a' && value[index] <= 'f'))) {
            return false;
        }
    }
    return true;
}

static bool is_safe_driver(const char *value)
{
    size_t length = strlen(value);
    if (length == 0U || length > 32U) {
        return false;
    }
    for (size_t index = 0U; index < length; ++index) {
        if (!(islower((unsigned char)value[index]) ||
              isdigit((unsigned char)value[index]) || value[index] == '_')) {
            return false;
        }
    }
    return true;
}

static bool is_safe_connector(const char *value)
{
    size_t length = strlen(value);
    if (length < 2U || length > 64U ||
        !isalnum((unsigned char)value[0])) {
        return false;
    }
    for (size_t index = 1U; index < length; ++index) {
        if (!(isalnum((unsigned char)value[index]) || value[index] == '-')) {
            return false;
        }
    }
    return true;
}

static bool parse_decimal(const char *value, unsigned long maximum,
                          unsigned long *result)
{
    if (value[0] == '\0' || (value[0] == '0' && value[1] != '\0')) {
        return false;
    }
    for (const char *cursor = value; *cursor != '\0'; ++cursor) {
        if (!isdigit((unsigned char)*cursor)) {
            return false;
        }
    }
    errno = 0;
    char *end = NULL;
    unsigned long parsed = strtoul(value, &end, 10);
    if (errno != 0 || end == NULL || *end != '\0' || parsed == 0U ||
        parsed > maximum) {
        return false;
    }
    *result = parsed;
    return true;
}

static bool parse_config_text(char *text, struct runtime_config *config)
{
    enum {
        SEEN_SCHEMA = 1U << 0U,
        SEEN_USER = 1U << 1U,
        SEEN_UID = 1U << 2U,
        SEEN_SLOT = 1U << 3U,
        SEEN_VENDOR = 1U << 4U,
        SEEN_DEVICE = 1U << 5U,
        SEEN_DRIVER = 1U << 6U,
        SEEN_CONNECTOR = 1U << 7U,
        SEEN_ALL = (1U << 8U) - 1U,
    };
    unsigned int seen = 0U;
    unsigned long schema = 0U;
    char *save = NULL;
    unsigned int line_number = 0U;
    for (char *line = strtok_r(text, "\n", &save); line != NULL;
         line = strtok_r(NULL, "\n", &save)) {
        ++line_number;
        if (line[0] == '\0' || line[0] == '#') {
            continue;
        }
        if (strchr(line, '\r') != NULL || strchr(line, ' ') != NULL ||
            strchr(line, '\t') != NULL) {
            fprintf(stderr,
                    "headless-virtual-display-root: invalid whitespace on config line %u\n",
                    line_number);
            return false;
        }
        char *separator = strchr(line, '=');
        if (separator == NULL || separator == line || separator[1] == '\0' ||
            strchr(separator + 1, '=') != NULL) {
            fprintf(stderr,
                    "headless-virtual-display-root: invalid config syntax on line %u\n",
                    line_number);
            return false;
        }
        *separator = '\0';
        const char *key = line;
        const char *value = separator + 1;
        unsigned int bit = 0U;
        bool valid = false;
        if (strcmp(key, "schema_version") == 0) {
            bit = SEEN_SCHEMA;
            valid = parse_decimal(value, 999U, &schema) &&
                    schema == CONFIG_SCHEMA_VERSION;
        } else if (strcmp(key, "desktop_user") == 0) {
            bit = SEEN_USER;
            valid = is_safe_user(value) &&
                    copy_config_value(config->desktop_user,
                                      sizeof(config->desktop_user), value);
        } else if (strcmp(key, "desktop_uid") == 0) {
            bit = SEEN_UID;
            valid = parse_decimal(value, 2147483647UL,
                                  &config->desktop_uid);
        } else if (strcmp(key, "pci_slot") == 0) {
            bit = SEEN_SLOT;
            valid = is_pci_slot(value) &&
                    copy_config_value(config->pci_slot,
                                      sizeof(config->pci_slot), value);
        } else if (strcmp(key, "pci_vendor") == 0) {
            bit = SEEN_VENDOR;
            valid = is_lower_hex4(value) &&
                    copy_config_value(config->pci_vendor,
                                      sizeof(config->pci_vendor), value);
        } else if (strcmp(key, "pci_device") == 0) {
            bit = SEEN_DEVICE;
            valid = is_lower_hex4(value) &&
                    copy_config_value(config->pci_device,
                                      sizeof(config->pci_device), value);
        } else if (strcmp(key, "driver") == 0) {
            bit = SEEN_DRIVER;
            valid = is_safe_driver(value) &&
                    copy_config_value(config->driver,
                                      sizeof(config->driver), value);
        } else if (strcmp(key, "connector") == 0) {
            bit = SEEN_CONNECTOR;
            valid = is_safe_connector(value) &&
                    copy_config_value(config->connector,
                                      sizeof(config->connector), value);
        } else {
            fprintf(stderr,
                    "headless-virtual-display-root: unknown config key %s\n",
                    key);
            return false;
        }
        if ((seen & bit) != 0U || !valid) {
            fprintf(stderr,
                    "headless-virtual-display-root: duplicate or invalid config key %s\n",
                    key);
            return false;
        }
        seen |= bit;
    }
    if (seen != SEEN_ALL) {
        fprintf(stderr,
                "headless-virtual-display-root: topology config is incomplete\n");
        return false;
    }
    return true;
}

static bool load_config(struct runtime_config *config)
{
    struct stat before;
    if (lstat(CONFIG_PATH, &before) != 0) {
        report_errno("cannot inspect config", CONFIG_PATH);
        return false;
    }
    if (!S_ISREG(before.st_mode) || before.st_uid != 0U ||
        (before.st_mode & 0022U) != 0U) {
        fprintf(stderr,
                "headless-virtual-display-root: unsafe topology config metadata: %s\n",
                CONFIG_PATH);
        return false;
    }
    int descriptor = open(CONFIG_PATH, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        report_errno("cannot open config", CONFIG_PATH);
        return false;
    }
    struct stat after;
    if (fstat(descriptor, &after) != 0 || before.st_dev != after.st_dev ||
        before.st_ino != after.st_ino || !S_ISREG(after.st_mode) ||
        after.st_uid != 0U || (after.st_mode & 0022U) != 0U) {
        fprintf(stderr,
                "headless-virtual-display-root: topology config changed or is unsafe\n");
        close(descriptor);
        return false;
    }
    char text[CONFIG_SIZE + 1U];
    size_t used = 0U;
    while (used < sizeof(text)) {
        ssize_t amount = read(descriptor, text + used, sizeof(text) - used);
        if (amount < 0 && errno == EINTR) {
            continue;
        }
        if (amount < 0) {
            report_errno("cannot read config", CONFIG_PATH);
            close(descriptor);
            return false;
        }
        if (amount == 0) {
            break;
        }
        used += (size_t)amount;
    }
    bool close_ok = close(descriptor) == 0;
    if (!close_ok) {
        report_errno("cannot close config", CONFIG_PATH);
    }
    if (!close_ok || used == 0U || used > CONFIG_SIZE) {
        fprintf(stderr,
                "headless-virtual-display-root: topology config must contain 1..%u bytes\n",
                CONFIG_SIZE);
        return false;
    }
    if (memchr(text, '\0', used) != NULL) {
        fprintf(stderr,
                "headless-virtual-display-root: topology config contains a NUL byte\n");
        return false;
    }
    text[used] = '\0';
    memset(config, 0, sizeof(*config));
    return parse_config_text(text, config);
}

static bool read_bounded_file(const char *path, uint8_t *buffer,
                              size_t capacity, size_t *length)
{
    int descriptor = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        report_errno("cannot open", path);
        return false;
    }
    size_t used = 0;
    while (used < capacity) {
        ssize_t amount = read(descriptor, buffer + used, capacity - used);
        if (amount < 0 && errno == EINTR) {
            continue;
        }
        if (amount < 0) {
            report_errno("cannot read", path);
            close(descriptor);
            return false;
        }
        if (amount == 0) {
            break;
        }
        used += (size_t)amount;
    }
    if (close(descriptor) != 0) {
        report_errno("cannot close", path);
        return false;
    }
    *length = used;
    return true;
}

static bool read_text(const char *path, char *buffer, size_t capacity)
{
    if (capacity < 2U) {
        return false;
    }
    size_t length = 0;
    if (!read_bounded_file(path, (uint8_t *)buffer, capacity - 1U, &length)) {
        return false;
    }
    buffer[length] = '\0';
    while (length > 0U &&
           (buffer[length - 1U] == '\n' || buffer[length - 1U] == '\r' ||
            buffer[length - 1U] == ' ' || buffer[length - 1U] == '\t')) {
        buffer[--length] = '\0';
    }
    return true;
}

static const char *last_component(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash == NULL ? path : slash + 1;
}

static bool path_belongs_to(const char *path, const char *parent)
{
    size_t parent_length = strlen(parent);
    return strncmp(path, parent, parent_length) == 0 &&
           path[parent_length] == '/';
}

static bool find_card(const char *pci_path, char *card_name, size_t size)
{
    char drm_path[PATH_MAX];
    if (!append_path(drm_path, sizeof(drm_path), pci_path, "drm")) {
        return false;
    }
    DIR *directory = opendir(drm_path);
    if (directory == NULL) {
        report_errno("cannot open DRM directory", drm_path);
        return false;
    }
    unsigned int matches = 0;
    struct dirent *entry = NULL;
    int saved_errno = 0;
    for (;;) {
        errno = 0;
        entry = readdir(directory);
        if (entry == NULL) {
            saved_errno = errno;
            break;
        }
        if (!is_card_name(entry->d_name)) {
            continue;
        }
        ++matches;
        int written = snprintf(card_name, size, "%s", entry->d_name);
        if (written < 0 || (size_t)written >= size) {
            fprintf(stderr, "headless-virtual-display-root: DRM card name is too long\n");
            closedir(directory);
            return false;
        }
    }
    if (closedir(directory) != 0) {
        report_errno("cannot close DRM directory", drm_path);
        return false;
    }
    if (saved_errno != 0) {
        errno = saved_errno;
        report_errno("cannot enumerate DRM directory", drm_path);
        return false;
    }
    if (matches != 1U) {
        fprintf(stderr,
                "headless-virtual-display-root: expected exactly one DRM card below %s, found %u\n",
                pci_path, matches);
        return false;
    }
    return true;
}

static bool inspect_pci_device(const struct runtime_config *config,
                               struct topology *candidate)
{
    char device_path[PATH_MAX];
    char vendor_path[PATH_MAX];
    char device_id_path[PATH_MAX];
    char driver_path[PATH_MAX];
    char resolved_driver[PATH_MAX];
    char vendor[TEXT_SIZE];
    char device_id[TEXT_SIZE];

    int device_path_written = snprintf(device_path, sizeof(device_path),
                                       "/sys/bus/pci/devices/%s",
                                       config->pci_slot);
    if (device_path_written < 0 ||
        (size_t)device_path_written >= sizeof(device_path) ||
        !append_path(vendor_path, sizeof(vendor_path), device_path, "vendor") ||
        !append_path(device_id_path, sizeof(device_id_path), device_path, "device") ||
        !append_path(driver_path, sizeof(driver_path), device_path, "driver")) {
        return false;
    }
    if (!read_text(vendor_path, vendor, sizeof(vendor)) ||
        !read_text(device_id_path, device_id, sizeof(device_id))) {
        return false;
    }
    char expected_vendor[7];
    char expected_device[7];
    int vendor_written = snprintf(expected_vendor, sizeof(expected_vendor),
                                  "0x%s", config->pci_vendor);
    int device_written = snprintf(expected_device, sizeof(expected_device),
                                  "0x%s", config->pci_device);
    if (vendor_written != 6 || device_written != 6 ||
        strcmp(vendor, expected_vendor) != 0 ||
        strcmp(device_id, expected_device) != 0) {
        return false;
    }
    if (realpath(driver_path, resolved_driver) == NULL) {
        report_errno("cannot resolve driver", driver_path);
        return false;
    }
    if (strcmp(last_component(resolved_driver), config->driver) != 0) {
        return false;
    }
    if (realpath(device_path, candidate->pci_path) == NULL) {
        report_errno("cannot resolve PCI device", device_path);
        return false;
    }
    if (!is_pci_slot(last_component(candidate->pci_path))) {
        fprintf(stderr,
                "headless-virtual-display-root: resolved PCI path has unsafe identity: %s\n",
                candidate->pci_path);
        return false;
    }
    int slot_written = snprintf(candidate->pci_slot, sizeof(candidate->pci_slot),
                                "%s", last_component(candidate->pci_path));
    if (slot_written < 0 ||
        (size_t)slot_written >= sizeof(candidate->pci_slot) ||
        !find_card(candidate->pci_path, candidate->card_name,
                   sizeof(candidate->card_name))) {
        return false;
    }

    char drm_card_path[PATH_MAX];
    char connector_name[64];
    char unresolved_connector[PATH_MAX];
    char resolved_connector[PATH_MAX];
    int connector_written = snprintf(connector_name, sizeof(connector_name),
                                     "%s-%s", candidate->card_name,
                                     config->connector);
    int drm_path_written = snprintf(drm_card_path, sizeof(drm_card_path),
                                    "%s/drm/%s", candidate->pci_path,
                                    candidate->card_name);
    if (connector_written < 0 ||
        (size_t)connector_written >= sizeof(connector_name) ||
        drm_path_written < 0 ||
        (size_t)drm_path_written >= sizeof(drm_card_path) ||
        !append_path(unresolved_connector, sizeof(unresolved_connector),
                     drm_card_path, connector_name)) {
        return false;
    }
    if (realpath(unresolved_connector, resolved_connector) == NULL) {
        report_errno("cannot resolve configured connector", unresolved_connector);
        return false;
    }
    if (!path_belongs_to(resolved_connector, candidate->pci_path)) {
        fprintf(stderr,
                "headless-virtual-display-root: configured connector resolves outside the target PCI device\n");
        return false;
    }
    int connector_path_written = snprintf(
        candidate->connector_path, sizeof(candidate->connector_path), "%s",
        resolved_connector);
    int debugfs_path_written = snprintf(
        candidate->debugfs_path, sizeof(candidate->debugfs_path),
        "/sys/kernel/debug/dri/%s/%s", candidate->pci_slot,
        config->connector);
    if (connector_path_written < 0 ||
        (size_t)connector_path_written >= sizeof(candidate->connector_path) ||
        debugfs_path_written < 0 ||
        (size_t)debugfs_path_written >= sizeof(candidate->debugfs_path)) {
        return false;
    }
    return true;
}

static bool discover_topology(const struct runtime_config *config,
                              struct topology *result)
{
    if (!inspect_pci_device(config, result)) {
        fprintf(stderr,
                "headless-virtual-display-root: configured topology %s %s:%s %s/%s did not match\n",
                config->pci_slot, config->pci_vendor, config->pci_device,
                config->driver, config->connector);
        return false;
    }
    return true;
}

static bool decode_manufacturer(const uint8_t edid[EDID_SIZE])
{
    uint16_t word = (uint16_t)(((uint16_t)edid[8] << 8U) | edid[9]);
    char manufacturer[4] = {
        (char)(((word >> 10U) & 0x1fU) + 'A' - 1),
        (char)(((word >> 5U) & 0x1fU) + 'A' - 1),
        (char)((word & 0x1fU) + 'A' - 1),
        '\0',
    };
    return strcmp(manufacturer, "VDS") == 0;
}

static bool validate_edid(const uint8_t edid[EDID_SIZE])
{
    static const uint8_t header[8] = {0x00, 0xff, 0xff, 0xff,
                                      0xff, 0xff, 0xff, 0x00};
    static const uint8_t dummy_descriptor[18] = {
        0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    };
    uint8_t checksum = 0;
    for (size_t index = 0; index < EDID_SIZE; ++index) {
        checksum = (uint8_t)(checksum + edid[index]);
    }
    if (memcmp(edid, header, sizeof(header)) != 0 || checksum != 0U ||
        edid[126] != 0U || edid[18] != 1U || edid[19] != 4U ||
        (edid[20] & 0x80U) == 0U || (edid[24] & 0x02U) == 0U) {
        fprintf(stderr,
                "headless-virtual-display-root: EDID header/version/flags/block/checksum validation failed\n");
        return false;
    }
    bool current_identity =
        memcmp(edid + 72, "\0\0\0\xfc\0HEADLESS-VDS\n", 18) == 0 &&
        memcmp(edid + 90, "\0\0\0\xff\0HVD-00000001\n", 18) == 0;
    bool legacy_identity =
        memcmp(edid + 72, "\0\0\0\xfc\0VIRTUAL-POC\n ", 18) == 0 &&
        memcmp(edid + 90, "\0\0\0\xff\0VDS-POC-0001\n", 18) == 0;
    if (!decode_manufacturer(edid) || edid[10] != 0x50U ||
        edid[11] != 0xd1U || memcmp(edid + 12, "\0\0\0\0", 4) != 0 ||
        (!current_identity && !legacy_identity) ||
        memcmp(edid + 108, dummy_descriptor, sizeof(dummy_descriptor)) != 0) {
        fprintf(stderr,
                "headless-virtual-display-root: EDID does not have the full managed VDS identity\n");
        return false;
    }

    const uint8_t *dtd = edid + 54;
    unsigned int clock_units = (unsigned int)dtd[0] |
                               ((unsigned int)dtd[1] << 8U);
    unsigned int width = (unsigned int)dtd[2] |
                         (((unsigned int)dtd[4] >> 4U) << 8U);
    unsigned int h_blank = (unsigned int)dtd[3] |
                           (((unsigned int)dtd[4] & 0x0fU) << 8U);
    unsigned int height = (unsigned int)dtd[5] |
                          (((unsigned int)dtd[7] >> 4U) << 8U);
    unsigned int v_blank = (unsigned int)dtd[6] |
                           (((unsigned int)dtd[7] & 0x0fU) << 8U);
    unsigned int width_mm = (unsigned int)dtd[12] |
                            (((unsigned int)dtd[14] >> 4U) << 8U);
    unsigned int height_mm = (unsigned int)dtd[13] |
                             (((unsigned int)dtd[14] & 0x0fU) << 8U);
    if (clock_units == 0U || width < 320U || width > 4095U ||
        width % 8U != 0U || height < 200U || height > 4095U ||
        h_blank == 0U || v_blank == 0U || width_mm == 0U ||
        height_mm == 0U || (dtd[17] & 0x80U) != 0U ||
        (dtd[17] & 0x18U) != 0x18U) {
        fprintf(stderr,
                "headless-virtual-display-root: EDID preferred timing validation failed\n");
        return false;
    }
    double refresh = ((double)clock_units * 10000.0) /
                     ((double)(width + h_blank) * (double)(height + v_blank));
    if (refresh < 23.5 || refresh > 240.5) {
        fprintf(stderr,
                "headless-virtual-display-root: EDID preferred refresh %.6f is outside policy\n",
                refresh);
        return false;
    }
    return true;
}

static bool read_stdin_edid(uint8_t edid[EDID_SIZE])
{
    size_t used = 0;
    while (used < EDID_SIZE) {
        ssize_t amount = read(STDIN_FILENO, edid + used, EDID_SIZE - used);
        if (amount < 0 && errno == EINTR) {
            continue;
        }
        if (amount < 0) {
            report_errno("cannot read EDID from", "stdin");
            return false;
        }
        if (amount == 0) {
            break;
        }
        used += (size_t)amount;
    }
    uint8_t extra = 0;
    ssize_t extra_amount;
    do {
        extra_amount = read(STDIN_FILENO, &extra, 1U);
    } while (extra_amount < 0 && errno == EINTR);
    if (used != EDID_SIZE || extra_amount != 0) {
        fprintf(stderr,
                "headless-virtual-display-root: stdin must contain exactly one 128-byte base EDID\n");
        return false;
    }
    return validate_edid(edid);
}

static bool read_status(const struct topology *topology,
                        char status[STATUS_SIZE])
{
    char path[PATH_MAX];
    if (!append_path(path, sizeof(path), topology->connector_path, "status")) {
        return false;
    }
    if (!read_text(path, status, STATUS_SIZE)) {
        return false;
    }
    if (strcmp(status, "connected") != 0 &&
        strcmp(status, "disconnected") != 0) {
        fprintf(stderr,
                "headless-virtual-display-root: refusing unexpected %s status %s\n",
                last_component(topology->debugfs_path), status);
        return false;
    }
    return true;
}

static bool read_current_edid(const struct topology *topology,
                              uint8_t edid[EDID_SIZE], size_t *length)
{
    char path[PATH_MAX];
    if (!append_path(path, sizeof(path), topology->connector_path, "edid")) {
        return false;
    }
    uint8_t bounded[EDID_SIZE + 1U];
    size_t amount = 0;
    if (!read_bounded_file(path, bounded, sizeof(bounded), &amount)) {
        return false;
    }
    if (amount > EDID_SIZE) {
        fprintf(stderr,
                "headless-virtual-display-root: current %s EDID exceeds the managed size\n",
                last_component(topology->debugfs_path));
        return false;
    }
    memcpy(edid, bounded, amount);
    *length = amount;
    return true;
}

static bool open_control(const struct topology *topology, const char *name,
                         int *descriptor)
{
    if (strcmp(name, "edid_override") != 0 && strcmp(name, "force") != 0 &&
        strcmp(name, "trigger_hotplug") != 0) {
        fprintf(stderr,
                "headless-virtual-display-root: internal debugfs allowlist rejected %s\n",
                name);
        return false;
    }
    char path[PATH_MAX];
    if (!append_path(path, sizeof(path), topology->debugfs_path, name)) {
        return false;
    }
    struct stat before;
    if (lstat(path, &before) != 0) {
        report_errno("cannot inspect", path);
        return false;
    }
    if (!S_ISREG(before.st_mode) || before.st_uid != 0U ||
        (before.st_mode & 0022U) != 0U) {
        fprintf(stderr,
                "headless-virtual-display-root: unsafe debugfs endpoint metadata: %s\n",
                path);
        return false;
    }
    int opened = open(path, O_WRONLY | O_CLOEXEC | O_NOFOLLOW);
    if (opened < 0) {
        report_errno("cannot open", path);
        return false;
    }
    struct stat after;
    if (fstat(opened, &after) != 0 || before.st_dev != after.st_dev ||
        before.st_ino != after.st_ino || !S_ISREG(after.st_mode) ||
        after.st_uid != 0U || (after.st_mode & 0022U) != 0U) {
        fprintf(stderr,
                "headless-virtual-display-root: debugfs endpoint changed or is unsafe: %s\n",
                path);
        close(opened);
        return false;
    }
    *descriptor = opened;
    return true;
}

static bool write_control(const struct topology *topology, const char *name,
                          const uint8_t *payload, size_t length)
{
    int descriptor = -1;
    if (!open_control(topology, name, &descriptor)) {
        return false;
    }
    ssize_t amount;
    do {
        amount = write(descriptor, payload, length);
    } while (amount < 0 && errno == EINTR);
    bool success = amount == (ssize_t)length;
    if (!success) {
        if (amount < 0) {
            report_errno("write failed for", name);
        } else {
            fprintf(stderr,
                    "headless-virtual-display-root: short debugfs write to %s (%zd/%zu)\n",
                    name, amount, length);
        }
    }
    if (close(descriptor) != 0) {
        report_errno("cannot close", name);
        success = false;
    }
    return success;
}

static bool trigger_hotplug(const struct topology *topology)
{
    static const uint8_t payload[] = {'1', '\n'};
    return write_control(topology, "trigger_hotplug", payload,
                         sizeof(payload));
}

static bool remove_writes(const struct topology *topology)
{
    static const uint8_t unspecified[] = "unspecified";
    static const uint8_t reset[] = "reset";
    bool force_ok = write_control(topology, "force", unspecified,
                                  sizeof(unspecified) - 1U);
    bool reset_ok = write_control(topology, "edid_override", reset,
                                  sizeof(reset) - 1U);
    bool hotplug_ok = trigger_hotplug(topology);
    return force_ok && reset_ok && hotplug_ok;
}

static bool apply_writes(const struct topology *topology,
                         const uint8_t edid[EDID_SIZE])
{
    static const uint8_t force_on[] = "on";
    return write_control(topology, "edid_override", edid, EDID_SIZE) &&
           write_control(topology, "force", force_on,
                         sizeof(force_on) - 1U) &&
           trigger_hotplug(topology);
}

static int acquire_lock(void)
{
    int descriptor = open(LOCK_PATH,
                          O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW,
                          0600);
    if (descriptor < 0) {
        report_errno("cannot open lock", LOCK_PATH);
        return -1;
    }
    struct stat metadata;
    if (fstat(descriptor, &metadata) != 0 ||
        !S_ISREG(metadata.st_mode) || metadata.st_uid != 0U ||
        (metadata.st_mode & 0077U) != 0U) {
        fprintf(stderr,
                "headless-virtual-display-root: unsafe root lock metadata\n");
        close(descriptor);
        return -1;
    }
    if (flock(descriptor, LOCK_EX) != 0) {
        report_errno("cannot lock", LOCK_PATH);
        close(descriptor);
        return -1;
    }
    return descriptor;
}

static int run_apply_or_retune(const struct topology *topology,
                               const char *operation,
                               const uint8_t new_edid[EDID_SIZE])
{
    char status[STATUS_SIZE];
    uint8_t previous_edid[EDID_SIZE] = {0};
    size_t previous_length = 0;
    if (!read_status(topology, status) ||
        !read_current_edid(topology, previous_edid, &previous_length)) {
        return 1;
    }
    bool connected = strcmp(status, "connected") == 0;
    if (strcmp(operation, "retune") == 0 && !connected) {
        fprintf(stderr,
                "headless-virtual-display-root: retune requires an already-connected %s\n",
                last_component(topology->debugfs_path));
        return 1;
    }
    if (connected &&
        (previous_length != EDID_SIZE || !validate_edid(previous_edid))) {
        fprintf(stderr,
                "headless-virtual-display-root: refusing to manipulate connected %s with an unrecognized physical/unmanaged EDID\n",
                last_component(topology->debugfs_path));
        return 1;
    }
    if (!apply_writes(topology, new_edid)) {
        fprintf(stderr,
                "headless-virtual-display-root: %s writes failed; attempting fail-safe rollback\n",
                operation);
        bool rollback_ok = connected
                               ? apply_writes(topology, previous_edid)
                               : remove_writes(topology);
        if (!rollback_ok) {
            fprintf(stderr,
                    "headless-virtual-display-root: rollback also failed; %s needs administrative recovery\n",
                    last_component(topology->debugfs_path));
        }
        return 1;
    }
    printf("%s accepted for %s on %s\n", operation,
           last_component(topology->debugfs_path),
           topology->pci_slot);
    return 0;
}

static int run_remove(const struct topology *topology)
{
    char status[STATUS_SIZE];
    uint8_t current_edid[EDID_SIZE] = {0};
    size_t current_length = 0;
    if (!read_status(topology, status) ||
        !read_current_edid(topology, current_edid, &current_length)) {
        return 1;
    }
    if (strcmp(status, "connected") == 0 &&
        (current_length != EDID_SIZE || !validate_edid(current_edid))) {
        fprintf(stderr,
                "headless-virtual-display-root: refusing to remove connected %s with an unrecognized physical/unmanaged EDID\n",
                last_component(topology->debugfs_path));
        return 1;
    }
    if (!remove_writes(topology)) {
        fprintf(stderr,
                "headless-virtual-display-root: remove writes were incomplete\n");
        return 1;
    }
    printf("remove accepted for %s on %s\n",
           last_component(topology->debugfs_path),
           topology->pci_slot);
    return 0;
}

static void usage(const char *program)
{
    fprintf(stderr, "usage: %s {apply|retune|remove|probe}\n", program);
    fprintf(stderr,
            "apply/retune read exactly one validated 128-byte managed EDID from stdin\n");
}

int main(int argc, char **argv)
{
    umask(0077);
    if (geteuid() != 0) {
        fprintf(stderr,
                "headless-virtual-display-root: this fixed-purpose helper must run as root\n");
        return 1;
    }
    if (argc != 2 ||
        (strcmp(argv[1], "apply") != 0 &&
         strcmp(argv[1], "retune") != 0 &&
         strcmp(argv[1], "remove") != 0 &&
         strcmp(argv[1], "probe") != 0)) {
        usage(argv[0]);
        return 2;
    }

    uint8_t input_edid[EDID_SIZE] = {0};
    if (strcmp(argv[1], "apply") == 0 || strcmp(argv[1], "retune") == 0) {
        if (!read_stdin_edid(input_edid)) {
            return 1;
        }
    }
    struct runtime_config config = {0};
    if (!load_config(&config)) {
        return 1;
    }
    int lock_descriptor = acquire_lock();
    if (lock_descriptor < 0) {
        return 1;
    }
    struct topology topology = {0};
    int result = 1;
    if (discover_topology(&config, &topology)) {
        if (strcmp(argv[1], "remove") == 0) {
            result = run_remove(&topology);
        } else if (strcmp(argv[1], "probe") == 0) {
            static const char *controls[] = {
                "edid_override", "force", "trigger_hotplug",
            };
            result = 0;
            for (size_t index = 0U;
                 index < sizeof(controls) / sizeof(controls[0]); ++index) {
                int descriptor = -1;
                if (!open_control(&topology, controls[index], &descriptor) ||
                    close(descriptor) != 0) {
                    result = 1;
                    break;
                }
            }
            if (result == 0) {
                printf("probe accepted for %s on %s (%s %s:%s, user %s/%lu)\n",
                       config.connector, topology.pci_slot, config.driver,
                       config.pci_vendor, config.pci_device,
                       config.desktop_user, config.desktop_uid);
            }
        } else {
            result = run_apply_or_retune(&topology, argv[1], input_edid);
        }
    }
    if (flock(lock_descriptor, LOCK_UN) != 0) {
        report_errno("cannot unlock", LOCK_PATH);
        result = 1;
    }
    if (close(lock_descriptor) != 0) {
        report_errno("cannot close lock", LOCK_PATH);
        result = 1;
    }
    return result;
}
