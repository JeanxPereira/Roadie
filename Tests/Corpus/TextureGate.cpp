// Corpus gate for Texture resources, through the module: the install is opened by a Workspace with
// Brutal::Module and every bl.texture leaf is decoded the way a viewer does it, with the registry's
// DecodeImage on a DecodeContext built from the leaf. Replaces the Texture branch of
// Tests/corpus_rig_tex.py and proves at least its numbers on the Steam install:
//     Texture records 10,672, bl.rsalight leaves 16 (no image decoder, not DDS), DDS 10,656:
//     DXT5 5,405, DXT1 1,917, R5G6B5 1,667, A4R4G4B4 1,667, bad 0.
// Per texture: Dds() succeeds on the unpacked record, DecodeImage returns a valid image whose
// pixel byte size is ExpectedByteSize(format, w, h) and whose w/h equal ReadInfo's; the image
// format matches the DDS pixel format (Bc3, Bc1, Rgba8 for both 16-bit layouts).
// Per rsalight: the type has no image capability and is not a DDS (Dds() reports bl.texture.magic).
//
// Mutation (2026-11-03): in Source/Brutal/Texture.cpp Dds(), size check 0x28 + n -> 0x24 + n. The
// gate fails with dds-failed on all 10,656 DDS records (bl.texture.size) and the count-dds checks;
// reverting passes again.
#include "Corpus.h"

#include <Brutal/Install.h>
#include <Brutal/Texture.h>

#include <Onyx/Core/Modules/EntryAccess.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <string>
#include <tuple>
#include <vector>

namespace {

constexpr uint64_t kTextures = 10672, kRsaLights = 16, kDds = 10656, kDxt5 = 5405, kDxt1 = 1917, kR5G6B5 = 1667, kA4R4G4B4 = 1667;

uint32_t U32(std::span<const std::byte> b, size_t at) {
    uint32_t v = 0;
    std::memcpy(&v, b.data() + at, 4);
    return v;
}

// The DDS pixel format by its own fields: the name and the image format it must decode to.
struct Kind {
    const char* name;
    Onyx::Domain::PixelFormat image;
};

bool Classify(std::span<const std::byte> dds, Kind& out) {
    if (dds.size() < 0x80) return false;
    const uint32_t flags = U32(dds, 0x50), fourcc = U32(dds, 0x54), bits = U32(dds, 0x58);
    const uint32_t mr = U32(dds, 0x5C), mg = U32(dds, 0x60), mb = U32(dds, 0x64), ma = U32(dds, 0x68);
    uint32_t dxt1, dxt5;
    std::memcpy(&dxt1, "DXT1", 4);
    std::memcpy(&dxt5, "DXT5", 4);
    const bool cc = (flags & 0x4) != 0;
    if (cc && fourcc == dxt5) out = {"dxt5", Onyx::Domain::PixelFormat::Bc3};
    else if (cc && fourcc == dxt1) out = {"dxt1", Onyx::Domain::PixelFormat::Bc1};
    else if (!cc && bits == 16 && mr == 0xF800 && mg == 0x07E0 && mb == 0x001F && ma == 0) out = {"r5g6b5", Onyx::Domain::PixelFormat::Rgba8};
    else if (!cc && bits == 16 && mr == 0x0F00 && mg == 0x00F0 && mb == 0x000F && ma == 0xF000) out = {"a4r4g4b4", Onyx::Domain::PixelFormat::Rgba8};
    else return false;
    return true;
}

}

int main() {
    auto opened = Corpus::OpenInstall();
    if (!opened) return 1;
    Onyx::Modules::Document* doc = opened->ws.Get(opened->id);
    const auto install = std::static_pointer_cast<const Brutal::Install>(doc->moduleState);
    if (!install) {
        std::cerr << "the document holds no Brutal::Install\n";
        return 1;
    }

    std::map<std::string, uint64_t> counts, bad;
    std::map<std::string, std::string> examples;
    const auto fail = [&](const std::string& kind, const std::string& what) {
        ++bad[kind];
        examples.emplace(kind, what);
    };

    // Read in payload order: the tree order is alphabetical, which is random access on the disk.
    std::vector<const Onyx::Domain::AssetEntry*> leaves;
    Corpus::ForEachLeaf(*doc, [&](const Onyx::Domain::AssetEntry& leaf) { leaves.push_back(&leaf); });
    std::sort(leaves.begin(), leaves.end(), [](const auto* a, const auto* b) {
        return std::tie(a->source.fileIndex, a->source.offset) < std::tie(b->source.fileIndex, b->source.offset);
    });

    Onyx::Services::DiagSink readDiags, decodeDiags;
    Onyx::Services::Progress progress;
    for (const Onyx::Domain::AssetEntry* leafPtr : leaves) {
        const Onyx::Domain::AssetEntry& leaf = *leafPtr;
        const Brutal::RecordRef* ref = install->At(leaf.source);
        if (!ref) continue;
        const Brutal::Dfpf::Record& rec = install->RecordOf(*ref);
        if (rec.type != "Texture") continue;
        ++counts["texture"];
        const std::string path = rec.Path();

        const auto bytes = install->Read(*ref, readDiags);
        if (!bytes) {
            fail("read-failed", path);
            continue;
        }
        const auto info = Brutal::Texture::ReadInfo(*bytes);
        if (!info) {
            fail("no-info", path);
            continue;
        }

        if (Brutal::Texture::IsRsaLight(rec.name)) {
            ++counts["rsalight"];
            if (opened->ws.Decoders().Of(leaf.type).image) fail("rsalight-has-image-decoder", path);
            Onyx::Services::DiagSink probe;
            if (Brutal::Texture::Dds(*bytes, probe, path)) fail("rsalight-is-dds", path);
            continue;
        }

        const auto dds = Brutal::Texture::Dds(*bytes, decodeDiags, path);
        if (!dds) {
            fail("dds-failed", path);
            continue;
        }
        ++counts["dds"];
        Kind kind{};
        if (!Classify(*dds, kind)) {
            fail("unknown-format", path);
            continue;
        }
        ++counts[kind.name];

        if (!opened->ws.Decoders().Of(leaf.type).image) {
            fail("no-image-decoder", path);
            continue;
        }
        auto reader = Onyx::Modules::ReaderOf(*doc, leaf);
        if (!reader) {
            fail("no-reader", path);
            continue;
        }
        Onyx::Modules::DecodeContext ctx{doc, leaf, std::move(*reader), decodeDiags, progress, opened->ws.Settings(), doc->moduleState};
        const auto image = opened->ws.Decoders().DecodeImage(ctx);
        if (!image) {
            fail("decode-failed", path);
            continue;
        }
        if (!image->IsValid()) fail("invalid-image", path);
        if (image->width != info->width || image->height != info->height) {
            fail("size-vs-header", path + ": " + std::to_string(image->width) + "x" + std::to_string(image->height) + " vs " +
                                       std::to_string(info->width) + "x" + std::to_string(info->height));
        }
        const size_t want = Onyx::Domain::ExpectedByteSize(image->format, image->width, image->height);
        if (image->pixels.size() != want) {
            fail("byte-size", path + ": " + std::to_string(image->pixels.size()) + " vs " + std::to_string(want));
        }
        if (image->format != kind.image) fail("image-format", path + ": " + kind.name);
    }

    for (const auto& d : readDiags.Snapshot()) {
        if (d.severity == Onyx::Services::Severity::Error) fail("read-diagnostic", d.code + ": " + d.message);
    }
    for (const auto& d : decodeDiags.Snapshot()) {
        if (d.severity == Onyx::Services::Severity::Error) fail("decode-diagnostic", d.code + ": " + d.message);
    }

    const auto expect = [&](const char* key, uint64_t want) {
        if (counts[key] != want) fail(std::string("count-") + key, std::to_string(counts[key]) + " vs " + std::to_string(want));
    };
    expect("texture", kTextures);
    expect("rsalight", kRsaLights);
    expect("dds", kDds);
    expect("dxt5", kDxt5);
    expect("dxt1", kDxt1);
    expect("r5g6b5", kR5G6B5);
    expect("a4r4g4b4", kA4R4G4B4);
    return Corpus::Verdict(counts, bad, examples);
}
