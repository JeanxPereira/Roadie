#include "DfpfWriter.h"

#include <zlib.h>

#include <atomic>
#include <fstream>
#include <process.h>
#include <stdexcept>

namespace Brutal::Tests {

TempDir::TempDir(const std::string& tag) {
    static std::atomic<uint32_t> counter{0};
    m_path = std::filesystem::temp_directory_path() /
             ("roadie-" + tag + "-" + std::to_string(_getpid()) + "-" + std::to_string(counter.fetch_add(1)));
    std::error_code ec;
    std::filesystem::remove_all(m_path, ec);
    std::filesystem::create_directories(m_path);
}

TempDir::~TempDir() {
    std::error_code ec;
    std::filesystem::remove_all(m_path, ec);
}

namespace {

// Bit 0 is the most significant bit of byte 0, as the record bitfields count.
void SetBits(std::array<uint8_t, 16>& rec, unsigned start, unsigned width, uint64_t value) {
    if (width < 64 && (value >> width) != 0) throw std::invalid_argument("value wider than its bit field");
    for (unsigned i = 0; i < width; ++i) {
        const unsigned bit = start + i;
        const bool on = (value >> (width - 1 - i)) & 1;
        if (on) rec[bit / 8] |= uint8_t(0x80 >> (bit % 8));
    }
}

void PutBe(std::vector<std::byte>& out, uint64_t v, int bytes) {
    for (int i = bytes - 1; i >= 0; --i) out.push_back(std::byte((v >> (8 * i)) & 0xFF));
}

void PutAt(std::vector<std::byte>& out, size_t at, uint64_t v, int bytes) {
    for (int i = 0; i < bytes; ++i) out[at + size_t(i)] = std::byte((v >> (8 * (bytes - 1 - i))) & 0xFF);
}

}

std::array<uint8_t, 16> PackRecord(uint32_t dataSize, uint32_t nameOffset, uint32_t headerSize, uint64_t offset,
                                   uint32_t storedSize, uint32_t typeIndex, uint8_t compression) {
    std::array<uint8_t, 16> rec{};
    SetBits(rec, 0, 24, dataSize);        // bytes 0..3 >> 8
    SetBits(rec, 24, 21, nameOffset);     // bytes 3..6 >> 11
    SetBits(rec, 45, 18, headerSize);     // bytes 4..7 (>> 1) & 0x3FFFF
    SetBits(rec, 64, 29, offset);         // bytes 8..11 >> 3
    SetBits(rec, 93, 23, storedSize);     // bytes 11..14 (<< 5) >> 9
    SetBits(rec, 116, 7, typeIndex);      // bytes 14..17 ((<< 4) >> 24) >> 1
    SetBits(rec, 124, 4, compression);    // byte 15 & 15
    return rec;
}

std::vector<std::byte> Pattern(size_t n, uint8_t seed) {
    std::vector<std::byte> out(n);
    for (size_t i = 0; i < n; ++i) out[i] = std::byte((seed + i * 7) & 0xFF);
    return out;
}

std::filesystem::path WriteBundle(const std::filesystem::path& dir, const BundleSpec& spec) {
    std::vector<std::string> types = spec.types;
    const auto typeIndex = [&](const std::string& t) {
        for (size_t i = 0; i < types.size(); ++i) {
            if (types[i] == t) return uint32_t(i);
        }
        types.push_back(t);
        return uint32_t(types.size() - 1);
    };
    std::vector<uint32_t> tidx;
    for (const Item& it : spec.items) tidx.push_back(typeIndex(it.type));

    // Payload and name directory.
    std::vector<std::byte> payload, names;
    std::vector<std::array<uint8_t, 16>> records;
    for (size_t i = 0; i < spec.items.size(); ++i) {
        const Item& it = spec.items[i];
        if (it.headerSize > it.unpacked.size()) throw std::invalid_argument("headerSize past the item");
        std::vector<std::byte> stored = it.unpacked;
        if (it.compression == Dfpf::Compression::Zlib) {
            uLongf n = compressBound(uLong(it.unpacked.size()));
            stored.resize(n);
            if (compress2(reinterpret_cast<Bytef*>(stored.data()), &n, reinterpret_cast<const Bytef*>(it.unpacked.data()),
                          uLong(it.unpacked.size()), 6) != Z_OK) {
                throw std::runtime_error("compress2 failed");
            }
            stored.resize(n);
            if (it.corruptStream) {
                for (size_t k = 2; k < stored.size(); k += 3) stored[k] ^= std::byte{0xA5};
            }
        }
        const uint64_t offset = it.offset.value_or(payload.size());
        const uint32_t nameRel = uint32_t(names.size());
        for (char c : it.name) names.push_back(std::byte(c));
        names.push_back(std::byte{0});
        records.push_back(PackRecord(it.dataSize.value_or(uint32_t(it.unpacked.size() - it.headerSize)), nameRel,
                                     it.headerSizeField.value_or(it.headerSize), offset,
                                     it.storedSize.value_or(uint32_t(stored.size())), tidx[i], uint8_t(it.compression)));
        payload.insert(payload.end(), stored.begin(), stored.end());
    }

    // Header: fixed fields, type table, name directory, record table.
    std::vector<std::byte> h(0x40, std::byte{0});
    h[0] = std::byte{'d'}; h[1] = std::byte{'f'}; h[2] = std::byte{'p'}; h[3] = std::byte{'f'};
    h[4] = std::byte{5};
    const uint64_t typeOff = h.size();
    for (const std::string& t : types) {
        PutBe(h, t.size(), 4);
        for (char c : t) h.push_back(std::byte(c));
        for (int i = 0; i < 12; ++i) h.push_back(std::byte{0});
    }
    const uint64_t nameOff = h.size();
    h.insert(h.end(), names.begin(), names.end());
    const uint64_t recOff = h.size();
    for (const auto& r : records) {
        for (uint8_t b : r) h.push_back(std::byte(b));
    }
    PutAt(h, 0x08, typeOff, 8);
    PutAt(h, 0x10, nameOff, 8);
    PutAt(h, 0x18, types.size(), 4);
    PutAt(h, 0x1C, names.size(), 4);
    PutAt(h, 0x20, records.size(), 4);
    PutAt(h, 0x38, recOff, 8);

    const auto save = [](const std::filesystem::path& p, const std::vector<std::byte>& bytes) {
        std::ofstream f(p, std::ios::binary);
        f.write(reinterpret_cast<const char*>(bytes.data()), std::streamsize(bytes.size()));
    };
    save(dir / (spec.name + ".~h"), h);
    save(dir / (spec.name + ".~p"), payload);
    return dir / (spec.name + ".~h");
}

}
