// Roadie: the Onyx Shell hosting the Brütal Legend module.
#include <Brutal/Module.h>

#include <Brutal/InstallPath.h>
#include "Verbs.h"

#include <filesystem>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include "Onyx/Core/Services/Paths.h"
#include "Onyx/Exchange/Exporters.h"
#include "Onyx/Shell/Shell.h"

#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#endif

namespace {

// The first argument as UTF-8: on Windows the narrow argv is in the ANSI code page and loses
// characters, so it is read again from the wide command line.
std::string FirstArgUtf8(int argc, char** argv) {
#ifdef _WIN32
    int count = 0;
    wchar_t** wide = CommandLineToArgvW(GetCommandLineW(), &count);
    std::string out;
    if (wide && count == argc && count >= 2) {
        const int size = WideCharToMultiByte(CP_UTF8, 0, wide[1], -1, nullptr, 0, nullptr, nullptr);
        if (size > 1) {
            out.assign(size_t(size), '\0');
            WideCharToMultiByte(CP_UTF8, 0, wide[1], -1, out.data(), size, nullptr, nullptr);
            out.pop_back();
        }
    }
    if (wide) LocalFree(wide);
    return out;
#else
    return argc >= 2 ? argv[1] : std::string();
#endif
}

}

int main(int argc, char** argv) {
    Onyx::Shell::Shell shell({.appName = "Roadie", .configDir = Onyx::Services::Paths::UserConfig("Roadie")});
    if (!shell.Workspace().AddModule(std::make_unique<Brutal::Module>()).ok()) return 1;
    Onyx::Exchange::AddExporters(shell.Verbs());
    shell.Verbs().Add(Roadie::Verbs());

    // `roadie <game folder>` opens the install. The rewritten argv is UTF-8 and not the process's
    // own, so Shell::Run uses it as given.
    std::vector<std::string> storage;
    std::vector<char*> args(argv, argv + argc);
    if (argc == 2) {
        const std::string first = FirstArgUtf8(argc, argv);
        std::error_code ec;
        const std::filesystem::path folder = Onyx::Services::Paths::FromUtf8(first);
        // A verb name wins over a folder of the same name.
        if (!first.empty() && !shell.Verbs().Find(first) && std::filesystem::is_directory(folder, ec)) {
            const auto header = Brutal::ResolveInstallPath(folder);
            if (!header) {
                std::cerr << "no Brütal Legend bundles under " << first << "\n";
                return 2;
            }
            storage = {argv[0], Onyx::Services::Paths::ToUtf8(*header)};
            args = {storage[0].data(), storage[1].data()};
        }
    }
    return shell.Run(int(args.size()), args.data());
}
