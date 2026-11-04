#include <Brutal/Install.h>

#include <Onyx/Core/Modules/Document.h>

#include <algorithm>

namespace Brutal {

using namespace Onyx;

namespace {

void Report(Services::DiagSink& diags, const char* code, std::string message) {
    diags.Report({Services::Severity::Error, code, std::move(message), std::nullopt});
}

char Lower(char c) {
    return (c >= 'A' && c <= 'Z') ? char(c - 'A' + 'a') : c;
}

}

void Install::Add(Dfpf::Bundle bundle, uint32_t fileIndex, std::shared_ptr<const Vfs::IFile> payload, bool present) {
    const auto b = uint32_t(bundles.size());
    for (uint32_t r = 0; r < bundle.records.size(); ++r) m_refs.push_back({b, r, fileIndex});
    bundles.push_back(std::move(bundle));
    payloads.resize(std::max<size_t>(payloads.size(), size_t(fileIndex) + 1));
    payloads[fileIndex] = std::move(payload);
    payloadPresent.push_back(present);
}

void Install::Index() {
    m_byPath.clear();
    m_byRange.clear();
    for (size_t i = 0; i < m_refs.size(); ++i) {
        const Dfpf::Record& rec = RecordOf(m_refs[i]);
        std::string key = rec.Path();
        std::transform(key.begin(), key.end(), key.begin(), Lower);
        m_byPath.emplace(std::move(key), i);  // first bundle wins
        m_byRange.emplace(std::make_tuple(m_refs[i].fileIndex, rec.offset, uint64_t(rec.storedSize)), i);
    }
}

const RecordRef* Install::Find(std::string_view path) const {
    std::string key(path);
    for (char& c : key) c = c == '\\' ? '/' : Lower(c);
    const auto it = m_byPath.find(key);
    return it == m_byPath.end() ? nullptr : &m_refs[it->second];
}

const RecordRef* Install::At(const Domain::ByteRange& range) const {
    const auto it = m_byRange.find(std::make_tuple(range.fileIndex, range.offset, range.size));
    return it == m_byRange.end() ? nullptr : &m_refs[it->second];
}

std::optional<std::vector<std::byte>> Install::Read(const RecordRef& ref, Services::DiagSink& diags) const {
    const Dfpf::Record& rec = RecordOf(ref);
    if (!payloadPresent[ref.bundle]) {
        Report(diags, "bl.dfpf.payload", rec.Path() + ": " + bundles[ref.bundle].name + ".~p is missing");
        return std::nullopt;
    }
    const Vfs::IFile& file = *payloads[ref.fileIndex];
    if (rec.offset + rec.storedSize > file.Size()) {
        Report(diags, "bl.dfpf.range", rec.Path() + ": stored bytes run past the end of " + bundles[ref.bundle].name + ".~p");
        return std::nullopt;
    }
    std::vector<std::byte> stored(rec.storedSize);
    if (file.ReadAt(rec.offset, stored) != stored.size()) {
        Report(diags, "bl.dfpf.range", rec.Path() + ": short read from " + bundles[ref.bundle].name + ".~p");
        return std::nullopt;
    }
    return Dfpf::Unpack(rec, stored, diags);
}

std::optional<std::vector<std::byte>> Install::Read(std::string_view path, Services::DiagSink& diags) const {
    const RecordRef* ref = Find(path);
    if (!ref) return std::nullopt;
    return Read(*ref, diags);
}

std::shared_ptr<const Install> InstallOf(const Modules::DecodeContext& ctx) {
    return std::static_pointer_cast<const Install>(ctx.moduleState);
}

std::optional<std::vector<std::byte>> UnpackEntry(Modules::DecodeContext& ctx) {
    const auto install = InstallOf(ctx);
    const RecordRef* ref = install ? install->At(ctx.entry.source) : nullptr;
    if (!ref) {
        Report(ctx.diags, "bl.dfpf.record", ctx.entry.name + ": the entry is not a record of this install");
        return std::nullopt;
    }
    const Dfpf::Record& rec = install->RecordOf(*ref);
    ctx.reader.Seek(0);
    const std::vector<std::byte> stored = ctx.reader.ReadAll();
    if (stored.size() != rec.storedSize) {
        Report(ctx.diags, "bl.dfpf.range", ctx.entry.name + ": stored bytes run past the end of the payload");
        return std::nullopt;
    }
    return Dfpf::Unpack(rec, stored, ctx.diags);
}

}
