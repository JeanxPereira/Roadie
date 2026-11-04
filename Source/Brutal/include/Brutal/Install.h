#pragma once

#include <Brutal/Dfpf.h>

#include <Onyx/Core/Domain/ByteRange.h>
#include <Onyx/Core/Modules/DecodeContext.h>
#include <Onyx/Core/Services/Diagnostics.h>
#include <Onyx/Core/Vfs/IFile.h>

#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

// The bundles of one install as one resource namespace (the Python Library). A resource path is
// "name.Type" ("characters/bipeds/x.Mesh"); lookup lower-cases it and turns "\" into "/". When two
// bundles hold the same path the first bundle in sorted file-name order wins (Library.__init__ does
// setdefault over sorted(glob)); the Steam install has no such path (Tests/Corpus/DfpfGate.cpp
// asserts 71,095 distinct lower-cased paths).
namespace Brutal {

// Stands in for a file that is not there (a .~p that could not be opened, payload slot 0), so file
// indices stay aligned and no slot is null.
class EmptyFile final : public Onyx::Vfs::IFile {
public:
    uint64_t Size() const override { return 0; }
    size_t ReadAt(uint64_t, std::span<std::byte>) const override { return 0; }
};

struct RecordRef {
    uint32_t bundle = 0;
    uint32_t record = 0;
    uint32_t fileIndex = 0;  // index of the bundle's .~p in Document::files
};

class Install {
public:
    std::vector<Dfpf::Bundle> bundles;
    // Indexed by RecordRef::fileIndex, the same index as the document's `files`; slot 0 (the opened
    // .~h) and the slots of missing payloads hold an EmptyFile; no slot is null.
    std::vector<std::shared_ptr<const Onyx::Vfs::IFile>> payloads;
    // Per bundle: its .~p could be opened.
    std::vector<bool> payloadPresent;
    // Filled by Index(): (first, later) paths of records sharing one (file, offset, stored size) range.
    // At() resolves such a range to the first record only.
    std::vector<std::pair<std::string, std::string>> sharedRanges;

    // Appends a bundle whose payload is files[fileIndex]; call Index() once all are added.
    void Add(Dfpf::Bundle bundle, uint32_t fileIndex, std::shared_ptr<const Onyx::Vfs::IFile> payload, bool present);
    void Index();

    const RecordRef* Find(std::string_view path) const;
    const RecordRef* At(const Onyx::Domain::ByteRange& range) const;
    const Dfpf::Record& RecordOf(const RecordRef& ref) const { return bundles[ref.bundle].records[ref.record]; }

    // The record's bytes, inflated. Reports bl.dfpf.payload, bl.dfpf.range, bl.dfpf.inflate, bl.dfpf.xmem.
    std::optional<std::vector<std::byte>> Read(const RecordRef& ref, Onyx::Services::DiagSink& diags) const;
    std::optional<std::vector<std::byte>> Read(std::string_view path, Onyx::Services::DiagSink& diags) const;

private:
    std::vector<RecordRef> m_refs;  // every record, bundle order
    std::unordered_map<std::string, size_t> m_byPath;
    std::map<std::tuple<uint32_t, uint64_t, uint64_t>, size_t> m_byRange;
};

std::shared_ptr<const Install> InstallOf(const Onyx::Modules::DecodeContext& ctx);

// The entry's record, inflated; every later decoder starts here. Reports and returns nothing when
// the document holds no install, the entry is no record, or the bytes do not unpack.
std::optional<std::vector<std::byte>> UnpackEntry(Onyx::Modules::DecodeContext& ctx);

}
