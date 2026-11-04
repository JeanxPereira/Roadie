#include <Brutal/Module.h>

#include <Brutal/Dfpf.h>
#include <Brutal/Install.h>
#include <Brutal/Texture.h>

#include <Onyx/Core/Modules/DecoderRegistry.h>
#include <Onyx/Core/Modules/Document.h>
#include <Onyx/Core/Services/Paths.h>
#include <Onyx/Core/Vfs/OsFile.h>

#include <algorithm>
#include <cstring>
#include <map>

namespace Brutal {

using namespace Onyx;

namespace {

void Report(Services::DiagSink& diags, Services::Severity severity, std::string code, std::string message) {
    diags.Report({severity, std::move(code), std::move(message), std::nullopt});
}

bool IsHeaderFile(const std::filesystem::path& p) {
    std::string ext = Services::Paths::ToUtf8(p.extension());
    std::transform(ext.begin(), ext.end(), ext.begin(), [](char c) { return (c >= 'A' && c <= 'Z') ? char(c - 'A' + 'a') : c; });
    return ext == ".~h";
}

// The opened .~h plus every other *.~h next to it, in file-name byte order (Python sorted(glob)).
std::vector<std::filesystem::path> SiblingHeaders(const std::filesystem::path& opened) {
    std::vector<std::filesystem::path> out;
    std::error_code ec;
    for (std::filesystem::directory_iterator it(opened.parent_path(), ec), end; !ec && it != end; it.increment(ec)) {
        if (it->is_regular_file(ec) && IsHeaderFile(it->path())) out.push_back(it->path());
    }
    const auto same = [&](const std::filesystem::path& a) { return std::filesystem::equivalent(a, opened, ec); };
    if (std::none_of(out.begin(), out.end(), same)) out.push_back(opened);
    std::sort(out.begin(), out.end(), [](const std::filesystem::path& a, const std::filesystem::path& b) {
        return Services::Paths::ToUtf8(a.filename()) < Services::Paths::ToUtf8(b.filename());
    });
    return out;
}

struct TrieNode {
    std::map<std::string, TrieNode> folders;
    std::vector<Domain::AssetEntry> leaves;
};

std::vector<std::string> Segments(const std::string& name) {
    std::vector<std::string> out;
    size_t start = 0;
    while (start <= name.size()) {
        size_t slash = name.find('/', start);
        if (slash == std::string::npos) slash = name.size();
        if (slash > start) out.push_back(name.substr(start, slash - start));
        start = slash + 1;
    }
    return out;
}

std::vector<Domain::AssetEntry> Emit(TrieNode& node, Types::TypeId folderType) {
    std::vector<Domain::AssetEntry> out = std::move(node.leaves);
    for (auto& [name, child] : node.folders) {
        Domain::AssetEntry folder;
        folder.name = name;
        folder.type = folderType;
        folder.kind = Domain::MediaKind::Container;
        folder.children = Emit(child, folderType);
        out.push_back(std::move(folder));
    }
    std::stable_sort(out.begin(), out.end(), [](const Domain::AssetEntry& a, const Domain::AssetEntry& b) { return a.name < b.name; });
    return out;
}

}

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

void Module::RegisterTypes(Types::TypeRegistrar& registrar) {
    const auto add = [&](const char* key, const char* label, Domain::MediaKind media, Types::Color color) {
        Types::TypeSpec spec;
        spec.key = key;
        spec.label = label;
        spec.media = media;
        spec.icon = Domain::DefaultIcon(media);
        spec.color = color;
        return registrar.Add(spec);
    };
    m_folder = add("folder", "Folder", Domain::MediaKind::Container, {0.85f, 0.70f, 0.30f, 1.0f});
    m_resource = add("resource", "Resource", Domain::MediaKind::Raw, {0.60f, 0.60f, 0.65f, 1.0f});
    m_texture = add("texture", "Texture", Domain::MediaKind::Image, {0.40f, 0.70f, 0.85f, 1.0f});
    m_rsalight = add("rsalight", "Baked light", Domain::MediaKind::Raw, {0.90f, 0.80f, 0.40f, 1.0f});
}

// bl.resource is Raw: the hex view is the default for every game type without a decoder of its own.
void Module::RegisterDecoders(Modules::DecoderRegistry& decoders) {
    decoders.Image(m_texture, Texture::DecodeImage);
}

Modules::ParseResult Module::ParseContainer(Modules::ContainerContext& ctx) {
    auto install = std::make_shared<Install>();
    std::vector<uint32_t> fileIndices;
    for (const std::filesystem::path& headerPath : SiblingHeaders(ctx.path)) {
        auto headerFile = Vfs::OsFile::Open(headerPath);
        if (!headerFile.ok()) {
            Report(ctx.diags, Services::Severity::Error, "bl.dfpf.open", Services::Paths::ToUtf8(headerPath.filename()) + ": " + headerFile.error().message);
            continue;
        }
        Vfs::Reader reader(headerFile.value());
        auto parsed = Dfpf::ParseHeader(reader, headerPath);
        if (!parsed.ok()) {
            Report(ctx.diags, Services::Severity::Error, parsed.error().code, parsed.error().message);
            continue;
        }
        Dfpf::Bundle bundle = std::move(parsed.value());

        std::shared_ptr<const Vfs::IFile> payload;
        bool present = false;
        if (auto opened = Vfs::OsFile::Open(bundle.payloadPath); opened.ok()) {
            payload = opened.value();
            present = true;
        } else {
            payload = std::make_shared<EmptyFile>();
            Report(ctx.diags, Services::Severity::Error, "bl.dfpf.payload",
                   bundle.name + ".~p is missing; every entry of " + bundle.name + " is unreadable");
        }
        const auto fileIndex = uint32_t(ctx.files.size());
        ctx.files.push_back(payload);
        fileIndices.push_back(fileIndex);
        install->Add(std::move(bundle), fileIndex, std::move(payload), present);
    }
    install->Index();
    if (install->bundles.empty()) return {false};
    for (const auto& [first, later] : install->sharedRanges) {
        Report(ctx.diags, Services::Severity::Warning, "bl.dfpf.overlap",
               first + " and " + later + " share one stored range; decoding resolves it to " + first);
    }

    TrieNode root;
    for (uint32_t b = 0; b < install->bundles.size(); ++b) {
        const Dfpf::Bundle& bundle = install->bundles[b];
        const uint32_t fileIndex = fileIndices[b];
        const uint64_t payloadSize = install->payloads[fileIndex]->Size();
        for (const Dfpf::Record& rec : bundle.records) {
            Domain::AssetEntry leaf;
            const std::vector<std::string> parts = Segments(rec.name);
            leaf.name = (parts.empty() ? rec.name : parts.back()) + "." + rec.type;
            leaf.subtitle = rec.type + " \xC2\xB7 " + bundle.name;
            leaf.source = {fileIndex, rec.offset, rec.storedSize};
            leaf.type = m_resource;
            leaf.kind = Domain::MediaKind::Raw;
            if (rec.type == "Texture") {
                const bool light = Texture::IsRsaLight(rec.name);
                leaf.type = light ? m_rsalight : m_texture;
                leaf.kind = light ? Domain::MediaKind::Raw : Domain::MediaKind::Image;
            }
            if (!install->payloadPresent[b]) {
                leaf.flags = Domain::NodeFlags::Failed;
            } else if (rec.offset + rec.storedSize > payloadSize) {
                leaf.flags = Domain::NodeFlags::Failed;
                Report(ctx.diags, Services::Severity::Error, "bl.dfpf.range",
                       rec.Path() + ": stored bytes run past the end of " + bundle.name + ".~p");
            }
            TrieNode* node = &root;
            for (size_t i = 0; i + 1 < parts.size(); ++i) node = &node->folders[parts[i]];
            node->leaves.push_back(std::move(leaf));
        }
    }
    ctx.roots = Emit(root, m_folder);
    ctx.moduleState = install;
    return {true};
}

}
