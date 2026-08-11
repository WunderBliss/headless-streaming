#define main headless_virtual_display_privileged_main
#include "../src/headless-virtual-display-root.c"
#undef main

int main(int argc, char **argv)
{
    if (argc != 2 && argc != 3) {
        return 2;
    }
    uint8_t buffer[EDID_SIZE + 1U] = {0};
    size_t length = 0;
    if (!read_bounded_file(argv[1], buffer, sizeof(buffer), &length) ||
        length != EDID_SIZE) {
        return 1;
    }
    if (argc == 3) {
        buffer[77] ^= 0x01U;
        buffer[127] = 0U;
        uint8_t sum = 0U;
        for (size_t index = 0; index < 127U; ++index) {
            sum = (uint8_t)(sum + buffer[index]);
        }
        buffer[127] = (uint8_t)(0U - sum);
    }
    return validate_edid(buffer) ? 0 : 1;
}
