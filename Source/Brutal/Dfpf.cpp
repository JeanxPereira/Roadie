// The format facts live in Brutal/Dfpf.h.
#include <Brutal/Dfpf.h>

#include <zlib.h>

#include <algorithm>
#include <cstring>

namespace Brutal::Dfpf {

using namespace Onyx;

namespace {

Error Fail(const char* code, std::string message) {
    return Error{code, std::move(message), 0};
}

uint32_t Be32(const std::vector<std::byte>& b, uint64_t o) {
    return (uint32_t(uint8_t(b[o])) << 24) | (uint32_t(uint8_t(b[o + 1])) << 16) |
           (uint32_t(uint8_t(b[o + 2])) << 8) | uint32_t(uint8_t(b[o + 3]));
}

uint64_t Be64(const std::vector<std::byte>& b, uint64_t o) {
    return (uint64_t(Be32(b, o)) << 32) | Be32(b, o + 4);
}

void AppendLatin1(std::string& out, const std::byte* p, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        const auto c = uint8_t(p[i]);
        if (c < 0x80) {
            out.push_back(char(c));
        } else {
            out.push_back(char(0xC0 | (c >> 6)));
            out.push_back(char(0x80 | (c & 0x3F)));
        }
    }
}

bool IsSpace(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f';
}

// Python: .strip().rstrip("\0")
std::string TrimTypeName(std::string s) {
    while (!s.empty() && IsSpace(s.back())) s.pop_back();
    size_t b = 0;
    while (b < s.size() && IsSpace(s[b])) ++b;
    s.erase(0, b);
    while (!s.empty() && s.back() == '\0') s.pop_back();
    return s;
}

}

Result<Bundle> ParseHeader(Vfs::Reader& header, const std::filesystem::path& headerPath) {
    const std::string where = headerPath.filename().string();
    header.Seek(0);
    const std::vector<std::byte> h = header.ReadAll();
    if (h.size() < 5 || std::memcmp(h.data(), "dfpf", 4) != 0) {
        return Result<Bundle>::Fail(Fail("bl.dfpf.magic", where + ": not a DFPF bundle"));
    }
    if (uint8_t(h[4]) != 5) {
        return Result<Bundle>::Fail(Fail("bl.dfpf.version", where + ": DFPF v" + std::to_string(uint8_t(h[4])) +
                                                               " unsupported (Brutal Legend is v5)"));
    }
    const auto truncated = [&](const std::string& what) {
        return Result<Bundle>::Fail(Fail("bl.dfpf.truncated", where + ": " + what));
    };
    if (h.size() < 0x40) return truncated("header shorter than the fixed fields");

    const uint64_t typeOff = Be64(h, 0x08);
    const uint64_t nameOff = Be64(h, 0x10);
    const uint32_t typeCount = Be32(h, 0x18);
    const uint32_t count = Be32(h, 0x20);
    const uint64_t recOff = Be64(h, 0x38);
    const uint64_t size = h.size();

    // Every type entry is at least 4 + 12 bytes, every record 16: reject counts the file cannot hold.
    if (typeOff > size || uint64_t(typeCount) * 16 > size - typeOff) return truncated("type table past the end");
    if (recOff > size || uint64_t(count) * 16 > size - recOff) return truncated("record table past the end");
    if (nameOff > size) return truncated("name directory past the end");

    std::vector<std::string> types;
    types.reserve(typeCount);
    uint64_t o = typeOff;
    for (uint32_t i = 0; i < typeCount; ++i) {
        if (o + 4 > size) return truncated("type table entry past the end");
        const uint64_t n = Be32(h, o);
        if (o + 4 + n + 12 > size) return truncated("type table entry past the end");
        std::string t;
        AppendLatin1(t, h.data() + o + 4, size_t(n));
        types.push_back(TrimTypeName(std::move(t)));
        o += 4 + n + 12;
    }

    Bundle bundle;
    bundle.headerPath = headerPath;
    bundle.payloadPath = headerPath;
    bundle.payloadPath.replace_extension(".~p");
    bundle.name = headerPath.stem().string();
    bundle.records.reserve(count);
    for (uint32_t i = 0; i < count; ++i) {
        const uint64_t r = recOff + uint64_t(i) * 16;
        Record rec;
        rec.index = i;
        rec.dataSize = Be32(h, r) >> 8;
        const uint32_t nameRel = Be32(h, r + 3) >> 11;
        rec.headerSize = (Be32(h, r + 4) >> 1) & 0x3FFFF;
        rec.offset = Be32(h, r + 8) >> 3;
        rec.storedSize = (Be32(h, r + 11) << 5) >> 9;
        const uint32_t tidx = (((uint32_t(uint8_t(h[r + 14])) & 15) << 4) | (uint8_t(h[r + 15]) >> 4)) >> 1;
        rec.compression = Compression(uint8_t(h[r + 15]) & 15);
        if (tidx >= types.size()) {
            return truncated("record " + std::to_string(i) + " names type " + std::to_string(tidx) + " of " +
                             std::to_string(types.size()));
        }
        rec.type = types[tidx];

        const uint64_t nameAt = nameOff + nameRel;
        if (nameAt >= size) return truncated("record " + std::to_string(i) + " name past the end");
        const auto begin = h.begin() + static_cast<std::ptrdiff_t>(nameAt);
        const auto nul = std::find(begin, h.end(), std::byte{0});
        if (nul == h.end()) return truncated("record " + std::to_string(i) + " name unterminated");
        AppendLatin1(rec.name, &*begin, size_t(nul - begin));
        bundle.records.push_back(std::move(rec));
    }
    return Result<Bundle>::Ok(std::move(bundle));
}

std::optional<std::vector<std::byte>> Unpack(const Record& record, std::span<const std::byte> stored,
                                             Services::DiagSink& diags) {
    const auto report = [&](const char* code, const std::string& why) {
        diags.Report({Services::Severity::Error, code, record.Path() + ": " + why, std::nullopt});
    };
    const uint64_t want = record.UnpackedSize();
    switch (record.compression) {
        case Compression::Raw:
            if (stored.size() != want) {
                report("bl.dfpf.inflate",
                       "raw payload is " + std::to_string(stored.size()) + " bytes, expected " + std::to_string(want));
                return std::nullopt;
            }
            return std::vector<std::byte>(stored.begin(), stored.end());
        case Compression::Zlib: {
            std::vector<std::byte> out(static_cast<size_t>(want));
            z_stream zs{};
            if (inflateInit(&zs) != Z_OK) {
                report("bl.dfpf.inflate", "inflateInit failed");
                return std::nullopt;
            }
            zs.next_in = reinterpret_cast<Bytef*>(const_cast<std::byte*>(stored.data()));
            zs.avail_in = uInt(stored.size());
            zs.next_out = reinterpret_cast<Bytef*>(out.data());
            zs.avail_out = uInt(out.size());
            const int rc = inflate(&zs, Z_FINISH);
            const uint64_t produced = zs.total_out;
            inflateEnd(&zs);
            if (rc != Z_STREAM_END || produced != want) {
                report("bl.dfpf.inflate", "zlib stream did not inflate to " + std::to_string(want) + " bytes");
                return std::nullopt;
            }
            return out;
        }
        case Compression::Xmem:
            report("bl.dfpf.xmem", "XMemCompress payloads only appear in Xbox 360 bundles");
            return std::nullopt;
    }
    report("bl.dfpf.inflate", "unknown compression " + std::to_string(uint8_t(record.compression)));
    return std::nullopt;
}

}
