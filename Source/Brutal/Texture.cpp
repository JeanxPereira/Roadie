#include <Brutal/Texture.h>

#include <Brutal/Install.h>

#include <cstring>

namespace Brutal::Texture {

using namespace Onyx;

namespace {

uint32_t U32(std::span<const std::byte> b, size_t at) {
    uint32_t v = 0;
    std::memcpy(&v, b.data() + at, 4);  // little-endian host, as the format
    return v;
}

void Report(Services::DiagSink& diags, const char* code, std::string message) {
    diags.Report({Services::Severity::Error, code, std::move(message), std::nullopt});
}

char Lower(char c) {
    return (c >= 'A' && c <= 'Z') ? char(c - 'A' + 'a') : c;
}

constexpr size_t kDdsHeader = 0x80;
constexpr uint32_t kMaxSide = 1u << 16;

std::string FourCc(uint32_t v) {
    std::string s;
    for (int i = 0; i < 4; ++i) {
        const char c = char((v >> (8 * i)) & 0xFF);
        s += (c >= 0x20 && c < 0x7F) ? c : '?';
    }
    return s;
}

std::string Hex(uint32_t v) {
    static const char* d = "0123456789abcdef";
    std::string s = "0000";
    for (int i = 0; i < 4; ++i) s[3 - i] = d[(v >> (4 * i)) & 15];
    return s;
}

uint8_t Expand5(uint32_t v) { return uint8_t(v << 3 | v >> 2); }
uint8_t Expand6(uint32_t v) { return uint8_t(v << 2 | v >> 4); }
uint8_t Expand4(uint32_t v) { return uint8_t(v * 17); }

uint32_t Fcc(const char* s) {
    uint32_t v;
    std::memcpy(&v, s, 4);
    return v;
}

}

std::optional<Info> ReadInfo(std::span<const std::byte> d) {
    if (d.size() < kHeaderSize) return std::nullopt;
    return Info{U32(d, 0x08), U32(d, 0x10), U32(d, 0x14), U32(d, 0x1C)};
}

bool IsRsaLight(std::string_view name) {
    constexpr std::string_view prefix = "lighting/textures/rsalights/";
    if (name.size() < prefix.size()) return false;
    for (size_t i = 0; i < prefix.size(); ++i) {
        char c = Lower(name[i]);
        if (c == '\\') c = '/';
        if (c != prefix[i]) return false;
    }
    return true;
}

std::optional<std::span<const std::byte>> Dds(std::span<const std::byte> d, Services::DiagSink& diags, std::string_view name) {
    if (d.size() < 0x2C || std::memcmp(d.data() + 0x20, "rtxT", 4) != 0 || std::memcmp(d.data() + 0x28, "DDS ", 4) != 0) {
        Report(diags, "bl.texture.magic", std::string(name) + ": not a Texture (rtxT at 0x20 and DDS at 0x28 expected)");
        return std::nullopt;
    }
    const uint64_t n = U32(d, 0x24);
    if (0x28 + n != d.size()) {
        Report(diags, "bl.texture.size", std::string(name) + ": DDS size " + std::to_string(n) + " vs payload " + std::to_string(d.size() - 0x28));
        return std::nullopt;
    }
    return d.subspan(0x28);
}

std::optional<Domain::Texture> ToImage(std::span<const std::byte> dds, std::string name, Services::DiagSink& diags) {
    if (dds.size() < kDdsHeader) {
        Report(diags, "bl.texture.size", name + ": DDS shorter than its 0x80-byte header");
        return std::nullopt;
    }
    const uint32_t height = U32(dds, 0x0C), width = U32(dds, 0x10);
    if (width == 0 || height == 0 || width > kMaxSide || height > kMaxSide) {
        Report(diags, "bl.texture.size", name + ": implausible size " + std::to_string(width) + "x" + std::to_string(height));
        return std::nullopt;
    }
    const uint32_t flags = U32(dds, 0x50), fourcc = U32(dds, 0x54), bits = U32(dds, 0x58);
    const uint32_t mr = U32(dds, 0x5C), mg = U32(dds, 0x60), mb = U32(dds, 0x64), ma = U32(dds, 0x68);
    const std::span<const std::byte> data = dds.subspan(kDdsHeader);

    Domain::Texture tex;
    tex.name = std::move(name);
    tex.width = width;
    tex.height = height;

    const bool hasFourCc = (flags & 0x4) != 0;
    if (hasFourCc && (fourcc == Fcc("DXT1") || fourcc == Fcc("DXT5"))) {
        tex.format = fourcc == Fcc("DXT1") ? Domain::PixelFormat::Bc1 : Domain::PixelFormat::Bc3;
        const size_t need = Domain::ExpectedByteSize(tex.format, width, height);
        if (data.size() < need) {
            Report(diags, "bl.texture.size", tex.name + ": top mip needs " + std::to_string(need) + " bytes, DDS holds " + std::to_string(data.size()));
            return std::nullopt;
        }
        tex.pixels.assign(data.begin(), data.begin() + std::ptrdiff_t(need));
        return tex;
    }

    const bool rgb565 = !hasFourCc && bits == 16 && mr == 0xF800 && mg == 0x07E0 && mb == 0x001F && ma == 0;
    const bool argb4444 = !hasFourCc && bits == 16 && mr == 0x0F00 && mg == 0x00F0 && mb == 0x000F && ma == 0xF000;
    if (!rgb565 && !argb4444) {
        Report(diags, "bl.texture.format",
               tex.name + ": unsupported pixel format " +
                   (hasFourCc ? "FourCC " + FourCc(fourcc)
                              : std::to_string(bits) + "-bit masks " + Hex(mr) + "/" + Hex(mg) + "/" + Hex(mb) + "/" + Hex(ma)));
        return std::nullopt;
    }
    tex.format = Domain::PixelFormat::Rgba8;
    const size_t count = size_t(width) * height;
    if (data.size() < count * 2) {
        Report(diags, "bl.texture.size", tex.name + ": top mip needs " + std::to_string(count * 2) + " bytes, DDS holds " + std::to_string(data.size()));
        return std::nullopt;
    }
    tex.pixels.resize(count * 4);
    for (size_t i = 0; i < count; ++i) {
        const uint32_t p = uint32_t(data[i * 2]) | uint32_t(data[i * 2 + 1]) << 8;
        uint8_t px[4];
        if (rgb565) {
            px[0] = Expand5(p >> 11);
            px[1] = Expand6((p >> 5) & 0x3F);
            px[2] = Expand5(p & 0x1F);
            px[3] = 255;
        } else {
            px[0] = Expand4((p >> 8) & 15);
            px[1] = Expand4((p >> 4) & 15);
            px[2] = Expand4(p & 15);
            px[3] = Expand4(p >> 12);
        }
        std::memcpy(tex.pixels.data() + i * 4, px, 4);
    }
    return tex;
}

std::optional<Domain::Texture> DecodeImage(Modules::DecodeContext& ctx) {
    const auto resource = UnpackEntry(ctx);
    if (!resource) return std::nullopt;
    const auto dds = Dds(*resource, ctx.diags, ctx.entry.name);
    if (!dds) return std::nullopt;
    return ToImage(*dds, ctx.entry.name, ctx.diags);
}

}
