#pragma once

#include <Onyx/Core/Domain/AssetEntry.h>
#include <Onyx/Core/Modules/Workspace.h>

#include <cstdint>
#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <string>

// Shared by the corpus gates: the game install, opened through a real Workspace with Brutal::Module.
namespace Corpus {

struct Opened {
    Onyx::Modules::Workspace ws;
    Onyx::Modules::DocumentId id = 0;
};

// Opens the install at Brutal::DefaultInstall() (BL_GAME_DIR or the Steam path) through Brutal::ResolveInstallPath; null (with a message on stderr) when there is none or the open fails.
std::unique_ptr<Opened> OpenInstall();

// Calls `fn` for every leaf (an entry without children) of the document's tree.
void ForEachLeaf(const Onyx::Modules::Document& doc, const std::function<void(const Onyx::Domain::AssetEntry&)>& fn);

// Prints the counts, "bad N" and up to one example per failure kind (the shape of the Python gates).
// Returns 0 when `bad` is empty, 1 otherwise.
int Verdict(const std::map<std::string, uint64_t>& counts, const std::map<std::string, uint64_t>& bad,
            const std::map<std::string, std::string>& examples);

}
