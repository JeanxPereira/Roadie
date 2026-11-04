#pragma once

#include <Onyx/Core/Modules/GameModule.h>

namespace Brutal {

// Module id "bl". A bundle is a DFPF container (`.~h` header + `.~p` data), version 5.
class Module final : public Onyx::Modules::IGameModule {
public:
    Onyx::Modules::ModuleInfo Info() const override;
    Onyx::Modules::ProbeResult Probe(const Onyx::Modules::ProbeInput& input) const override;
    void RegisterTypes(Onyx::Types::TypeRegistrar& registrar) override;
    void RegisterDecoders(Onyx::Modules::DecoderRegistry& decoders) override;
    Onyx::Modules::ParseResult ParseContainer(Onyx::Modules::ContainerContext& ctx) override;
};

}
