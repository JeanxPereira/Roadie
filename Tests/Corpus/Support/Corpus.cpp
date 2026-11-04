#include "Corpus.h"

#include <Brutal/Module.h>

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <vector>

namespace Corpus {

namespace {

constexpr const char* kDefaultGameDir = R"(D:\ProgramLibrary\Steam\steamapps\common\BrutalLegend)";

void Walk(const std::vector<Onyx::Domain::AssetEntry>& level, const std::function<void(const Onyx::Domain::AssetEntry&)>& fn) {
    for (const auto& e : level) {
        if (e.children.empty()) fn(e);
        else Walk(e.children, fn);
    }
}

}

std::filesystem::path PacksDir() {
    const char* env = std::getenv("BL_GAME_DIR");
    return std::filesystem::path(env && *env ? env : kDefaultGameDir) / "Win" / "Packs";
}

std::unique_ptr<Opened> OpenInstall() {
    const std::filesystem::path dir = PacksDir();
    std::vector<std::filesystem::path> headers;
    std::error_code ec;
    for (std::filesystem::directory_iterator it(dir, ec), end; !ec && it != end; it.increment(ec)) {
        if (it->path().extension() == ".~h") headers.push_back(it->path());
    }
    if (headers.empty()) {
        std::cerr << "no *.~h in " << dir.string() << " (set BL_GAME_DIR)\n";
        return nullptr;
    }
    std::sort(headers.begin(), headers.end());
    auto opened = std::make_unique<Opened>();
    if (!opened->ws.AddModule(std::make_unique<Brutal::Module>()).ok()) {
        std::cerr << "cannot register Brutal::Module\n";
        return nullptr;
    }
    opened->id = opened->ws.Open(headers.front());
    if (opened->id == 0 || !opened->ws.Get(opened->id)) {
        std::cerr << "cannot open " << headers.front().string() << "\n";
        return nullptr;
    }
    return opened;
}

void ForEachLeaf(const Onyx::Modules::Document& doc, const std::function<void(const Onyx::Domain::AssetEntry&)>& fn) {
    Walk(doc.roots, fn);
}

int Verdict(const std::map<std::string, uint64_t>& counts, const std::map<std::string, uint64_t>& bad,
            const std::map<std::string, std::string>& examples) {
    uint64_t total = 0;
    for (const auto& [kind, n] : bad) total += n;
    std::cout << "{";
    bool first = true;
    for (const auto& [key, n] : counts) {
        std::cout << (first ? "" : ", ") << "'" << key << "': " << n;
        first = false;
    }
    std::cout << "} bad " << total << "\n";
    for (const auto& [kind, text] : examples) std::cout << "  e.g. " << kind << " " << text << "\n";
    return total ? 1 : 0;
}

}
