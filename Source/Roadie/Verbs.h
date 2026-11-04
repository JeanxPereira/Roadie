#pragma once

#include <Onyx/Core/Cli/Verb.h>

#include <vector>

// The command-line explorer, mirroring `python -m Brutal`. Every verb takes `--game DIR` (a game
// folder, Win/Packs, or any bundle file; default DefaultInstall()). Arguments are UTF-8.
//
//   types                                        "<count in 7> <Type>", most common first, ties by name
//   ls [GLOB] [-t TYPE]                          one resource path per line, sorted
//   extract GLOB -o DIR [--convert] [-t TYPE]    DIR/<path>; --convert: Texture -> DIR/<name>.dds
//
// GLOB is fnmatch (* ? [seq]) over the resource path or its name, case-insensitive. A record is
// listed once, from the bundle that wins the path (Brutal::Install::Find).
namespace Roadie {

std::vector<Onyx::Cli::Verb> Verbs();

}
