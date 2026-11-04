#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace Brutal::Tests {

// Builds the bytes of a Texture resource: 0x24-byte header part, u32 DDS size, a DDS.
struct TextureSpec {
    uint32_t engineFormat = 9;
    uint32_t width = 4, height = 4, mips = 1;
    std::string fourcc;                              // "DXT1"; empty = uncompressed
    uint32_t bits = 16, mr = 0, mg = 0, mb = 0, ma = 0;
    std::vector<std::byte> data;                     // everything after the 0x80-byte DDS header
};

inline void PutU32(std::vector<std::byte>& v, size_t at, uint32_t x) {
    std::memcpy(v.data() + at, &x, 4);
}

inline std::vector<std::byte> DdsBytes(const TextureSpec& s) {
    std::vector<std::byte> d(0x80);
    std::memcpy(d.data(), "DDS ", 4);
    PutU32(d, 0x04, 124);
    PutU32(d, 0x08, 0x08);
    PutU32(d, 0x0C, s.height);
    PutU32(d, 0x10, s.width);
    PutU32(d, 0x1C, s.mips);
    PutU32(d, 0x4C, 32);
    if (!s.fourcc.empty()) {
        PutU32(d, 0x50, 0x4);
        std::memcpy(d.data() + 0x54, s.fourcc.data(), 4);
    } else {
        PutU32(d, 0x50, s.ma ? 0x41 : 0x40);
        PutU32(d, 0x58, s.bits);
        PutU32(d, 0x5C, s.mr);
        PutU32(d, 0x60, s.mg);
        PutU32(d, 0x64, s.mb);
        PutU32(d, 0x68, s.ma);
    }
    d.insert(d.end(), s.data.begin(), s.data.end());
    return d;
}

// `sizeDelta` corrupts the DDS size field to test the size check.
inline std::vector<std::byte> TextureBytes(const TextureSpec& s, int sizeDelta = 0) {
    const std::vector<std::byte> dds = DdsBytes(s);
    std::vector<std::byte> r(0x28);
    PutU32(r, 0x08, s.engineFormat);
    PutU32(r, 0x10, s.width);
    PutU32(r, 0x14, s.height);
    PutU32(r, 0x1C, s.mips);
    std::memcpy(r.data() + 0x20, "rtxT", 4);
    PutU32(r, 0x24, uint32_t(int64_t(dds.size()) + sizeDelta));
    r.insert(r.end(), dds.begin(), dds.end());
    std::memcpy(r.data() + 0x28, "DDS ", 4);
    return r;
}

}
