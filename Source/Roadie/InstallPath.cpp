#include "InstallPath.h"

#include <Onyx/Core/Services/Paths.h>

#include <algorithm>
#include <cstdlib>
#include <string>
#include <vector>

namespace Roadie {

namespace fs = std::filesystem;

namespace {

std::string LowerExt(const fs::path& p) {
    std::string ext = Onyx::Services::Paths::ToUtf8(p.extension());
    for (char& c : ext) c = (c >= 'A' && c <= 'Z') ? char(c - 'A' + 'a') : c;
    return ext;
}

std::optional<fs::path> FirstHeader(const fs::path& dir) {
    std::vector<fs::path> found;
    std::error_code ec;
    for (fs::directory_iterator it(dir, ec), end; !ec && it != end; it.increment(ec)) {
        if (it->is_regular_file(ec) && LowerExt(it->path()) == ".~h") found.push_back(it->path());
    }
    if (found.empty()) return std::nullopt;
    std::sort(found.begin(), found.end(), [](const fs::path& a, const fs::path& b) {
        return Onyx::Services::Paths::ToUtf8(a.filename()) < Onyx::Services::Paths::ToUtf8(b.filename());
    });
    return found.front();
}

}

std::optional<fs::path> ResolveInstallPath(const fs::path& p) {
    std::error_code ec;
    if (fs::is_regular_file(p, ec)) {
        const std::string ext = LowerExt(p);
        if (ext == ".~h") return p;
        if (ext == ".~p") {
            fs::path header = p;
            header.replace_extension(".~h");
            if (fs::is_regular_file(header, ec)) return header;
        }
        return std::nullopt;
    }
    if (!fs::is_directory(p, ec)) return std::nullopt;
    const fs::path packs = p / "Win" / "Packs";
    if (fs::is_directory(packs, ec)) {
        if (auto h = FirstHeader(packs)) return h;
    }
    return FirstHeader(p);
}

fs::path DefaultInstall() {
#ifdef _WIN32
    if (const wchar_t* env = _wgetenv(L"BL_GAME_DIR"); env && *env) return fs::path(env);
#else
    if (const char* env = std::getenv("BL_GAME_DIR"); env && *env) return fs::path(env);
#endif
    return fs::path(LR"(D:\ProgramLibrary\Steam\steamapps\common\BrutalLegend)");
}

}
