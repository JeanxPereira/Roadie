#pragma once

#include <filesystem>
#include <optional>

// Which file opens an install. The Module joins every sibling .~h into one document, so any one
// header stands for the whole install.
namespace Roadie {

// A .~h as given; a .~p -> its .~h (when it exists); a folder holding Win/Packs, or holding *.~h
// itself -> its first *.~h in file-name byte order; anything else -> nullopt.
std::optional<std::filesystem::path> ResolveInstallPath(const std::filesystem::path& p);

// BL_GAME_DIR, or the Steam path Brutal/paths.py defaults to.
std::filesystem::path DefaultInstall();

}
