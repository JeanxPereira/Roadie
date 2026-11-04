#pragma once

#include <Onyx/Core/Domain/Texture.h>
#include <Onyx/Core/Modules/DecodeContext.h>
#include <Onyx/Core/Services/Diagnostics.h>

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <string_view>

// Texture resources. Record header part = 0x24 bytes, data part = u32 size + a complete DDS. The
// facts are the docstring of Blender/BrutalLegend/Brutal/texture.py plus the 16-bit formats; the
// gate is Tests/Corpus/TextureGate.cpp: 10,672 records, 16 rsalights, 10,656 DDS.
//
//     0x08  u32 engine format (9 DXT1, 11 DXT5, 5 R5G6B5, 2 A4R4G4B4)
//     0x10  u32 width
//     0x14  u32 height
//     0x1C  u32 mip count
//     0x20  'rtxT'                (IDA sub_64E170)
//     0x24  u32 DDS size          <- data part starts here; 0x28 + size == resource size
//     0x28  'DDS ' ...
//
// DDS (offsets inside the DDS): height 0x0C, width 0x10, mip count 0x1C, pixel format at 0x4C
// (size, flags 0x50, FourCC 0x54, RGB bit count 0x58, masks R 0x5C, G 0x60, B 0x64, A 0x68); the
// top mip starts at 0x80 and the smaller mips follow it.
//
// Measured over the Steam install (2026-11-03): DXT5 5,405 (3,663 with mips), DXT1 1,917,
// uncompressed R5G6B5 1,667 (engine format 5, masks f800/07e0/001f), uncompressed A4R4G4B4 1,667
// (engine format 2, masks 0f00/00f0/000f/f000). Both 16-bit sets are under worlds/.
//
// Normal maps are DXT5nm: X in alpha, Y in green, Z rebuilt (shown as stored here). The 16
// lighting/textures/rsalights/* records use a different 0xB0-byte header and are baked light data,
// not DDS; they stay Raw.
//
// The viewer shows the top mip only. 16-bit pixels expand by bit replication (5 bits v<<3|v>>2,
// 6 bits v<<2|v>>4, 4 bits v*17); R5G6B5 has alpha 255.
namespace Brutal::Texture {

constexpr size_t kHeaderSize = 0x24;

struct Info {
    uint32_t engineFormat = 0, width = 0, height = 0, mips = 0;
};

// The header-part fields; nullopt when the resource is shorter than the header part.
std::optional<Info> ReadInfo(std::span<const std::byte> resource);

// lighting/textures/rsalights/* (case and slash insensitive); the name may carry ".Texture".
bool IsRsaLight(std::string_view resourceName);

// The complete DDS of a resource. Reports bl.texture.magic and bl.texture.size.
std::optional<std::span<const std::byte>> Dds(std::span<const std::byte> resource, Onyx::Services::DiagSink& diags,
                                              std::string_view name);

// The top mip as an Onyx image. Reports bl.texture.format for anything but DXT1, DXT5 and the two
// 16-bit layouts, and bl.texture.size when the DDS is shorter than its header says.
std::optional<Onyx::Domain::Texture> ToImage(std::span<const std::byte> dds, std::string name, Onyx::Services::DiagSink& diags);

// Registered on bl.texture.
std::optional<Onyx::Domain::Texture> DecodeImage(Onyx::Modules::DecodeContext& ctx);

}
