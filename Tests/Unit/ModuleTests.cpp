#include <Brutal/Module.h>

#include <doctest/doctest.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>

namespace {

template <size_t N>
int Confidence(const std::array<uint8_t, N>& bytes) {
    const Brutal::Module module;
    Onyx::Modules::ProbeInput input;
    input.header = std::as_bytes(std::span(bytes));
    input.fileSize = N;
    return module.Probe(input).confidence;
}

}

TEST_CASE("Probe") {
    CHECK(Confidence(std::array<uint8_t, 8>{'d', 'f', 'p', 'f', 5, 0, 0, 0}) == 95);
    CHECK(Confidence(std::array<uint8_t, 8>{'d', 'f', 'p', 'f', 4, 0, 0, 0}) == 0);
    CHECK(Confidence(std::array<uint8_t, 8>{'D', 'F', 'P', 'F', 5, 0, 0, 0}) == 0);
    CHECK(Confidence(std::array<uint8_t, 0>{}) == 0);
}
