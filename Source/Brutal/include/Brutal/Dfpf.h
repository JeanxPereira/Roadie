#pragma once

#include <Onyx/Core/Result.h>
#include <Onyx/Core/Services/Diagnostics.h>
#include <Onyx/Core/Vfs/Reader.h>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <span>
#include <string>
#include <vector>

// DFPF v5 bundles: Brutal Legend's `.~h` (header) + `.~p` (payload) pairs. The facts below are the
// layout block of the Python decoder (Blender/BrutalLegend/Brutal/dfpf.py); the gate is the corpus
// gate Tests/Corpus/DfpfGate.cpp (71,095 records over the 21 bundles of the Steam install).
//
// Layout (big-endian on PC too; the magic is stored as "dfpf"):
//     0x00  "dfpf"
//     0x04  u8   version (5)
//     0x08  u64  type table offset
//     0x10  u64  name directory offset
//     0x18  u32  type count
//     0x1C  u32  name directory size (not used to bound name reads, as in the Python decoder)
//     0x20  u32  file count
//     0x38  u64  file record table offset (16 bytes per record)
// Type table entry: u32 length, char[length], u8[12] (unknown); the name is trimmed of white space
// and trailing NULs. Names: NUL-terminated latin-1 at name directory + name offset.
//
// Record bitfields (16 bytes, big-endian). Base: the DoubleFine Explorer V5 reader
// (uDFExplorer_PAKManager), corrected: its "uncompressed size" is only the data part.
//     bytes 0..3   BE u32 >> 8              data size (24 bits)
//     bytes 3..6   BE u32 >> 11             name offset (21 bits)
//     bytes 4..7   (BE u32 >> 1) & 0x3FFFF  header size (18 bits), the CPU-side part that precedes
//                                           the data; unpacked = header + data
//     bytes 8..11  BE u32 >> 3              payload offset (29 bits)
//     bytes 11..14 (BE u32 << 5) >> 9       stored size (23 bits)
//     bytes 14..17 ((BE u32 << 4) >> 24) >> 1  type index (only bytes 14 and 15 contribute)
//     byte 15 & 15                          compression: 4 raw, 8 zlib, 12 xmem
//
// Unpacking (fact, stricter than the Python decoder, which checks no sizes): a raw payload is
// exactly header + data bytes and a zlib stream inflates to exactly header + data bytes, for all
// 71,095 records of the Steam install. Gate: Tests/Corpus/DfpfGate.cpp. Xmem appears
// only in Xbox 360 bundles and is not decoded.
namespace Brutal::Dfpf {

enum class Compression : uint8_t { Raw = 4, Zlib = 8, Xmem = 12 };

struct Record {
    uint32_t index = 0;
    std::string name;
    std::string type;
    uint64_t offset = 0;
    uint32_t storedSize = 0;
    uint32_t dataSize = 0;
    uint32_t headerSize = 0;
    Compression compression = Compression::Raw;

    uint64_t UnpackedSize() const { return uint64_t(headerSize) + dataSize; }
    std::string Path() const { return name + "." + type; }
};

struct Bundle {
    std::string name;
    std::filesystem::path headerPath, payloadPath;
    std::vector<Record> records;
};

// Fails with bl.dfpf.magic, bl.dfpf.version or bl.dfpf.truncated.
Onyx::Result<Bundle> ParseHeader(Onyx::Vfs::Reader& header, const std::filesystem::path& headerPath);

// Reports bl.dfpf.inflate / bl.dfpf.xmem and returns nothing on failure.
std::optional<std::vector<std::byte>> Unpack(const Record& record, std::span<const std::byte> stored,
                                             Onyx::Services::DiagSink& diags);

}
