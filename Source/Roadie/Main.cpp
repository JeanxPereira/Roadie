// Roadie: the Onyx Shell hosting the Brütal Legend module.
#include <Brutal/Module.h>

#include <memory>

#include "Onyx/Core/Services/Paths.h"
#include "Onyx/Exchange/Exporters.h"
#include "Onyx/Shell/Shell.h"

int main(int argc, char** argv) {
    Onyx::Shell::Shell shell({.appName = "Roadie", .configDir = Onyx::Services::Paths::UserConfig("Roadie")});
    if (!shell.Workspace().AddModule(std::make_unique<Brutal::Module>()).ok()) return 1;
    Onyx::Exchange::AddExporters(shell.Verbs());
    return shell.Run(argc, argv);
}
