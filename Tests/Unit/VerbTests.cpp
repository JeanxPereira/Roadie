// The Roadie verbs over a synthetic install. Goldens are captured the way OnyxSDK's
// Tests/Cli/PrismVerbs.cpp does: Cli::Run over a VerbTable, stdout and stderr and the exit code in
// one text, the temp path replaced by <game>.
#include <doctest/doctest.h>

#include "Support/DfpfWriter.h"
#include "Support/TextureWriter.h"

#include <Brutal/Module.h>
#include <Brutal/Texture.h>

#include <InstallPath.h>
#include <Verbs.h>

#include <Onyx/Core/Cli/Json.h>
#include <Onyx/Core/Cli/Run.h>
#include <Onyx/Core/Modules/Workspace.h>
#include <Onyx/Core/Services/Paths.h>
#include <Onyx/TestKit/Goldens.h>

#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

using namespace Brutal;
using namespace Brutal::Tests;
namespace fs = std::filesystem;

namespace {

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

TextureSpec Dxt1Spec() {
    TextureSpec s;
    s.engineFormat = 9;
    s.fourcc = "DXT1";
    s.data = Pattern(8, 5);
    return s;
}

Item TextureItem(const std::string& name, const TextureSpec& spec) {
    Item it;
    it.name = name;
    it.type = "Texture";
    it.unpacked = TextureBytes(spec);
    it.headerSize = uint32_t(Texture::kHeaderSize);
    it.compression = Dfpf::Compression::Zlib;
    return it;
}

// Mesh x2, Texture x2, Skeleton, Movie over two bundles.
void WriteInstall(const fs::path& game) {
    const fs::path packs = game / "Win" / "Packs";
    fs::create_directories(packs);
    WriteBundle(packs, {"a",
                        {},
                        {MakeItem("characters/bipeds/a01_avatar/a01_avatar", "Mesh", 40, 1),
                         MakeItem("characters/bipeds/a01_avatar/a01_avatar", "Skeleton", 24, 2, 8, Dfpf::Compression::Zlib),
                         MakeItem("characters/props/crate", "Mesh", 16, 3)}});
    WriteBundle(packs, {"b",
                        {},
                        {TextureItem("worlds/w1/tex", Dxt1Spec()), TextureItem("worlds/w1/avatar_tex", Dxt1Spec()),
                         MakeItem("ui/hud", "Movie", 16, 4)}});
}

std::string ReplaceAll(std::string text, const std::string& from, std::string_view to) {
    if (from.empty()) return text;
    for (size_t pos = text.find(from); pos != std::string::npos; pos = text.find(from, pos + to.size())) {
        text.replace(pos, from.size(), to);
    }
    return text;
}

struct Captured {
    int rc = 0;
    std::string out, err;
};

// Runs `roadie <args> --game <game>` (the --game pair is added when `game` is non-empty).
Captured Run(std::vector<std::string> args, const fs::path& game) {
    Onyx::Modules::Workspace ws;
    REQUIRE(ws.AddModule(std::make_unique<Module>()).ok());
    Onyx::Cli::VerbTable table;
    table.Add(Roadie::Verbs());
    if (!game.empty()) {
        args.push_back("--game");
        args.push_back(Onyx::Services::Paths::ToUtf8(game));
    }
    args.insert(args.begin(), "roadie");
    std::vector<char*> argv;
    for (std::string& a : args) argv.push_back(a.data());
    std::ostringstream out, err;
    Captured c;
    c.rc = Onyx::Cli::Run(ws, table, int(argv.size()), argv.data(), out, err);
    c.out = out.str();
    c.err = err.str();
    return c;
}

std::string Golden(const Captured& c, const fs::path& game, const fs::path& scratch = {}) {
    std::string text = "exit " + std::to_string(c.rc) + "\n--- stdout\n" + c.out + "--- stderr\n" + c.err;
    for (const auto& [p, tag] : {std::pair{game, "<game>"}, std::pair{scratch, "<out>"}}) {
        if (p.empty()) continue;
        const std::string utf8 = Onyx::Services::Paths::ToUtf8(p);
        text = ReplaceAll(std::move(text), Onyx::Cli::JsonEscape(utf8), tag);
        text = ReplaceAll(std::move(text), utf8, tag);
    }
    return text;
}

void CheckGolden(const std::string& actual, const char* golden) {
    const fs::path file = fs::path(ROADIE_GOLDEN_DIR) / "Cli" / golden;
    Onyx::TestKit::UpdateGolden(actual, file);
    std::string diff;
    CHECK_MESSAGE(Onyx::TestKit::CompareTreeGolden(actual, file, diff), diff);
}

std::vector<std::byte> ReadAll(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    std::vector<char> raw((std::istreambuf_iterator<char>(f)), {});
    return std::vector<std::byte>(reinterpret_cast<const std::byte*>(raw.data()),
                                  reinterpret_cast<const std::byte*>(raw.data()) + raw.size());
}

}

TEST_CASE("CliGolden.Types") {
    TempDir dir("vtypes");
    WriteInstall(dir.path());
    CheckGolden(Golden(Run({"types"}, dir.path()), dir.path()), "types.txt");
}

TEST_CASE("CliGolden.Ls") {
    TempDir dir("vls");
    WriteInstall(dir.path());
    CheckGolden(Golden(Run({"ls"}, dir.path()), dir.path()), "ls.txt");
}

TEST_CASE("CliGolden.LsTexture") {
    TempDir dir("vlst");
    WriteInstall(dir.path());
    CheckGolden(Golden(Run({"ls", "-t", "Texture"}, dir.path()), dir.path()), "ls-texture.txt");
}

TEST_CASE("CliGolden.LsGlob") {
    TempDir dir("vlsg");
    WriteInstall(dir.path());
    // Case-insensitive, over the path; the bare name form matches too.
    CheckGolden(Golden(Run({"ls", "*AVATAR*"}, dir.path()), dir.path()), "ls-avatar.txt");
    CHECK(Run({"ls", "ui/hud"}, dir.path()).out == "ui/hud.Movie\n");
    CHECK(Run({"ls", "crat?"}, dir.path()).out.empty());
    CHECK(Run({"ls", "characters/props/crat[a-f]"}, dir.path()).out == "characters/props/crate.Mesh\n");
    CHECK(Run({"ls", "*.[!M]*"}, dir.path()).out.find(".Mesh") == std::string::npos);
}

TEST_CASE("CliGolden.LsMissingInstall") {
    TempDir dir("vmiss");
    const Captured c = Run({"ls"}, dir.path() / "nowhere");
    CHECK(c.rc != 0);
    CheckGolden(Golden(c, dir.path()), "ls-missing.txt");
}

TEST_CASE("CliGolden.ExtractConvert") {
    TempDir dir("vext");
    WriteInstall(dir.path());
    const fs::path out = dir / "out";
    const Captured c = Run({"extract", "*", "-o", Onyx::Services::Paths::ToUtf8(out), "--convert"}, dir.path());
    CheckGolden(Golden(c, dir.path(), out), "extract-convert.txt");
    CHECK(ReadAll(out / "worlds" / "w1" / "tex.dds") == DdsBytes(Dxt1Spec()));
    CHECK_FALSE(fs::exists(out / "worlds" / "w1" / "tex.Texture"));
    CHECK(ReadAll(out / "characters" / "props" / "crate.Mesh") == Pattern(16, 3));
    CHECK(ReadAll(out / "characters" / "bipeds" / "a01_avatar" / "a01_avatar.Skeleton") == Pattern(24, 2));
}

TEST_CASE("ExtractRaw") {
    TempDir dir("vextraw");
    WriteInstall(dir.path());
    const fs::path out = dir / "out";
    const Captured c = Run({"extract", "*", "-t", "Texture", "-o", Onyx::Services::Paths::ToUtf8(out)}, dir.path());
    CHECK(c.out == "2 written\n");
    CHECK(ReadAll(out / "worlds" / "w1" / "tex.Texture") == TextureBytes(Dxt1Spec()));
    CHECK_FALSE(fs::exists(out / "ui"));
}

TEST_CASE("ExtractReportsFailuresAndContinues") {
    TempDir dir("vextbad");
    const fs::path packs = dir / "Win" / "Packs";
    fs::create_directories(packs);
    Item bad = MakeItem("bad/zip", "Mesh", 32, 1, 0, Dfpf::Compression::Zlib);
    bad.corruptStream = true;
    WriteBundle(packs, {"a", {}, {bad, MakeItem("good/one", "Mesh", 8, 2)}});
    const fs::path out = dir / "out";
    const Captured c = Run({"extract", "*", "-o", Onyx::Services::Paths::ToUtf8(out)}, dir.path());
    CHECK(c.rc == Onyx::Cli::kPartial);
    CHECK(c.out == "1 written\n");
    CHECK(c.err.find("bad/zip.Mesh") != std::string::npos);
    CHECK(ReadAll(out / "good" / "one.Mesh") == Pattern(8, 2));
}

TEST_CASE("UsageErrors") {
    TempDir dir("vusage");
    WriteInstall(dir.path());
    CHECK(Run({"extract", "*"}, dir.path()).rc == Onyx::Cli::kUsage);
    CHECK(Run({"ls", "--bogus"}, dir.path()).rc == Onyx::Cli::kUsage);
    CHECK(Run({"types", "extra"}, dir.path()).rc == Onyx::Cli::kUsage);
}

TEST_CASE("NonAsciiInstallPath") {
    TempDir plain("vascii");
    TempDir dir("vutf");
    const fs::path game = dir.path() / Onyx::Services::Paths::FromUtf8("Br\xC3\xBCtal Legend");
    WriteInstall(plain.path());
    WriteInstall(game);
    const Captured a = Run({"ls"}, plain.path());
    const Captured b = Run({"ls"}, game);
    CHECK(b.rc == 0);
    CHECK_FALSE(b.out.empty());
    CHECK(a.out == b.out);
    CHECK(Run({"types"}, plain.path()).out == Run({"types"}, game).out);
}

TEST_CASE("ResolveFolder") {
    TempDir dir("vresolve");
    WriteInstall(dir.path());
    const fs::path expected = dir / "Win" / "Packs" / "a.~h";
    const auto equal = [&](const std::optional<fs::path>& r) { return r && fs::equivalent(*r, expected); };
    CHECK(equal(Roadie::ResolveInstallPath(dir.path())));
    CHECK(equal(Roadie::ResolveInstallPath(dir.path() / "Win" / "Packs")));
    CHECK(equal(Roadie::ResolveInstallPath(dir.path() / "Win" / "Packs" / "a.~p")));
    // A .~p or .~h of another bundle stands for itself; the Module joins the siblings.
    CHECK(Roadie::ResolveInstallPath(dir.path() / "Win" / "Packs" / "b.~p") == dir.path() / "Win" / "Packs" / "b.~h");
    CHECK(equal(Roadie::ResolveInstallPath(expected)));
    CHECK_FALSE(Roadie::ResolveInstallPath(dir.path() / "Win"));
    CHECK_FALSE(Roadie::ResolveInstallPath(dir.path() / "missing"));
    std::ofstream(dir / "readme.txt") << "x";
    CHECK_FALSE(Roadie::ResolveInstallPath(dir.path() / "readme.txt"));
}
