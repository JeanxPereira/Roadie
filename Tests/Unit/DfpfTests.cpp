#include <doctest/doctest.h>

#include "Support/DfpfWriter.h"

#include <Brutal/Install.h>
#include <Brutal/Module.h>

#include <Onyx/Core/Modules/Workspace.h>
#include <Onyx/Core/Vfs/OsFile.h>
#include <Onyx/TestKit/Goldens.h>

#include <filesystem>
#include <fstream>
#include <memory>
#include <string>

using namespace Brutal;
using namespace Brutal::Tests;
namespace Dfpf = Brutal::Dfpf;
using Onyx::Modules::Document;
using Onyx::Services::Severity;

namespace {

std::unique_ptr<Onyx::Modules::Workspace> NewWorkspace() {
    auto ws = std::make_unique<Onyx::Modules::Workspace>();
    REQUIRE(ws->AddModule(std::make_unique<Module>()).ok());
    return ws;
}

Document* OpenDoc(Onyx::Modules::Workspace& ws, const std::filesystem::path& header) {
    const auto id = ws.Open(header);
    REQUIRE(id != 0);
    Document* doc = ws.Get(id);
    REQUIRE(doc);
    return doc;
}

const Onyx::Domain::AssetEntry* Find(const std::vector<Onyx::Domain::AssetEntry>& level, const std::string& path) {
    const size_t slash = path.find('/');
    if (slash == std::string::npos) {
        for (const auto& e : level) {
            if (e.name == path) return &e;
        }
        return nullptr;
    }
    for (const auto& e : level) {
        if (e.name == path.substr(0, slash)) return Find(e.children, path.substr(slash + 1));
    }
    return nullptr;
}

size_t Count(Document& doc, const std::string& code) {
    size_t n = 0;
    for (const auto& d : doc.diags.Snapshot()) n += d.code == code;
    return n;
}

struct Decoding {
    Onyx::Services::Progress progress;
    Onyx::Modules::DecodeContext ctx;
    Decoding(Onyx::Modules::Workspace& ws, Document& doc, const Onyx::Domain::AssetEntry& entry)
        : ctx{&doc, entry, Onyx::Vfs::Reader(doc.files[entry.source.fileIndex], entry.source.offset, entry.source.size),
              doc.diags, progress, ws.Settings(), doc.moduleState} {}
};

std::shared_ptr<const Install> InstallOfDoc(const Document& doc) {
    return std::static_pointer_cast<const Install>(doc.moduleState);
}

Item MakeItem(const std::string& name, const std::string& type, size_t size, uint8_t seed, uint32_t headerSize = 0,
              Dfpf::Compression c = Dfpf::Compression::Raw) {
    Item it;
    it.name = name;
    it.type = type;
    it.unpacked = Pattern(size, seed);
    it.headerSize = headerSize;
    it.compression = c;
    return it;
}

// a: x.Mesh (also in c), x.Skeleton; b: tex.Texture (zlib); c: x.Mesh (different bytes), hud.Movie.
void WriteThree(const std::filesystem::path& dir) {
    WriteBundle(dir, {"a", {}, {MakeItem("characters/bipeds/x", "Mesh", 40, 1), MakeItem("characters/bipeds/x", "Skeleton", 24, 2, 8, Dfpf::Compression::Zlib)}});
    WriteBundle(dir, {"b", {}, {MakeItem("worlds/w1/tex", "Texture", 64, 3, 4, Dfpf::Compression::Zlib)}});
    WriteBundle(dir, {"c", {}, {MakeItem("characters/bipeds/x", "Mesh", 40, 9), MakeItem("ui/hud", "Movie", 16, 4)}});
}

}

TEST_CASE("RecordBitfields") {
    TempDir dir("bitfields");
    Item boundary = MakeItem("big", "Two", 0, 0);
    boundary.dataSize = 0xFFFFFF;
    boundary.headerSizeField = 0x3FFFF;
    boundary.offset = (1u << 29) - 1;
    boundary.storedSize = (1u << 23) - 1;
    Item plain = MakeItem("plain", "Zero", 4, 0);
    const auto header = WriteBundle(dir.path(), {"a", {"Zero", "One", "Two"}, {plain, boundary}});

    auto file = Onyx::Vfs::OsFile::Open(header);
    REQUIRE(file.ok());
    Onyx::Vfs::Reader reader(file.value());
    auto bundle = Dfpf::ParseHeader(reader, header);
    REQUIRE(bundle.ok());
    REQUIRE(bundle.value().records.size() == 2);
    const Dfpf::Record& r = bundle.value().records[1];
    CHECK(r.dataSize == 0xFFFFFF);
    CHECK(r.headerSize == 0x3FFFF);
    CHECK(r.offset == (1u << 29) - 1);
    CHECK(r.storedSize == (1u << 23) - 1);
    CHECK(r.type == "Two");
    CHECK(r.name == "big");
    CHECK(r.compression == Dfpf::Compression::Raw);
    CHECK(r.UnpackedSize() == uint64_t(0xFFFFFF) + 0x3FFFF);
    CHECK(r.Path() == "big.Two");
    CHECK(bundle.value().records[0].type == "Zero");
    CHECK(bundle.value().name == "a");
}

TEST_CASE("ParseHeader rejects bad magic, version and truncation") {
    TempDir dir("badheader");
    const auto header = WriteBundle(dir.path(), {"a", {}, {MakeItem("x", "Mesh", 4, 0)}});
    const auto parse = [&](const std::vector<std::byte>& bytes) {
        const auto p = dir / "bad.~h";
        std::ofstream(p, std::ios::binary).write(reinterpret_cast<const char*>(bytes.data()), std::streamsize(bytes.size()));
        auto file = Onyx::Vfs::OsFile::Open(p);
        REQUIRE(file.ok());
        Onyx::Vfs::Reader reader(file.value());
        return Dfpf::ParseHeader(reader, p);
    };
    std::vector<std::byte> good;
    {
        auto file = Onyx::Vfs::OsFile::Open(header);
        Onyx::Vfs::Reader reader(file.value());
        good = reader.ReadAll();
    }
    auto bad = good;
    bad[0] = std::byte{'D'};
    CHECK(parse(bad).error().code == "bl.dfpf.magic");
    bad = good;
    bad[4] = std::byte{4};
    CHECK(parse(bad).error().code == "bl.dfpf.version");
    bad = good;
    bad.resize(0x30);
    CHECK(parse(bad).error().code == "bl.dfpf.truncated");
    bad = good;
    bad.resize(good.size() - 1);  // the record table now runs past the end
    CHECK(parse(bad).error().code == "bl.dfpf.truncated");
}

TEST_CASE("RawAndZlibUnpack") {
    TempDir dir("unpack");
    Item raw = MakeItem("r", "Mesh", 40, 5, 8);
    Item zl = MakeItem("z", "Mesh", 300, 6, 12, Dfpf::Compression::Zlib);
    const auto header = WriteBundle(dir.path(), {"a", {}, {raw, zl}});
    auto ws = NewWorkspace();
    Document* doc = OpenDoc(*ws, header);
    const auto install = InstallOfDoc(*doc);
    REQUIRE(install);
    for (const Item* it : {&raw, &zl}) {
        const RecordRef* ref = install->Find(it->name + ".Mesh");
        REQUIRE(ref);
        CHECK(install->RecordOf(*ref).UnpackedSize() == it->unpacked.size());
        const auto bytes = install->Read(*ref, doc->diags);
        REQUIRE(bytes);
        CHECK(*bytes == it->unpacked);
    }
    CHECK(doc->diags.Count(Severity::Warning) == 0);

    // The decode path: an entry's range finds its record.
    const auto* entry = Find(doc->roots, "z.Mesh");
    REQUIRE(entry);
    Decoding d(*ws, *doc, *entry);
    const auto bytes = UnpackEntry(d.ctx);
    REQUIRE(bytes);
    CHECK(*bytes == zl.unpacked);
}

TEST_CASE("CorruptZlib") {
    TempDir dir("corrupt");
    Item zl = MakeItem("z", "Mesh", 300, 6, 0, Dfpf::Compression::Zlib);
    zl.corruptStream = true;
    const auto header = WriteBundle(dir.path(), {"a", {}, {zl, MakeItem("ok", "Mesh", 8, 1)}});
    auto ws = NewWorkspace();
    Document* doc = OpenDoc(*ws, header);
    const auto* entry = Find(doc->roots, "z.Mesh");
    REQUIRE(entry);
    Decoding d(*ws, *doc, *entry);
    CHECK_FALSE(UnpackEntry(d.ctx));
    CHECK(Count(*doc, "bl.dfpf.inflate") == 1);
    for (const auto& diag : doc->diags.Snapshot()) {
        if (diag.code == "bl.dfpf.inflate") {
            CHECK(diag.severity == Severity::Error);
            CHECK(diag.message.find("z.Mesh") != std::string::npos);
        }
    }
}

TEST_CASE("MissingPayload") {
    TempDir dir("nopayload");
    const auto header = WriteBundle(dir.path(), {"a", {}, {MakeItem("x", "Mesh", 8, 1), MakeItem("y", "Mesh", 8, 2)}});
    std::filesystem::remove(dir / "a.~p");
    auto ws = NewWorkspace();
    Document* doc = OpenDoc(*ws, header);
    REQUIRE(doc->roots.size() == 2);
    for (const auto& e : doc->roots) CHECK(Onyx::Domain::HasFlag(e.flags, Onyx::Domain::NodeFlags::Failed));
    CHECK(Count(*doc, "bl.dfpf.payload") == 1);
}

TEST_CASE("RecordPastPayloadEnd") {
    TempDir dir("pastend");
    Item far = MakeItem("far", "Mesh", 8, 2);
    far.offset = 1000;  // the payload holds a few dozen bytes
    const auto header = WriteBundle(dir.path(), {"a", {}, {MakeItem("x", "Mesh", 8, 1), far, MakeItem("z", "Mesh", 8, 3)}});
    auto ws = NewWorkspace();
    Document* doc = OpenDoc(*ws, header);
    using Onyx::Domain::HasFlag;
    using Onyx::Domain::NodeFlags;
    REQUIRE(Find(doc->roots, "far.Mesh"));
    CHECK(HasFlag(Find(doc->roots, "far.Mesh")->flags, NodeFlags::Failed));
    CHECK_FALSE(HasFlag(Find(doc->roots, "x.Mesh")->flags, NodeFlags::Failed));
    CHECK_FALSE(HasFlag(Find(doc->roots, "z.Mesh")->flags, NodeFlags::Failed));
    CHECK(Count(*doc, "bl.dfpf.range") == 1);
    CHECK(Count(*doc, "bl.dfpf.payload") == 0);
}

TEST_CASE("SiblingsJoinOneDocument") {
    TempDir dir("siblings");
    WriteThree(dir.path());
    auto ws = NewWorkspace();
    Document* doc = OpenDoc(*ws, dir / "b.~h");
    const auto install = InstallOfDoc(*doc);
    REQUIRE(install);
    REQUIRE(install->bundles.size() == 3);
    CHECK(install->bundles[0].name == "a");
    CHECK(install->bundles[1].name == "b");
    CHECK(install->bundles[2].name == "c");
    CHECK(Find(doc->roots, "characters/bipeds/x.Skeleton"));
    CHECK(Find(doc->roots, "worlds/w1/tex.Texture"));
    CHECK(Find(doc->roots, "ui/hud.Movie"));
    // .~p of every bundle, behind the opened .~h
    CHECK(doc->files.size() == 4);

    const RecordRef* ref = install->Find("characters/bipeds/x.Mesh");
    REQUIRE(ref);
    CHECK(install->bundles[ref->bundle].name == "a");
    const auto bytes = install->Read(*ref, doc->diags);
    REQUIRE(bytes);
    CHECK(*bytes == Pattern(40, 1));
    CHECK(doc->diags.Count(Severity::Warning) == 0);
}

TEST_CASE("LoneBundleIsScoped") {
    TempDir all("lone-all");
    TempDir lone("lone");
    WriteThree(all.path());
    for (const char* f : {"b.~h", "b.~p"}) std::filesystem::copy_file(all / f, lone / f);
    auto ws = NewWorkspace();
    Document* doc = OpenDoc(*ws, lone / "b.~h");
    const auto install = InstallOfDoc(*doc);
    REQUIRE(install);
    CHECK(install->bundles.size() == 1);
    CHECK(Find(doc->roots, "worlds/w1/tex.Texture"));
    CHECK_FALSE(Find(doc->roots, "ui/hud.Movie"));
    CHECK_FALSE(install->Read("ui/hud.Movie", doc->diags));
    CHECK(install->Read("worlds/w1/tex.Texture", doc->diags));
}

TEST_CASE("PathLookupNormalizes") {
    TempDir dir("lookup");
    WriteBundle(dir.path(), {"a", {}, {MakeItem("characters/bipeds/x", "Mesh", 8, 1)}});
    auto ws = NewWorkspace();
    Document* doc = OpenDoc(*ws, dir / "a.~h");
    const auto install = InstallOfDoc(*doc);
    REQUIRE(install);
    CHECK(install->Find("Characters\\Bipeds\\X.Mesh"));
    CHECK(install->Find("characters/bipeds/x.Mesh"));
    CHECK_FALSE(install->Find("characters/bipeds/y.Mesh"));
    CHECK_FALSE(install->Find(""));
}

TEST_CASE("TreeGolden") {
    TempDir dir("golden");
    WriteThree(dir.path());
    auto ws = NewWorkspace();
    Document* doc = OpenDoc(*ws, dir / "b.~h");
    const std::string snapshot = Onyx::TestKit::SnapshotTree(*doc, ws->Catalog());
    const std::filesystem::path golden = std::filesystem::path(ROADIE_GOLDEN_DIR) / "install.golden.json";
    Onyx::TestKit::UpdateGolden(snapshot, golden);
    std::string diff;
    CHECK_MESSAGE(Onyx::TestKit::CompareTreeGolden(snapshot, golden, diff), diff);
}
