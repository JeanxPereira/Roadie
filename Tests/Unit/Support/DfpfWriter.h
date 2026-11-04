#pragma once

#include <Brutal/Dfpf.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace Brutal::Tests {

// A directory of its own under the system temp root, removed on destruction.
class TempDir {
public:
    explicit TempDir(const std::string& tag);
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;
    ~TempDir();
    const std::filesystem::path& path() const { return m_path; }
    std::filesystem::path operator/(const std::string& name) const { return m_path / name; }

private:
    std::filesystem::path m_path;
};

// One resource of a bundle. `unpacked` is header part + data part (headerSize bytes, then the rest).
struct Item {
    std::string name;  // "characters/bipeds/x"
    std::string type;  // "Mesh"
    std::vector<std::byte> unpacked;
    uint32_t headerSize = 0;
    Dfpf::Compression compression = Dfpf::Compression::Raw;

    // Knobs to break the bundle; each replaces what the writer would have stored.
    bool corruptStream = false;  // flip bytes inside the stored (zlib) stream
    std::optional<uint64_t> offset;
    std::optional<uint32_t> storedSize, dataSize, headerSizeField;
};

struct BundleSpec {
    std::string name;                // "a" -> a.~h / a.~p
    std::vector<std::string> types;  // type table order; item types missing here are appended
    std::vector<Item> items;
};

// The inverse of the record bitfields in Brutal/Dfpf.h.
std::array<uint8_t, 16> PackRecord(uint32_t dataSize, uint32_t nameOffset, uint32_t headerSize, uint64_t offset,
                                   uint32_t storedSize, uint32_t typeIndex, uint8_t compression);

// Writes <dir>/<name>.~h and <dir>/<name>.~p and returns the header path.
std::filesystem::path WriteBundle(const std::filesystem::path& dir, const BundleSpec& spec);

// Deterministic bytes: byte i is (seed + i * 7) & 0xFF.
std::vector<std::byte> Pattern(size_t n, uint8_t seed);

}
