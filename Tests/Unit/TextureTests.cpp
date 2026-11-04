#include <doctest/doctest.h>

#include "Support/DfpfWriter.h"
#include "Support/TextureWriter.h"

#include <Brutal/Module.h>
#include <Brutal/Texture.h>

#include <Onyx/Core/Modules/Workspace.h>

#include <algorithm>
#include <memory>
#include <string>

using namespace Brutal;
using namespace Brutal::Tests;
using Onyx::Domain::PixelFormat;
using Onyx::Modules::Document;

namespace {

struct Opened {
    TempDir dir;
    std::unique_ptr<Onyx::Modules::Workspace> ws;
    Document* doc = nullptr;
    Opened(const std::string& tag, std::vector<Item> items) : dir(tag) {
        const auto header = WriteBundle(dir.path(), {"a", {}, std::move(items)});
        ws = std::make_unique<Onyx::Modules::Workspace>();
        REQUIRE(ws->AddModule(std::make_unique<Module>()).ok());
        const auto id = ws->Open(header);
        REQUIRE(id != 0);
        doc = ws->Get(id);
        REQUIRE(doc);
    }
};

Item TextureItem(const std::string& name, std::vector<std::byte> bytes) {
    Item it;
    it.name = name;
    it.type = "Texture";
    it.unpacked = std::move(bytes);
    it.headerSize = uint32_t(Texture::kHeaderSize);
    it.compression = Dfpf::Compression::Zlib;
    return it;
}

const Onyx::Domain::AssetEntry* Find(const std::vector<Onyx::Domain::AssetEntry>& level, const std::string& path) {
    const size_t slash = path.find('/');
    for (const auto& e : level) {
        if (slash == std::string::npos ? e.name == path : e.name == path.substr(0, slash)) {
            return slash == std::string::npos ? &e : Find(e.children, path.substr(slash + 1));
        }
    }
    return nullptr;
}

std::optional<Onyx::Domain::Texture> Decode(Opened& o, const std::string& path) {
    const auto* entry = Find(o.doc->roots, path);
    REQUIRE(entry);
    Onyx::Services::Progress progress;
    Onyx::Modules::DecodeContext ctx{o.doc, *entry, Onyx::Vfs::Reader(o.doc->files[entry->source.fileIndex], entry->source.offset, entry->source.size),
                                     o.doc->diags, progress, o.ws->Settings(), o.doc->moduleState};
    return o.ws->Decoders().DecodeImage(ctx);
}

size_t Count(const Onyx::Services::DiagSink& d, const std::string& code) {
    size_t n = 0;
    for (const auto& x : d.Snapshot()) n += x.code == code;
    return n;
}

std::vector<std::byte> Pixels(std::initializer_list<uint16_t> px) {
    std::vector<std::byte> v;
    for (uint16_t p : px) {
        v.push_back(std::byte(p & 0xFF));
        v.push_back(std::byte(p >> 8));
    }
    return v;
}

Onyx::Domain::Texture Convert(const TextureSpec& s) {
    Onyx::Services::DiagSink diags;
    auto t = Texture::ToImage(DdsBytes(s), "t", diags);
    REQUIRE(t);
    CHECK(diags.Count() == 0);
    return *t;
}

void ExpectPixel(const Onyx::Domain::Texture& t, size_t i, uint8_t r, uint8_t g, uint8_t b, uint8_t a) {
    REQUIRE(t.pixels.size() >= i * 4 + 4);
    CHECK(uint8_t(t.pixels[i * 4]) == r);
    CHECK(uint8_t(t.pixels[i * 4 + 1]) == g);
    CHECK(uint8_t(t.pixels[i * 4 + 2]) == b);
    CHECK(uint8_t(t.pixels[i * 4 + 3]) == a);
}

}

TEST_CASE("DxtTopMip") {
    struct Case { const char* fourcc; PixelFormat fmt; size_t block; };
    for (const Case& c : {Case{"DXT1", PixelFormat::Bc1, 8}, Case{"DXT5", PixelFormat::Bc3, 16}}) {
        TextureSpec s;
        s.fourcc = c.fourcc;
        s.width = s.height = 8;
        s.mips = 3;
        s.data = Pattern(c.block * (4 + 1 + 1), 11);  // 8x8, 4x4, 2x2
        const auto t = Convert(s);
        CHECK(t.format == c.fmt);
        CHECK(t.width == 8);
        CHECK(t.height == 8);
        CHECK(t.pixels.size() == Onyx::Domain::ExpectedByteSize(c.fmt, 8, 8));
        CHECK(t.pixels.size() == c.block * 4);
        CHECK(std::equal(t.pixels.begin(), t.pixels.end(), s.data.begin()));
        CHECK(t.IsValid());
    }
}

TEST_CASE("Rgb565Expands") {
    TextureSpec s;
    s.width = 3;
    s.height = 1;
    s.mr = 0xF800; s.mg = 0x07E0; s.mb = 0x001F;
    s.data = Pixels({0xF800, 0x07E0, 0x001F});
    const auto t = Convert(s);
    CHECK(t.format == PixelFormat::Rgba8);
    CHECK(t.IsValid());
    ExpectPixel(t, 0, 255, 0, 0, 255);
    ExpectPixel(t, 1, 0, 255, 0, 255);
    ExpectPixel(t, 2, 0, 0, 255, 255);
}

TEST_CASE("Argb4444Expands") {
    TextureSpec s;
    s.width = 5;
    s.height = 1;
    s.mr = 0x0F00; s.mg = 0x00F0; s.mb = 0x000F; s.ma = 0xF000;
    s.data = Pixels({0x0F00, 0x00F0, 0x000F, 0xF000, 0x8421});
    const auto t = Convert(s);
    CHECK(t.IsValid());
    ExpectPixel(t, 0, 255, 0, 0, 0);
    ExpectPixel(t, 1, 0, 255, 0, 0);
    ExpectPixel(t, 2, 0, 0, 255, 0);
    ExpectPixel(t, 3, 0, 0, 0, 255);
    ExpectPixel(t, 4, 68, 34, 17, 136);
}

TEST_CASE("SizeMismatch") {
    TextureSpec s;
    s.fourcc = "DXT1";
    s.data = Pattern(8, 1);
    Onyx::Services::DiagSink diags;
    const auto good = TextureBytes(s);
    CHECK(Texture::Dds(good, diags, "t"));
    CHECK(diags.Count() == 0);
    for (int delta : {1, -1}) {
        const auto bad = TextureBytes(s, delta);
        CHECK_FALSE(Texture::Dds(bad, diags, "t"));
    }
    CHECK(Count(diags, "bl.texture.size") == 2);

    auto noMagic = good;
    noMagic[0x20] = std::byte{'x'};
    CHECK_FALSE(Texture::Dds(noMagic, diags, "t"));
    CHECK(Count(diags, "bl.texture.magic") == 1);

    // through the decoder: the entry yields no image
    Opened o("texsize", {TextureItem("t", TextureBytes(s, 4))});
    CHECK_FALSE(Decode(o, "t.Texture"));
    CHECK(Count(o.doc->diags, "bl.texture.size") == 1);
}

TEST_CASE("UnknownFormat") {
    TextureSpec s;
    s.fourcc = "ATI2";
    s.data = Pattern(16, 1);
    Onyx::Services::DiagSink diags;
    CHECK_FALSE(Texture::ToImage(DdsBytes(s), "t", diags));
    REQUIRE(Count(diags, "bl.texture.format") == 1);
    CHECK(diags.Snapshot()[0].message.find("ATI2") != std::string::npos);

    TextureSpec m;  // 16-bit with masks outside the two measured layouts
    m.mr = 0x7C00; m.mg = 0x03E0; m.mb = 0x001F;
    m.data = Pixels({0});
    m.width = m.height = 1;
    Onyx::Services::DiagSink d2;
    CHECK_FALSE(Texture::ToImage(DdsBytes(m), "t", d2));
    REQUIRE(Count(d2, "bl.texture.format") == 1);
    CHECK(d2.Snapshot()[0].message.find("7c00") != std::string::npos);
}

TEST_CASE("RsaLightIsRaw") {
    CHECK(Texture::IsRsaLight("lighting/textures/rsalights/x"));
    CHECK(Texture::IsRsaLight("Lighting\\Textures\\RsaLights\\x.Texture"));
    CHECK_FALSE(Texture::IsRsaLight("lighting/textures/other/x"));
    CHECK_FALSE(Texture::IsRsaLight("worlds/w/x"));

    TextureSpec s;
    s.fourcc = "DXT1";
    s.data = Pattern(8, 1);
    Opened o("rsa", {TextureItem("lighting/textures/rsalights/l0", Pattern(0xB0 + 4, 3)),
                     TextureItem("worlds/w/t", TextureBytes(s))});
    const auto* light = Find(o.doc->roots, "lighting/textures/rsalights/l0.Texture");
    const auto* tex = Find(o.doc->roots, "worlds/w/t.Texture");
    REQUIRE(light);
    REQUIRE(tex);
    CHECK(o.ws->Catalog().Key(light->type) == "bl.rsalight");
    CHECK(light->kind == Onyx::Domain::MediaKind::Raw);
    CHECK(o.ws->Catalog().Key(tex->type) == "bl.texture");
    CHECK(tex->kind == Onyx::Domain::MediaKind::Image);
    const auto img = Decode(o, "worlds/w/t.Texture");
    REQUIRE(img);
    CHECK(img->format == PixelFormat::Bc1);
    CHECK(Count(o.doc->diags, "bl.texture.size") == 0);
}

TEST_CASE("ReadInfo") {
    TextureSpec s;
    s.engineFormat = 11;
    s.width = 64; s.height = 32; s.mips = 7;
    const auto info = Texture::ReadInfo(TextureBytes(s));
    REQUIRE(info);
    CHECK(info->engineFormat == 11);
    CHECK(info->width == 64);
    CHECK(info->height == 32);
    CHECK(info->mips == 7);
    CHECK_FALSE(Texture::ReadInfo(std::vector<std::byte>(0x10)));
}
