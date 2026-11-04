#include "Corpus.h"

#include <Brutal/InstallPath.h>
#include <Brutal/Module.h>

#include <Onyx/Core/Services/Paths.h>

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <vector>

namespace Corpus {

namespace {

void Walk(const std::vector<Onyx::Domain::AssetEntry>& level, const std::function<void(const Onyx::Domain::AssetEntry&)>& fn) {
    for (const auto& e : level) {
        if (e.children.empty()) fn(e);
        else Walk(e.children, fn);
    }
}

}

std::unique_ptr<Opened> OpenInstall() {
    const std::filesystem::path game = Brutal::DefaultInstall();
    const std::string shown = Onyx::Services::Paths::ToUtf8(game);
    const auto header = Brutal::ResolveInstallPath(game);
    if (!header) {
        std::cerr << "no *.~h under " << shown << " (set BL_GAME_DIR)\n";
        return nullptr;
    }
    auto opened = std::make_unique<Opened>();
    if (!opened->ws.AddModule(std::make_unique<Brutal::Module>()).ok()) {
        std::cerr << "cannot register Brutal::Module\n";
        return nullptr;
    }
    opened->id = opened->ws.Open(*header);
    if (opened->id == 0 || !opened->ws.Get(opened->id)) {
        std::cerr << "cannot open " << Onyx::Services::Paths::ToUtf8(*header) << "\n";
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
