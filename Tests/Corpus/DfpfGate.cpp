// Corpus gate for DFPF records, through the module: the install is opened by a Workspace with
// Brutal::Module, and every leaf of the document is read with Install::Read. Replaces
// the retired Python DFPF gate and proves at least its numbers on the Steam install:
//     bundles 21, records 71,095, comp4 (raw) 10,900, comp8 (zlib) 60,195, comp12 (xmem) 0, bad 0,
//     71,095 distinct lower-cased paths (no resource path in two bundles; Install::Find would
//     otherwise hide one), zero Error diagnostics, zero bl.dfpf.overlap warnings (Install::At resolves a shared stored
//     range to its first record, which is only safe when no range is shared).
// Per record: Install::Read returns exactly header + data bytes (UnpackedSize), and a raw record
// stores exactly that many bytes.
//
// Mutation (2026-11-03): in Source/Brutal/Dfpf.cpp, header-size mask 0x3FFFF -> 0x1FFFF. The gate
// fails with read-failed (zlib stream does not inflate to the wrong size) on the 34 records whose header is 128 KiB or
// larger; reverting the mask passes again.
#include "Corpus.h"

#include <Brutal/Install.h>

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <vector>

namespace {

constexpr uint64_t kBundles = 21, kRecords = 71095, kComp4 = 10900, kComp8 = 60195;

}

int main() {
    auto opened = Corpus::OpenInstall();
    if (!opened) return 1;
    Onyx::Modules::Document* doc = opened->ws.Get(opened->id);
    const auto install = std::static_pointer_cast<const Brutal::Install>(doc->moduleState);
    if (!install) {
        std::cerr << "the document holds no Brutal::Install\n";
        return 1;
    }

    std::map<std::string, uint64_t> counts, bad;
    std::map<std::string, std::string> examples;
    const auto fail = [&](const std::string& kind, const std::string& what) {
        ++bad[kind];
        examples.emplace(kind, what);
    };

    counts["bundles"] = install->bundles.size();
    if (install->bundles.size() != kBundles) {
        fail("bundle-count", std::to_string(install->bundles.size()) + " vs " + std::to_string(kBundles));
    }

    // No path may repeat across bundles: Install::Find keeps the first, so a repeat would hide a record.
    std::set<std::string> distinct;
    for (const Brutal::Dfpf::Bundle& bundle : install->bundles) {
        for (const Brutal::Dfpf::Record& rec : bundle.records) {
            std::string key = rec.Path();
            for (char& c : key) c = (c >= 'A' && c <= 'Z') ? char(c - 'A' + 'a') : c;
            distinct.insert(std::move(key));
        }
    }
    counts["distinct-paths"] = distinct.size();

    Onyx::Services::DiagSink readDiags;
    // Read in payload order: the tree order is alphabetical, which is random access on the disk.
    std::vector<const Onyx::Domain::AssetEntry*> leaves;
    Corpus::ForEachLeaf(*doc, [&](const Onyx::Domain::AssetEntry& leaf) { leaves.push_back(&leaf); });
    std::sort(leaves.begin(), leaves.end(), [](const auto* a, const auto* b) {
        return std::tie(a->source.fileIndex, a->source.offset) < std::tie(b->source.fileIndex, b->source.offset);
    });
    for (const Onyx::Domain::AssetEntry* leafPtr : leaves) {
        const Onyx::Domain::AssetEntry& leaf = *leafPtr;
        const Brutal::RecordRef* ref = install->At(leaf.source);
        if (!ref) {
            fail("no-record", leaf.name);
            continue;
        }
        const Brutal::Dfpf::Record& rec = install->RecordOf(*ref);
        ++counts["records"];
        ++counts["comp" + std::to_string(int(rec.compression))];
        const std::string sizes = std::to_string(rec.headerSize) + "+" + std::to_string(rec.dataSize);
        if (Onyx::Domain::HasFlag(leaf.flags, Onyx::Domain::NodeFlags::Failed)) fail("flagged-failed", rec.Path());
        if (rec.compression == Brutal::Dfpf::Compression::Raw && rec.storedSize != rec.UnpackedSize()) {
            fail("raw-store-size", rec.Path() + ": " + std::to_string(rec.storedSize) + " vs " + sizes);
        }
        const auto bytes = install->Read(*ref, readDiags);
        if (!bytes) {
            fail("read-failed", rec.Path());
            continue;
        }
        if (bytes->size() != rec.UnpackedSize()) {
            fail("size-mismatch", rec.Path() + ": " + std::to_string(bytes->size()) + " vs " + sizes);
        }
    }

    for (const auto& d : readDiags.Snapshot()) {
        if (d.severity == Onyx::Services::Severity::Error) fail("read-diagnostic", d.code + ": " + d.message);
    }
    for (const auto& d : doc->diags.Snapshot()) {
        if (d.severity == Onyx::Services::Severity::Error) fail("error-diagnostic", d.code + ": " + d.message);
        if (d.code == "bl.dfpf.overlap") fail("overlap", d.message);
    }

    const auto expect = [&](const char* key, uint64_t want) {
        if (counts[key] != want) fail(std::string("count-") + key, std::to_string(counts[key]) + " vs " + std::to_string(want));
    };
    expect("records", kRecords);
    expect("comp4", kComp4);
    expect("comp8", kComp8);
    expect("distinct-paths", kRecords);
    if (counts["comp12"] != 0) fail("count-comp12", std::to_string(counts["comp12"]) + " vs 0");
    return Corpus::Verdict(counts, bad, examples);
}
