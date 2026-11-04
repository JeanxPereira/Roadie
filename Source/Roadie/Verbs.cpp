#include "Verbs.h"

#include "InstallPath.h"

#include <Brutal/Install.h>
#include <Brutal/Texture.h>

#include <Onyx/Core/Cli/Run.h>
#include <Onyx/Core/Modules/Workspace.h>
#include <Onyx/Core/Services/Diagnostics.h>
#include <Onyx/Core/Services/Paths.h>

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <map>
#include <memory>
#include <optional>
#include <ostream>
#include <span>
#include <string>
#include <string_view>
#include <utility>

namespace Roadie {

namespace {

using namespace Onyx;
namespace fs = std::filesystem;

char Lower(char c) { return (c >= 'A' && c <= 'Z') ? char(c - 'A' + 'a') : c; }

std::string Lowered(std::string_view s) {
    std::string out(s);
    for (char& c : out) c = Lower(c);
    return out;
}

// Python fnmatch on already lower-cased text: * ? [seq] [!seq]; `*` crosses '/'.
bool Fnmatch(std::string_view pat, std::string_view s) {
    size_t p = 0, i = 0, starP = std::string_view::npos, starI = 0;
    while (i < s.size()) {
        bool ok = false;
        size_t next = p;
        if (p < pat.size() && pat[p] == '*') {
            starP = ++p;
            starI = i;
            continue;
        }
        if (p < pat.size() && pat[p] == '?') {
            ok = true;
            next = p + 1;
        } else if (p < pat.size() && pat[p] == '[') {
            size_t q = p + 1;
            const bool neg = q < pat.size() && pat[q] == '!';
            if (neg) ++q;
            const size_t first = q;
            bool hit = false, closed = false;
            while (q < pat.size()) {
                if (pat[q] == ']' && q > first) {
                    closed = true;
                    break;
                }
                if (q + 2 < pat.size() && pat[q + 1] == '-' && pat[q + 2] != ']') {
                    hit |= pat[q] <= s[i] && s[i] <= pat[q + 2];
                    q += 3;
                } else {
                    hit |= pat[q] == s[i];
                    ++q;
                }
            }
            if (closed) {
                ok = hit != neg;
                next = q + 1;
            } else {  // no closing bracket: '[' is literal
                ok = s[i] == '[';
                next = p + 1;
            }
        } else if (p < pat.size()) {
            ok = pat[p] == s[i];
            next = p + 1;
        }
        if (ok) {
            p = next;
            ++i;
        } else if (starP != std::string_view::npos) {
            p = starP;
            i = ++starI;
        } else {
            return false;
        }
    }
    while (p < pat.size() && pat[p] == '*') ++p;
    return p == pat.size();
}

struct Options {
    std::optional<std::string> pattern, type, out, game;
    bool convert = false;
};

// False (after a message on `err`) for an unknown option or a missing value.
bool ParseArgs(std::span<const std::string_view> args, bool wantPattern, bool wantOut, Options& o, std::ostream& err) {
    const auto value = [&](size_t& i, std::optional<std::string>& slot) {
        if (i + 1 >= args.size()) {
            err << "missing value for " << args[i] << '\n';
            return false;
        }
        slot = std::string(args[++i]);
        return true;
    };
    for (size_t i = 0; i < args.size(); ++i) {
        const std::string_view a = args[i];
        if (a == "--game") {
            if (!value(i, o.game)) return false;
        } else if ((a == "-t" || a == "--type") && wantPattern) {
            if (!value(i, o.type)) return false;
        } else if ((a == "-o" || a == "--out") && wantOut) {
            if (!value(i, o.out)) return false;
        } else if (a == "--convert" && wantOut) {
            o.convert = true;
        } else if (a.size() > 1 && a[0] == '-') {
            err << "unknown option: " << a << '\n';
            return false;
        } else if (wantPattern && !o.pattern) {
            o.pattern = std::string(a);
        } else {
            err << "unexpected argument: " << a << '\n';
            return false;
        }
    }
    if (wantOut && (!o.out || !o.pattern)) {
        err << "extract needs GLOB and -o DIR\n";
        return false;
    }
    return true;
}

std::shared_ptr<const Brutal::Install> OpenInstall(Modules::Workspace& ws, const Options& o, std::ostream& err) {
    const fs::path given = o.game ? Services::Paths::FromUtf8(*o.game) : DefaultInstall();
    const auto header = ResolveInstallPath(given);
    if (!header) {
        err << "no Brutal Legend bundles at " << Services::Paths::ToUtf8(given) << " (use --game or BL_GAME_DIR)\n";
        return nullptr;
    }
    const Modules::DocumentId id = ws.Open(*header);
    Modules::Document* doc = id ? ws.Get(id) : nullptr;
    auto install = doc ? std::static_pointer_cast<const Brutal::Install>(doc->moduleState) : nullptr;
    if (!install) err << "cannot open " << Services::Paths::ToUtf8(*header) << '\n';
    return install;
}

// The records of the install, once each, from the bundle that wins the path.
template <typename F>
void ForEachRecord(const Brutal::Install& install, F&& f) {
    for (uint32_t b = 0; b < install.bundles.size(); ++b) {
        const auto& records = install.bundles[b].records;
        for (uint32_t r = 0; r < records.size(); ++r) {
            const Brutal::RecordRef* ref = install.Find(records[r].Path());
            if (ref && ref->bundle == b && ref->record == r) f(records[r], *ref);
        }
    }
}

bool Matches(const Brutal::Dfpf::Record& rec, const Options& o, const std::string& pat) {
    if (o.type && rec.type != *o.type) return false;
    return Fnmatch(pat, Lowered(rec.Path())) || Fnmatch(pat, Lowered(rec.name));
}

int Types(Modules::Workspace& ws, const Cli::VerbTable&, std::span<const std::string_view> args, std::ostream& out,
          std::ostream& err) {
    Options o;
    if (!ParseArgs(args, false, false, o, err)) return Cli::kUsage;
    const auto install = OpenInstall(ws, o, err);
    if (!install) return Cli::kNoModule;
    std::map<std::string, size_t> counts;
    ForEachRecord(*install, [&](const Brutal::Dfpf::Record& rec, const Brutal::RecordRef&) { ++counts[rec.type]; });
    std::vector<std::pair<std::string, size_t>> rows(counts.begin(), counts.end());  // by name
    std::stable_sort(rows.begin(), rows.end(), [](const auto& a, const auto& b) { return a.second > b.second; });
    for (const auto& [type, n] : rows) {
        char head[32];
        std::snprintf(head, sizeof head, "%7zu ", n);
        out << head << type << '\n';
    }
    return Cli::kOk;
}

int Ls(Modules::Workspace& ws, const Cli::VerbTable&, std::span<const std::string_view> args, std::ostream& out,
       std::ostream& err) {
    Options o;
    if (!ParseArgs(args, true, false, o, err)) return Cli::kUsage;
    const auto install = OpenInstall(ws, o, err);
    if (!install) return Cli::kNoModule;
    const std::string pat = Lowered(o.pattern.value_or("*"));
    std::vector<std::string> paths;
    ForEachRecord(*install, [&](const Brutal::Dfpf::Record& rec, const Brutal::RecordRef&) {
        if (Matches(rec, o, pat)) paths.push_back(rec.Path());
    });
    std::sort(paths.begin(), paths.end());
    for (const std::string& p : paths) out << p << '\n';
    return Cli::kOk;
}

// A resource path stays inside the output folder: no "..", drive, or backslash segment.
bool SafePath(const std::string& path) {
    if (path.empty() || path[0] == '/') return false;
    size_t start = 0;
    while (start <= path.size()) {
        size_t slash = path.find('/', start);
        if (slash == std::string::npos) slash = path.size();
        const std::string_view seg(path.data() + start, slash - start);
        if (seg == ".." || seg.find_first_of(":\\") != std::string_view::npos) return false;
        start = slash + 1;
    }
    return true;
}

int Extract(Modules::Workspace& ws, const Cli::VerbTable&, std::span<const std::string_view> args, std::ostream& out,
            std::ostream& err) {
    Options o;
    if (!ParseArgs(args, true, true, o, err)) return Cli::kUsage;
    const auto install = OpenInstall(ws, o, err);
    if (!install) return Cli::kNoModule;
    const std::string pat = Lowered(*o.pattern);
    const fs::path root = Services::Paths::FromUtf8(*o.out);

    std::vector<std::pair<Brutal::Dfpf::Record, Brutal::RecordRef>> picked;
    ForEachRecord(*install, [&](const Brutal::Dfpf::Record& rec, const Brutal::RecordRef& ref) {
        if (Matches(rec, o, pat)) picked.emplace_back(rec, ref);
    });

    size_t written = 0, failed = 0;
    for (const auto& [rec, ref] : picked) {
        std::string rel = rec.Path();
        if (!SafePath(rel)) {
            err << rel << ": unsafe path, skipped\n";
            ++failed;
            continue;
        }
        Services::DiagSink diags;
        auto bytes = install->Read(ref, diags);
        if (!bytes) {
            const auto d = diags.Snapshot();
            err << rel << ": " << (d.empty() ? "unreadable" : d.front().message) << '\n';
            ++failed;
            continue;
        }
        std::span<const std::byte> data = *bytes;
        if (o.convert && rec.type == "Texture") {
            Services::DiagSink texDiags;  // not a DDS (an rsalight): written as stored
            if (const auto dds = Brutal::Texture::Dds(*bytes, texDiags, rec.Path())) {
                data = *dds;
                rel = rec.name + ".dds";
            }
        }
        const fs::path target = root / Services::Paths::FromUtf8(rel);
        std::error_code ec;
        fs::create_directories(target.parent_path(), ec);
        std::ofstream f(target, std::ios::binary);
        if (f) f.write(reinterpret_cast<const char*>(data.data()), std::streamsize(data.size()));
        if (!f || !f.flush()) {
            err << rel << ": cannot write " << Services::Paths::ToUtf8(target) << '\n';
            ++failed;
            continue;
        }
        ++written;
    }
    out << written << " written\n";
    return failed ? Cli::kPartial : Cli::kOk;
}

}

std::vector<Onyx::Cli::Verb> Verbs() {
    return {
        {"types", "[--game DIR]", Types},
        {"ls", "[GLOB] [-t TYPE] [--game DIR]", Ls},
        {"extract", "GLOB -o DIR [--convert] [-t TYPE] [--game DIR]", Extract},
    };
}

}
