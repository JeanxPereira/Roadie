# Roadie Plan 1: Foundation (Step 0, C++ scaffold, DFPF, Texture) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One native `roadie` binary on OnyxSDK 2.0.0 that opens the Brütal Legend install as one document, browses all 71,095 resources, shows every DDS texture, and proves DFPF and Texture with C++ corpus gates at the Python numbers, while the Python decoder moves into the Blender extension and stays honest through a parity gate.

**Architecture:** `Source/Brutal` is an Onyx module (links `Onyx::Core` only): opening any `.~h` loads every sibling `.~h` into an `Install` kept as module state, builds a path tree lazily backed by byte ranges in the `.~p` files, and decoders inflate and decode on demand. `Source/Roadie` is the `Onyx::Shell` host plus Roadie's own CLI verbs. Corpus gates are C++ executables that drive the real `Workspace`; `check.py` stays the single verdict.

**Tech Stack:** C++26, clang-cl 23 (LLVM at `C:\Program Files\LLVM\bin`), CMake 4 + Ninja Multi-Config, OnyxSDK `v2.0.0` (FetchContent), zlib 1.3.1, doctest 2.4.11; Python 3.11 for project tooling and the extension.

**Spec:** `Docs/Specs/2026-11-01-roadie-onyx-design.md` (read it first; this is plan 1 of the port).

**Later plans (one each, written when the previous one lands):** 2 Mesh + Rig; 3 Material, TextObj, Shaders, RsaLight (+ material viewer); 4 Anim; 5 UI chain (Image, Gfx, GfxSvg, Ttf, `ui` verbs, viewers, `readme_art.py` switch); 6 final cut (delete the remaining Python product code and gates, Docs/README/CLAUDE.md to the final layout). Morph viewing and float tracks wait for OnyxSDK 2.1 (spec, "Decided").

## Global Constraints

- The game and `BrutalLegend.exe` are the authorities; every format fact goes at the top of its decoder source and in `Docs/formats.md`, with its gate (and IDA address when it came from code).
- A gate must bite: every C++ corpus gate is mutation-checked once and the mutation is recorded in the gate's header comment.
- No gate loses a number: a C++ gate replaces a Python gate only when it proves at least the same counts over the same corpus.
- Exactly one Python decoder in the repo at all times: `Blender/BrutalLegend/Brutal/` (after Task 1).
- The extension never depends on the Roadie binary.
- OnyxSDK is consumed unpatched at tag `v2.0.0`. If something does not compile or is missing, stop and report; never edit the fetched copy.
- `Source/Brutal` links `Onyx::Core` only (no GPU on its include path).
- Folders and C++ files PascalCase; the extension id `brutal_legend` stays lowercase.
- Module rules from OnyxSDK `docs/modules.md`: report, never throw; distrust every count and offset; decoders are free functions holding no raw pointer to the module.
- Evidence stays out of git (`.evidence/`); corpus gates need the install (`BL_GAME_DIR`, default `D:\ProgramLibrary\Steam\steamapps\common\BrutalLegend`) and never run in CI.
- Commits: plain imperative subject like the repo's history, no AI attribution of any kind.
- `python check.py` is the verdict (exit code); `python check.py --blender` when the extension is touched.

## Review Focus

1. A `.~h` whose `.~p` is missing or shorter than its records claim: the open still succeeds, the affected entries are flagged `Failed` with a `bl.dfpf.*` diagnostic, nothing throws. (Task 3, `MissingPayload`, `RecordPastPayloadEnd`)
2. A zlib payload that is corrupt or inflates to a size other than header + data: `bl.dfpf.inflate` diagnostic and no payload, not a partial buffer. (Task 3, `CorruptZlib`)
3. An install path with non-ASCII characters (`Brütal Legend` is a plausible folder name): opens, lists and extracts. (Task 7, `NonAsciiInstallPath`)
4. Resource paths given with backslashes or other case (`Characters\Bipeds\...`): resolve like the Python `Library.read` (lower-case, `\` → `/`). (Task 3, `PathLookupNormalizes`)
5. A single `.~h` copied alone into another folder: opens scoped to itself; nothing reaches into the real install. (Task 3, `LoneBundleIsScoped`)

## Measured facts this plan pins (2026-11-03, the Steam install)

- `Win/Packs` holds **21** `.~h` files (`Docs/formats.md` says 20; it is wrong and Task 4 fixes it). Records: **71,095**; compression 4 (raw) **10,900**, 8 (zlib) **60,195**, 12 (xmem) 0. No resource path appears in two bundles.
- Texture: **10,672** records, all zlib. 16 are `lighting/textures/rsalights/*` (not DDS). The other **10,656** are DDS: DXT5 **5,405** (3,663 with mips), DXT1 **1,917**, uncompressed R5G6B5 **1,667** (engine format 5, masks `f800/07e0/001f`), uncompressed A4R4G4B4 **1,667** (engine format 2, masks `0f00/00f0/000f/f000`); the two 16-bit sets are all under `worlds/`.

---

### Task 1: Step 0, the Python decoder moves into the extension

**Files:**
- Move: `Brutal/` → `Blender/BrutalLegend/Brutal/` (`git mv`, contents unchanged)
- Modify: every `Tests/corpus_*.py`, `Tests/Blender/*.py` that inserts the repo root into `sys.path` (insert `Blender/BrutalLegend` instead); `Tools/readme_art.py`, `Tools/Shaders/disasm.py`, `Tools/Shaders/idaq.py` if it imports `Brutal`; `Tools/build_addon.py`; `.github/workflows/ci.yml`; `CLAUDE.md`, `README.md`, `Docs/formats.md`, `Docs/Formats/*.md` path references (`Brutal/x.py` → `Blender/BrutalLegend/Brutal/x.py`)
- Create: `Tools/brutal.py` (two lines: put `Blender/BrutalLegend` on `sys.path`, `runpy.run_module("Brutal", run_name="__main__")`), so the Python CLI keeps working as `python Tools/brutal.py ...` until plan 5 replaces it

**Interfaces:**
- Produces: the only Python decoder at `Blender/BrutalLegend/Brutal/`, importable as `Brutal` with `Blender/BrutalLegend` on `sys.path`. The extension code is unchanged (it already imports `.Brutal`).

- [ ] **Step 1: Record the extension archive before the move**

Run: `python Tools/build_addon.py && python -c "import zipfile,glob;print('\n'.join(sorted(zipfile.ZipFile(glob.glob('dist/brutal_legend-*.zip')[0]).namelist())))" > .evidence/addon-before.txt`

- [ ] **Step 2: Move and fix every import and reference**

`build_addon.py` walks `Blender/BrutalLegend` alone (drop the `LIB` vendoring pass, keep skipping `__pycache__`). `ci.yml` compiles `Blender Tools Tests check.py` and runs the import check with `PYTHONPATH=Blender/BrutalLegend`. `grep -rn "Brutal/" --include=*.md --include=*.py --include=*.yml --include=*.sh .` returns only the new paths.

- [ ] **Step 3: Verify the archive is byte-for-byte the same list and the gates pass**

Run: `python Tools/build_addon.py && python -c "...same..." > .evidence/addon-after.txt && diff .evidence/addon-before.txt .evidence/addon-after.txt`
Expected: no diff.
Run: `python check.py --blender`
Expected: `ALL GATES PASS`, exit 0, and `.evidence/renders/check.png` shows the avatar as before.

- [ ] **Step 4: Commit**

```bash
git add -A Blender Brutal Tests Tools .github CLAUDE.md README.md Docs check.py
git commit -m "Move the Python decoder into the Blender extension"
```

---

### Task 2: C++ scaffold, empty module, `roadie` binary, `check.py` builds

**Files:**
- Create: `CMakeLists.txt`, `CMakePresets.json`, `cmake/Deps.cmake`
- Create: `Source/Brutal/CMakeLists.txt`, `Source/Brutal/include/Brutal/Module.h`, `Source/Brutal/Module.cpp`
- Create: `Source/Roadie/CMakeLists.txt`, `Source/Roadie/Main.cpp`
- Create: `Tests/Unit/CMakeLists.txt`, `Tests/Unit/Main.cpp` (doctest main), `Tests/Unit/ModuleTests.cpp`
- Modify: `check.py`, `.gitignore` (`build/`)

**Interfaces:**
- Produces: `class Brutal::Module final : public Onyx::Modules::IGameModule` with `Info()` = `{id "bl", displayName "Brütal Legend", hints {"brutal", "bl"}, openFilters {{"Brütal Legend bundle", {".~h"}}}}`; `Probe` returns 95 when the header starts with `dfpf` and byte 4 is 5, 0 otherwise, reason `"DFPF v5"`. CMake targets `Brutal::Module` (static lib), `roadie` (exe), `RoadieUnit` (doctest exe, ctest name `Unit`).

- [ ] **Step 1: Write the failing test**

`Tests/Unit/ModuleTests.cpp`, `TEST_CASE("Probe")`: header `dfpf\x05...` → `confidence == 95`; `dfpf\x04` → 0; `DFPF\x05` → 0; empty header → 0.

- [ ] **Step 2: Build files**

- `CMakeLists.txt`: `cmake_minimum_required(VERSION 4.0)`, `project(Roadie CXX C)`, `CMAKE_CXX_STANDARD 26` required, `set(ONYX_WITH_MEDIA OFF)` before the fetch (Roadie plays no audio yet), `include(cmake/Deps.cmake)`, `add_subdirectory` Source/Brutal, Source/Roadie, Tests/Unit (Tests/Corpus arrives in Task 4), `enable_testing()`.
- `cmake/Deps.cmake`: FetchContent `OnyxSDK` (`GIT_TAG v2.0.0`), `zlib` (`madler/zlib`, `GIT_TAG v1.3.1`, link the static `zlibstatic`), `doctest` (`GIT_TAG v2.4.11`, only `if(NOT TARGET doctest::doctest)`).
- `CMakePresets.json`: configure preset `windows` (generator `Ninja Multi-Config`, `binaryDir` `${sourceDir}/build/windows`, `CMAKE_C_COMPILER`/`CMAKE_CXX_COMPILER` `clang-cl`, Windows-only condition); build presets `windows-debug` / `windows-release` (configurations Debug / Release); test preset `windows-debug`.
- `Source/Roadie/Main.cpp`: the `MinimalViewer` shape from OnyxSDK (`Examples/MinimalViewer/Main.cpp`): `Shell({.appName = "Roadie", .configDir = Paths::UserConfig("Roadie")})`, `AddModule(std::make_unique<Brutal::Module>())`, `Exchange::AddExporters` on `shell.Verbs()`, `return shell.Run(argc, argv)`. CMake: link `Onyx::Shell Onyx::Exchange Brutal::Module`, `onyx_install_assets(roadie)`.

- [ ] **Step 3: `check.py` drives the C++ build**

Keep the Python gate list and `--blender`. Add before them: locate `vcvars64.bat` through `vswhere` exactly as OnyxSDK `tools/check.py` `find_vcvars` does; prepend `C:\Program Files\LLVM\bin` (or `BL_LLVM_DIR`) to `PATH`; run inside vcvars `cmake --preset windows`, `cmake --build --preset windows-debug`, `ctest --preset windows-debug -LE corpus`. A failed step is a failed gate named after the step.

- [ ] **Step 4: Run to verify it fails, then passes**

Run: `python check.py` with `Probe` returning 0. Expected: FAIL at `ctest` (Unit). Implement `Probe`. Run again. Expected: `ALL GATES PASS`.
Run: `build\windows\Debug\roadie.exe --help`. Expected: exit 0 and the stock verbs listed.
If OnyxSDK v2.0.0 does not compile under clang-cl, stop here and report the first error (Global Constraints).

- [ ] **Step 5: Commit**

```bash
git add CMakeLists.txt CMakePresets.json cmake Source Tests/Unit check.py .gitignore
git commit -m "Roadie scaffold on OnyxSDK 2.0.0: empty Brutal module, roadie binary, check.py builds"
```

---

### Task 3: DFPF bundles and the install as one document

**Files:**
- Create: `Source/Brutal/include/Brutal/Dfpf.h`, `Source/Brutal/Dfpf.cpp` (header comment = the layout block of today's `dfpf.py` docstring, verbatim facts)
- Create: `Source/Brutal/include/Brutal/Install.h`, `Source/Brutal/Install.cpp`
- Modify: `Source/Brutal/Module.cpp` (types, `ParseContainer`)
- Create: `Tests/Unit/Support/DfpfWriter.h`, `Tests/Unit/Support/DfpfWriter.cpp` (builds `.~h`/`.~p` pairs in a temp dir: the inverse of the record bitfields, raw or zlib payloads, plus knobs to break them)
- Create: `Tests/Unit/DfpfTests.cpp`, `Tests/Unit/Golden/install.golden.json`

**Interfaces:**
- Produces (`Brutal/Dfpf.h`, namespace `Brutal::Dfpf`):
  - `enum class Compression : uint8_t { Raw = 4, Zlib = 8, Xmem = 12 };`
  - `struct Record { uint32_t index; std::string name; std::string type; uint64_t offset; uint32_t storedSize; uint32_t dataSize; uint32_t headerSize; Compression compression; uint64_t UnpackedSize() const; std::string Path() const; /* name + "." + type */ };`
  - `struct Bundle { std::string name; std::filesystem::path headerPath, payloadPath; std::vector<Record> records; };`
  - `Onyx::Result<Bundle> ParseHeader(Onyx::Vfs::Reader& header, const std::filesystem::path& headerPath);` (big-endian; fails with code `bl.dfpf.magic`, `bl.dfpf.version`, `bl.dfpf.truncated`)
  - `std::optional<std::vector<std::byte>> Unpack(const Record&, std::span<const std::byte> stored, Onyx::Services::DiagSink&);` (raw: must be exactly `UnpackedSize()` bytes; zlib: inflate to exactly `UnpackedSize()`, else `bl.dfpf.inflate`; xmem: `bl.dfpf.xmem`)
- Produces (`Brutal/Install.h`, namespace `Brutal`):
  - `struct RecordRef { uint32_t bundle; uint32_t record; uint32_t fileIndex; };`
  - `class Install` with `std::vector<Dfpf::Bundle> bundles;` `std::vector<std::shared_ptr<const Onyx::Vfs::IFile>> payloads;` (indexed by `RecordRef::fileIndex`, the same index as the document's `files`), `const RecordRef* Find(std::string_view path) const;` (lower-case, `\` → `/`, first bundle in sorted order wins), `const RecordRef* At(const Onyx::Domain::ByteRange&) const;`, `const Dfpf::Record& RecordOf(const RecordRef&) const;`, `std::optional<std::vector<std::byte>> Read(const RecordRef&, Onyx::Services::DiagSink&) const;`, `std::optional<std::vector<std::byte>> Read(std::string_view path, Onyx::Services::DiagSink&) const;`
  - `std::shared_ptr<const Install> InstallOf(const Onyx::Modules::DecodeContext&);`
  - `std::optional<std::vector<std::byte>> UnpackEntry(Onyx::Modules::DecodeContext&);` (the entry's record, inflated; every later decoder starts here)
- Module types: `bl.folder` (Container), `bl.resource` (Raw, the default for any type without its own decoder; the game type goes in `AssetEntry::subtitle` as `"<Type> · <bundle>"`). Tree: one `bl.folder` per path segment, leaf name `<last segment>.<Type>`, children sorted by name, `source = {fileIndex of its .~p, offset, storedSize}`.
- `ParseContainer`: the opened `.~h` plus every other `*.~h` in its directory, sorted by file name byte order (the Python `sorted(glob)`); each bundle's `.~p` appended to `ctx.files`; the `Install` stored in `ctx.moduleState`. A bundle that fails `ParseHeader` is reported and skipped; a missing `.~p` flags that bundle's entries `Failed` (`bl.dfpf.payload`); a record whose `offset + storedSize` exceeds its `.~p` size is flagged `Failed` (`bl.dfpf.range`).

- [ ] **Step 1: Write the failing tests** (`Tests/Unit/DfpfTests.cpp`, each over a `DfpfWriter` install in a temp dir, opened through a real `Onyx::Modules::Workspace` with the module added)

- `RecordBitfields`: one bundle with records at boundary values (`dataSize = 0xFFFFFF`, `headerSize = 0x3FFFF`, `offset = (1<<29)-1`, type index 2 of 3) parse back to exactly those values.
- `RawAndZlibUnpack`: raw and zlib records unpack to the writer's bytes; size = header + data.
- `CorruptZlib`: flipped bytes in a zlib stream → no payload, one `bl.dfpf.inflate` error naming the entry.
- `MissingPayload`: `.~p` deleted → open ok, every entry of that bundle `Failed`, one `bl.dfpf.payload`.
- `RecordPastPayloadEnd`: one record beyond the `.~p` end → that entry `Failed` with `bl.dfpf.range`, its neighbours fine.
- `SiblingsJoinOneDocument`: three bundles `a.~h b.~h c.~h`, opening `b.~h` yields entries from all three; a path present in `a` and `c` resolves to `a`.
- `LoneBundleIsScoped`: one `.~h`/`.~p` copied into an empty folder → only its own entries; `Install::Read` of another bundle's path returns nothing.
- `PathLookupNormalizes`: `Install::Find("Characters\\Bipeds\\X.Mesh")` finds `characters/bipeds/x.Mesh`.
- `TreeGolden`: `TestKit::SnapshotTree` of the three-bundle install equals `Tests/Unit/Golden/install.golden.json` (`TestKit::CompareTreeGolden`; refresh with `ONYX_UPDATE_GOLDENS=1` once, then review the JSON by eye).

- [ ] **Step 2: Run to verify they fail**

Run: `python check.py`. Expected: FAIL at `ctest` with the new cases failing.

- [ ] **Step 3: Implement `Dfpf.cpp`, `Install.cpp` and the module's `RegisterTypes`/`ParseContainer`**

The record bitfields are the table in the `dfpf.py` docstring (bytes 0..3 `>> 8`, 3..6 `>> 11`, 4..7 `(>> 1) & 0x3FFFF`, 8..11 `>> 3`, 11..14 `(<< 5) >> 9` in 32 bits, 14..17 `((<< 4) >> 24) >> 1`, byte 15 `& 15`). Type names: `u32 len; char[len]; u8[12]`, trimmed of spaces and trailing NULs. Names: NUL-terminated latin-1 at name directory + offset, converted to UTF-8.

- [ ] **Step 4: Run to verify they pass**

Run: `python check.py`. Expected: `ALL GATES PASS`.

- [ ] **Step 5: Commit**

```bash
git add Source/Brutal Tests/Unit
git commit -m "DFPF v5 bundles in C++: every bundle of an install as one document"
```

---

### Task 4: DFPF corpus gate in C++ replaces `Tests/corpus_dfpf.py`

**Files:**
- Create: `Tests/Corpus/CMakeLists.txt` (one executable per gate, ctest label `corpus`), `Tests/Corpus/Support/Corpus.h`, `Tests/Corpus/Support/Corpus.cpp`, `Tests/Corpus/DfpfGate.cpp`
- Modify: `CMakeLists.txt` (add `Tests/Corpus`), `check.py` (run `ctest --preset windows-debug -L corpus` when `Win/Packs` exists; drop `Tests/corpus_dfpf.py` from `GATES`)
- Delete: `Tests/corpus_dfpf.py`
- Modify: `Docs/formats.md` (bundle row: 21 bundles, decoder `Source/Brutal/Dfpf.cpp`, gate `Tests/Corpus/DfpfGate.cpp`; intro line "20 bundles" → 21)

**Interfaces:**
- Produces (`Tests/Corpus/Support/Corpus.h`, namespace `Corpus`): `std::filesystem::path PacksDir();` (`BL_GAME_DIR` or the default, + `Win/Packs`); `struct Opened { Onyx::Modules::Workspace ws; Onyx::Modules::DocumentId id; };` `std::unique_ptr<Opened> OpenInstall();` (first `*.~h` of `PacksDir()`, through a real Workspace with `Brutal::Module`); `void ForEachLeaf(const Onyx::Modules::Document&, const std::function<void(const Onyx::Domain::AssetEntry&)>&);` `int Verdict(const std::map<std::string, uint64_t>& counts, const std::map<std::string, uint64_t>& bad, const std::map<std::string, std::string>& examples);` (prints the counts, `bad N`, up to one example per failure kind, returns 0/1; the same output shape as the Python gates).

- [ ] **Step 1: Write the gate**

For every leaf of the opened install: `UnpackEntry`-equivalent through `Install::Read` returns exactly `UnpackedSize()` bytes, and raw records store exactly that many. Assert totals: bundles **21**, records **71,095**, `comp4` **10,900**, `comp8` **60,195**, `bad 0`, zero diagnostics of severity Error on the document. Header comment lists these numbers and the mutation of Step 2.

- [ ] **Step 2: Mutation check**

Change the header-size mask in `Dfpf.cpp` from `0x3FFFF` to `0x1FFFF`, run `ctest --preset windows-debug -L corpus -R Dfpf`. Expected: FAIL with size mismatches. Revert. Expected: PASS.

- [ ] **Step 3: Run the whole verdict**

Run: `python check.py`. Expected: `ALL GATES PASS`, and the DFPF gate line shows the numbers above.

- [ ] **Step 4: Commit**

```bash
git add Tests/Corpus CMakeLists.txt check.py Docs/formats.md
git rm Tests/corpus_dfpf.py
git commit -m "DFPF corpus gate in C++: 71,095/71,095 records unpack to header + data"
```

---

### Task 5: Texture decoder in the Image slot

**Files:**
- Create: `Source/Brutal/include/Brutal/Texture.h`, `Source/Brutal/Texture.cpp` (header comment = today's `texture.py` docstring plus the 16-bit formats measured above)
- Modify: `Source/Brutal/Module.cpp` (types `bl.texture` Image, `bl.rsalight` Raw; `Texture` records under `lighting/textures/rsalights/` get `bl.rsalight`)
- Create: `Tests/Unit/Support/TextureWriter.h`, `Tests/Unit/TextureTests.cpp`

**Interfaces:**
- Produces (`Brutal/Texture.h`, namespace `Brutal::Texture`):
  - `constexpr size_t kHeaderSize = 0x24;`
  - `struct Info { uint32_t engineFormat, width, height, mips; };` `std::optional<Info> ReadInfo(std::span<const std::byte> resource);`
  - `bool IsRsaLight(std::string_view resourceName);`
  - `std::optional<std::span<const std::byte>> Dds(std::span<const std::byte> resource, Onyx::Services::DiagSink&, std::string_view name);` (`rtxT` at 0x20, `DDS ` at 0x28, `0x28 + u32@0x24 == size`; codes `bl.texture.magic`, `bl.texture.size`)
  - `std::optional<Onyx::Domain::Texture> ToImage(std::span<const std::byte> dds, std::string name, Onyx::Services::DiagSink&);` top mip only: FourCC `DXT1` → `Bc1`, `DXT5` → `Bc3`; uncompressed 16-bit R5G6B5 and A4R4G4B4 (by pixel-format masks) → `Rgba8`, expanding by bit replication (5-bit `v<<3|v>>2`, 6-bit `v<<2|v>>4`, 4-bit `v*17`; R5G6B5 alpha 255); anything else → `bl.texture.format` naming the FourCC or masks.
  - `std::optional<Onyx::Domain::Texture> DecodeImage(Onyx::Modules::DecodeContext&);` (registered on `bl.texture`)

- [ ] **Step 1: Write the failing tests**

`DxtTopMip` (DXT1 and DXT5 with 3 mips: pixels = exactly the top level, `ExpectedByteSize` holds), `Rgb565Expands` (pixel `0xF800` → `{255,0,0,255}`, `0x07E0` → `{0,255,0,255}`, `0x001F` → `{0,0,255,255}`), `Argb4444Expands` (`0x0F00` → `{255,0,0,0}`, `0x00F0` → `{0,255,0,0}`, `0x000F` → `{0,0,255,0}`, `0xF000` → `{0,0,0,255}`, `0x8421` → `{68,34,17,136}`), `SizeMismatch` (`0x28 + n != size` → `bl.texture.size`, no image), `UnknownFormat` (FourCC `ATI2` → `bl.texture.format`), `RsaLightIsRaw` (a Texture record under `lighting/textures/rsalights/` gets type `bl.rsalight`, kind Raw).

- [ ] **Step 2: Run to verify they fail**

Run: `python check.py`. Expected: FAIL at `ctest`.

- [ ] **Step 3: Implement `Texture.cpp` and the registrations**

- [ ] **Step 4: Run to verify they pass, then look**

Run: `python check.py`. Expected: `ALL GATES PASS`.
Run: `build\windows\Debug\roadie.exe "%BL_GAME_DIR%\Win\Packs\00Startup.~h"`, open one DXT1, one DXT5 and one `worlds/` 16-bit texture. Expected: they display; save a screenshot to `.evidence/renders/plan1-texture.png`.

- [ ] **Step 5: Commit**

```bash
git add Source/Brutal Tests/Unit
git commit -m "Texture in C++: DXT1/DXT5 and 16-bit DDS into the Onyx image viewer"
```

---

### Task 6: Texture corpus gate in C++ replaces the Python texture check

**Files:**
- Create: `Tests/Corpus/TextureGate.cpp`
- Modify: `Tests/corpus_rig_tex.py` (drop the Texture branch and its import; it keeps Rig and Mesh↔Rig until plan 2)
- Modify: `Docs/formats.md` (Texture row: decoder `Source/Brutal/Texture.cpp`, gate `Tests/Corpus/TextureGate.cpp`, the per-format counts)

- [ ] **Step 1: Write the gate**

For every `bl.texture` leaf: `Dds` succeeds and `DecodeImage` returns a valid image whose byte size is `ExpectedByteSize(format, w, h)` and whose `w`/`h` equal `ReadInfo`'s. Assert: Texture records **10,672**; `bl.rsalight` **16**; DDS **10,656** (DXT5 **5,405**, DXT1 **1,917**, R5G6B5 **1,667**, A4R4G4B4 **1,667**); `bad 0`.

- [ ] **Step 2: Mutation check**

Change the `Dds` size check to `0x24 + n`. Expected: FAIL with 10,656 size errors. Revert. Expected: PASS. Record it in the header comment.

- [ ] **Step 3: Run the whole verdict**

Run: `python check.py`. Expected: `ALL GATES PASS`; `corpus_rig_tex.py` still prints its rig and mesh~rig counts unchanged (302 rigs).

- [ ] **Step 4: Commit**

```bash
git add Tests/Corpus Tests/corpus_rig_tex.py Docs/formats.md
git commit -m "Texture corpus gate in C++: 10,656 DDS decode, 16 rsalights set apart"
```

---

### Task 7: Roadie verbs `types`, `ls`, `extract`, and opening the install by folder

**Files:**
- Create: `Source/Roadie/Verbs.h`, `Source/Roadie/Verbs.cpp`, `Source/Roadie/InstallPath.h`, `Source/Roadie/InstallPath.cpp`
- Modify: `Source/Roadie/Main.cpp`
- Create: `Tests/Unit/VerbTests.cpp`, `Tests/Unit/Golden/Cli/*.txt`

**Interfaces:**
- Produces:
  - `std::optional<std::filesystem::path> Roadie::ResolveInstallPath(const std::filesystem::path& p);` a `.~h`/`.~p` → its `.~h`; a folder containing `Win/Packs` or holding `*.~h` → its first `*.~h` in byte order; else nullopt.
  - `std::filesystem::path Roadie::DefaultInstall();` (`BL_GAME_DIR` or the default path).
  - `std::vector<Onyx::Cli::Verb> Roadie::Verbs();` with, mirroring `python -m Brutal` today:
    - `types [--game DIR]`: `<count right-aligned in 7> <Type>`, most common first, ties by name.
    - `ls [GLOB] [-t TYPE] [--game DIR]`: one resource path per line, sorted; GLOB matches the path or the name, case-insensitive, fnmatch rules.
    - `extract GLOB -o DIR [--convert] [-t TYPE] [--game DIR]`: writes each unpacked resource to `DIR/<path>`; with `--convert`, Texture becomes `DIR/<name>.dds` (the bare DDS); prints `<n> written` and reports failures per entry without stopping.
  - `Main.cpp`: when the first argument is an existing folder, replace it with `ResolveInstallPath` (UTF-8 through `Services::Paths`), then `shell.Verbs().Add(Roadie::Verbs())`.

- [ ] **Step 1: Write the failing tests**

CLI goldens over a `DfpfWriter` install, captured as OnyxSDK's `Tests/Cli/PrismVerbs.cpp` does (`Cli::Run` over a `VerbTable`, temp path replaced by `<game>`): `types`, `ls`, `ls -t Texture`, `ls "*avatar*"`, `extract "*" -o <tmp> --convert` (then the written `.dds` equals the writer's DDS bytes). `NonAsciiInstallPath`: the same install under a folder named `Brütal Legend` → `ls` output identical. `ResolveFolder`: game folder, `Win/Packs`, a `.~p` all resolve to the same `.~h`.

- [ ] **Step 2: Run to verify they fail**

Run: `python check.py`. Expected: FAIL at `ctest`.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run to verify they pass, and compare with Python on the real install**

Run: `python check.py`. Expected: `ALL GATES PASS`.
Run: `build\windows\Debug\roadie.exe types > .evidence/types-cpp.txt` and `python Tools/brutal.py types > .evidence/types-py.txt`, `diff` them. Expected: identical.

- [ ] **Step 5: Commit**

```bash
git add Source/Roadie Tests/Unit
git commit -m "Roadie verbs types, ls, extract; open the install by folder"
```

---

### Task 8: Parity gate between the C++ module and the extension's Python decoder

**Files:**
- Modify: `Source/Roadie/Verbs.cpp` (verb `digest`)
- Create: `Tests/parity.py`
- Modify: `check.py` (run the parity gate after the corpus gates, when the install exists)
- Modify: `Docs/formats.md` (a short "Parity" paragraph: what the digest covers, per plan)

**Interfaces:**
- Produces: `roadie digest [--game DIR]` writes UTF-8 lines sorted by path, tab-separated:
  - every record: `R <path> <compression> <headerSize> <dataSize>`
  - every DDS texture: `T <path> <engineFormat> <width> <height> <mips> <len(dds)> <crc32(dds) as 8 lower-case hex>`
  The digest grows one line kind per format in later plans; the line kinds and fields are documented in `Docs/formats.md`.
- `Tests/parity.py`: imports `Brutal` from `Blender/BrutalLegend` (stdlib only: `zlib.crc32`), writes the same lines from `Library`, `Entry`, `texture.info`, `texture.dds`, runs the binary, compares line by line, prints the first 5 differences and the counts per line kind, exits 1 on any difference.

- [ ] **Step 1: Write `Tests/parity.py` and run it before the verb exists**

Expected: FAIL (`roadie digest` unknown verb).

- [ ] **Step 2: Implement `digest`**

- [ ] **Step 3: Run, then mutation check both sides**

Run: `python Tests/parity.py`. Expected: PASS with `R 71095`, `T 10656`.
Mutation: in the Python copy, make `texture.info` read width at `0x14` instead of `0x10`. Expected: FAIL. Revert. In C++, the same in `ReadInfo`. Expected: FAIL. Revert. Record both in the script's docstring.

- [ ] **Step 4: Run the whole verdict**

Run: `python check.py --blender`. Expected: `ALL GATES PASS`.

- [ ] **Step 5: Commit**

```bash
git add Source/Roadie Tests/parity.py check.py Docs/formats.md
git commit -m "Parity gate: the extension's decoder agrees with Roadie on every record and texture"
```

---

### Task 9: Docs and the "Where to look" table for the new layout

**Files:**
- Modify: `CLAUDE.md` (Tools: the CMake presets, `roadie`, `Tools/brutal.py` until plan 5; rule 3: `python check.py` builds and runs C++ and Python gates; rule 5: stdlib Python applies to `Blender/BrutalLegend/Brutal/`; "Where to look": `Source/Brutal/`, `Source/Roadie/`, `Tests/Corpus/`, `Tests/Unit/`, `Tests/parity.py`, `Docs/Specs/`, `Docs/Plans/`)
- Modify: `README.md` (build: `python check.py`; run: `roadie <game folder>`; the extension section unchanged)

- [ ] **Step 1: Update, then check every path named in both files exists**

Run: `python -c "import re,os;[print(p) for f in ('CLAUDE.md','README.md') for p in re.findall(r'\`([A-Za-z][\w./-]+/[\w./-]*)\`', open(f,encoding='utf-8').read()) if not os.path.exists(p.rstrip('/'))]"`
Expected: no output.

- [ ] **Step 2: Final verdict**

Run: `python check.py --blender`. Expected: `ALL GATES PASS`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Docs: Roadie's C++ layout, verdict and where to look"
```
