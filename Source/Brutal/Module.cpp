#include <Brutal/Module.h>

#include <cstring>

namespace Brutal {

using namespace Onyx;

Modules::ModuleInfo Module::Info() const {
    return {"bl", "Brütal Legend", {"brutal", "bl"}, {{"Brütal Legend bundle", {".~h"}}}};
}

// Evidence: the Win/Packs corpus; every bundle begins "dfpf" with the version byte 5 at offset 4.
Modules::ProbeResult Module::Probe(const Modules::ProbeInput& input) const {
    if (input.header.size() >= 5 && std::memcmp(input.header.data(), "dfpf", 4) == 0 &&
        static_cast<unsigned char>(input.header[4]) == 5) {
        return {95, "DFPF v5"};
    }
    return {0, "no evidence"};
}

void Module::RegisterTypes(Types::TypeRegistrar&) {}

void Module::RegisterDecoders(Modules::DecoderRegistry&) {}

Modules::ParseResult Module::ParseContainer(Modules::ContainerContext&) {
    return {};
}

}
