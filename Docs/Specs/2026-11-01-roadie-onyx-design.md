# Roadie on Onyx: design

Date: 2026-11-01. Status: draft for review.

## Intent

Roadie today is three things built on one Python library: the decoders (`Brutal/`, stdlib Python
3.11), a command-line explorer (`python -m Brutal`) and a Blender 5.2 extension
(`Blender/BrutalLegend/`) that imports straight from the game's bundles.

Jean wants Roadie to become a modern successor to the DoubleFine Explorer (the Delphi tool in
`References/DoubleFine-Explorer/` that this project reverse engineered): a native C++ application
built on **OnyxSDK 2.0.0** (https://github.com/JeanxPereira/OnyxSDK, Jean's own SDK for game-asset
tools). All the product Python outside Blender goes away. The Blender extension stays, isolated:
it keeps browsing and importing straight from the bundles, as it does today, without depending
on the C++ binary.

The longer arc is modding: export a texture, model or animation, edit it elsewhere (Blender via
glTF, an image editor via PNG), bring it back into the game's format without breaking it, and
ship the result as a package other people can install and uninstall. That arc is **not** in this
design (see Direction), but nothing here may close the door on it.

## Scope: what this design covers

The work splits into four projects, agreed in this order:

1. **Roadie reader in C++/Onyx.** Every decoder in `Brutal/` ported to an Onyx module, the corpus
   gates ported to C++, the Shell application with its viewers, and the command line.
2. **Blender extension isolated.** The Python decoder moves inside the extension; the rest of the
   product Python leaves the repo.
3. Writing and round trip (texture, then model, then animation). *Direction only.*
4. Mod packages (distributable, install/uninstall). *Direction only.*

This document designs 1 and 2. They ship together, because between them the repo must never
have two decoders that both claim to be the source of truth.

## Goals

- One native Roadie binary (Windows first) that is both the explorer window and the command line,
  built on `Onyx::Shell` (a file argument opens the window; a verb runs a command).
- Brutal Legend only. No structure for other Double Fine games is built ahead of need (Jean: "só
  o BrutalLegend por enquanto").
- Every format fact that `Brutal/` proves today is proven again by a C++ corpus gate with the same
  numbers, over the same corpus (the Steam install's `Win/Packs`, 20 bundles, 71,095 resources).
  The table in `Docs/formats.md` is the target list: DFPF 71,095/71,095; Mesh 7,711/7,711
  byte-exact; Rig 302/302; Texture 10,656 DDS byte-exact; Material 2,748 with 11,247/11,247 refs;
  text objects 11,678/11,678 in 69 types; UI movies, UI render, UI fonts; AnimResource 15,866
  with its chunk/section/quaternion counts.
- Viewers in the window for everything the decoders read: texture, mesh with skeleton and
  morphs, material, animation playback on its rig, text objects, UI movies, UI fonts.
- The existing CLI verbs keep working, as Roadie verbs: `types`, `ls`, `info`, `extract`
  (with `--convert`), `ui fonts`, `ui render`. Onyx's stock `probe/list/extract/decode` come for
  free.
- Export through `Onyx::Exchange`: glTF (mesh, skin, animation), PNG, plus the formats Roadie
  already writes (DDS, TrueType, SVG).
- The Blender extension keeps every feature it has today (browser/search, mesh+skeleton+morphs
  import, game materials and `gameshader` shading, Weather/sun, the animation clip browser) and
  installs and updates exactly as now (zip + the GitHub Pages extensions repository).

## Non-goals

- Writing any game format, glTF/PNG import, mod packages (projects 3 and 4).
- Formats not decoded today (Heightfield, ObjectData, Havok, audio, …; see `Docs/assets.md`).
  The port is of what exists, not new reverse engineering.
- Support for other Double Fine games.
- Linux/macOS builds of Roadie in this round (my call: Windows first, because the game, IDA and
  the corpus live there; Onyx itself builds on Linux, so nothing should block it later).

## Anti-goals (would make this a failure even if it technically works)

- A C++ gate that passes but does not bite. The project's principle stays: break the fact (an
  offset, a dropped field) and the gate must fail. Each ported gate is mutation-checked once.
- Losing a number. If a C++ gate proves less than the Python gate it replaces (fewer resources,
  a looser check), the port of that format is not done.
- Two sources of truth. After the cut, the C++ module is the authority; the Python decoder in the
  extension is a consumer that must agree with it, never the other way around.
- The extension starting to depend on the Roadie binary, a subprocess or a native module.
  It stays pure Python inside Blender.
- Changes to OnyxSDK made from this repo by hand-patching a fetched copy. If Roadie needs
  something Onyx lacks, it either builds it on top through Onyx's public extension points
  (`Any` payloads, `ViewerSpec`, `Cli::Verb`, `Mounts`) or it becomes a change proposed to OnyxSDK
  itself, released as a new Onyx version.

## Constraints

- The game and `BrutalLegend.exe` (IDA 9.4) are the only authorities, as today (`CLAUDE.md`).
  Every format fact lives at the top of its decoder source (a header comment replaces the Python
  docstring) and in `Docs/formats.md`, with its gate and IDA address.
- Space conversion stays `(x, y, z) -> (x, -z, y)` for Blender; glTF export uses the game's
  Y-up right-handed space directly (glTF is Y-up right-handed; my reading, the builder confirms
  with a render).
- Evidence stays out of git (`.evidence/`). The corpus gates need the install (`BL_GAME_DIR`,
  default in today's `Brutal/paths.py`) and are not run in CI.
- Folders and C++ files in PascalCase (Jean's preference; tool-forced ids such as the extension
  id `brutal_legend` stay lowercase).
- No AI attribution anywhere, in commits, docs or code.
- Onyx's rules apply to what Roadie writes against it: its module contract
  (`docs/modules.md` in OnyxSDK): report, never throw; distrust every count and offset; decoders
  are free functions that may run on a worker thread.

## Decided

By Jean:

- The C++ Roadie lives in **this repo** (`BrutalLegend-MDL`), replacing the Python product.
- The Blender extension stays, **isolated**: browses and imports from the bundles directly, no
  dependency on the binary.
- Brutal Legend only, for now.
- Project tooling stays Python: `Tools/Ida/` (idalib is Python), `Tools/Shaders/`,
  `Tools/readme_art.py`, `Tools/build_addon.py`, `Tools/blender.sh`, `Tools/ci_blender.sh`. It is
  tooling of the project, not the product.
- Order: reader + isolation now; writing, then packages, later, each with its own design.
- **Morphs and float (face/flex) animation tracks go into OnyxSDK 2.1**, not into Roadie. Onyx
  2.0.0 has neither (`Domain::Mesh` has no morph targets, `Domain::AnimChannel` carries only
  rotation/translation/scale per joint, the glTF exporter writes no morphs). They are generic, so
  they belong in the SDK: morph targets on the mesh, float channels on the clip, the stock
  renderer playing both, glTF export writing both. Until 2.1 is released and the pin bumped, the
  Roadie port proceeds without displaying them: the C++ decoders still read morphs and float
  tracks and the corpus gates still prove them (as today's Python gates do); only viewing and
  export wait for 2.1. The Onyx 2.1 work is designed and built in the OnyxSDK repo, under its own
  rules, not from here.

My calls (Jean can veto):

- **Toolchain:** C++26, Clang, CMake 4 + Ninja (Multi-Config) with presets, matching Jean's other
  reverse-engineering projects. Onyx itself is C++20 and builds with MSVC or Clang 18+; a C++26
  consumer links it unchanged.
- **Onyx dependency:** `FetchContent` pinned to the tag `v2.0.0`, bumped deliberately.
- **Layout** (PascalCase, mirroring Onyx's `Source/<Lib>/include/<Lib>/`):
  - `Source/Brutal/`: the Onyx module, links `Onyx::Core` only (no GPU, so the gates and the CLI
    configure without Vulkan). One source pair per format, named after today's Python modules
    (`Dfpf`, `Library`, `Mesh`, `Rig`, `Texture`, `Material`, `TextObj`, `Anim`, `Shaders`,
    `RsaLight`, `Gfx`, `GfxSvg`, `Image`, `Ttf`).
  - `Source/BrutalUi/`: the viewers and commands that need the Shell (material/shading, UI
    movie, font, Weather), installed as an `IShellExtension`.
  - `Source/Roadie/`: the executable, constructing the Shell with the module, the extension,
    Media and the Roadie verbs.
  - `Tests/Corpus/`: the C++ corpus gates (one per format, as today).
  - `Tests/Unit/`: synthetic tests that need no game (Onyx `TestKit` builders, tree and CLI
    goldens over synthetic fixtures), runnable in CI.
- **Verdict:** `check.py` stays the single verdict and exit code (it is project tooling, Python,
  like OnyxSDK's own `tools/check.py`): configure, build, run the unit suite, run the corpus gates
  when the install is present, run the parity gate, and with `--blender` the Blender smoke render.
- **Spec location:** `Docs/Specs/` (PascalCase, instead of the skill's default
  `docs/superpowers/specs/`).

## How it is built

### The module and the install

Onyx opens one file per document; Brutal Legend resolves references across bundles (a material
in one pack names a texture in another; today `Brutal/library.py` indexes all 20 `.~h` files by
lower-cased `name.Type` path, first bundle in sorted order wins). Roadie must keep that.

The shape is the builder's call, with these requirements:

- Opening the install (the game folder, `Win/Packs`, or any one `.~h`) yields one document whose
  tree covers all 20 bundles, grouped as the user browses them: by resource path, with the type
  visible and filterable (today's `types` and `ls -t`).
- Cross-bundle references resolve inside decoders through the document's module state, the
  equivalent of `Library.read(path)`, with the same first-wins rule.
- Opening a single `.~h` from another location (a copy, a future mod bundle) still works, scoped
  to that bundle, with unresolved references reported as diagnostics, not failures.
- Payloads are read lazily, as today; nothing decodes during the walk.

### Mapping formats to Onyx slots

| Resource | Onyx slot | Note |
|---|---|---|
| Texture (DDS: DXT1/DXT5/DXT5nm) | `Image` (`Bc1`/`Bc3`) | the 16 `rsalights` subtype: `Raw` + `Schema`/`Any`, as known |
| Mesh + Rig | `Scene` (mesh, skeleton, skin; morphs from Onyx 2.1) | until 2.1, morphs are decoded and gated but not placed in the `Scene` |
| Material | `Any` (game material, with resolved texture refs and shader constants) plus a best-effort `Domain::Material` for Onyx's stock renderer and glTF export | Onyx's material is generic PBR; the game's look comes from `Shaders` |
| AnimResource | `Scene` animation set on its rig (`AnimClip`) | float (face/flex) tracks: Onyx 2.1 float channels; until then decoded and gated only |
| Text objects (69 types) | `Text` (and `Table` where a type is a list) | MeshSet/Outfit/Weather keep their parsed form in an `Any` for viewers |
| Weather / RSALight | `Any` | drives the material viewer's lighting |
| UI movie (`.gfx`) | `Any` (decoded movie) + `Text` (SVG) | the viewer rasterizes a frame/label |
| UI fonts | `Any` + export to TrueType | |

Where this table says "if Onyx lacks X", the builder checks the 2.0.0 headers first and records
the answer in the plan.

### Viewers

The stock Onyx viewers serve texture, mesh, animation, text, table and hex. Roadie adds, through
`ViewerSpec` with `anyCapability`:

- **Material viewer:** a preview mesh (or the selected mesh) shaded like the game, driven by the
  same shader-family knowledge as the extension's `gameshader.py`, with a Weather picker.
- **UI movie viewer:** frame and label navigation, settle option, background toggle (today's
  `ui render` flags).
- **Font viewer:** glyph grid and sample text.

My call on depth: the first release of the material viewer may use Onyx's stock renderer with the
mapped `Domain::Material` (diffuse/normal/blend) and grow toward game-accurate shading; the
`gameshader` port is the target, not the entry bar. The builder may sequence it last.

### Gates

- One C++ corpus gate per format, reproducing the assertions of the Python gate it replaces
  (the docstring at the top of each `Tests/corpus_*.py` is the spec), with the same printed
  numbers. Each gate is mutation-checked once when ported (flip an offset, the gate fails),
  and the mutation used is recorded in the gate's header comment.
- The Python gates stay in the repo until their C++ gate matches them, then are deleted in the
  same change that deletes the Python decoder they cover.
- `Tests/Unit/` covers each decoder on synthetic input with TestKit writers, plus tree and CLI
  goldens, so CI has a meaningful build-and-test without the game.

### Transition (my call)

Work lands on `main` step by step, never as one big merge, and there is only ever **one** Python
decoder in the repo:

1. **Step 0, before any C++:** move `Brutal/` whole into the extension
   (`Blender/BrutalLegend/Brutal/`). The Python gates, the Python CLI and the tooling import it
   from there for the duration of the port; `Tools/build_addon.py` and `ci.yml` stop vendoring.
   Extension behaviour does not change, so extension releases from any intermediate state are
   allowed.
2. **Per format:** the C++ decoder and gate land; when the C++ gate reaches the Python numbers, the
   C++ module becomes the authority for that format, the Python gate is deleted and the parity gate
   for that format is switched on in the same change.
3. **End:** the modules the extension does not import (`gfx`, `gfxsvg`, `image`, `ttf`,
   `__main__`) are deleted once their C++ counterparts pass.

### Port order

Bottom-up, each step closing with its gate at the Python numbers:
DFPF + library, Texture, Mesh, Rig, Material, TextObj, Shaders/RsaLight, Anim, then the UI chain
(Image, Gfx, GfxSvg, Ttf). The window becomes usable after Texture/Mesh/Rig; the CLI verbs land
with the formats they need.

### Blender extension isolation

- The Python decoder moves into the extension as its own subpackage (e.g.
  `Blender/BrutalLegend/Brutal/`), keeping only the modules the extension imports today:
  `paths`, `library`, `dfpf`, `mesh`, `rig`, `texture`, `material`, `textobj`, `shaders`,
  `rsalight`, `anim`. The UI chain (`gfx`, `gfxsvg`, `image`, `ttf`) and the CLI (`__main__`)
  are not carried; they exist only in C++.
- **Parity gate** (keeps the extension honest against the C++ authority): Roadie gets a verb that
  writes a canonical digest per resource (for example, per mesh: vertex/index counts and a hash of
  each converted stream; per rig: bone names, parents, matrices hash; per material: texture refs
  and constants; per anim clip: channel layout and a hash of the decoded keys). A Python script
  in `Tests/` produces the same digest from the extension's decoder outside Blender, over the
  whole corpus, and the two must be identical. The digest format is the builder's call; the
  requirement is that a one-field divergence in either decoder fails it.
- `Tools/build_addon.py` packages the extension folder alone (no vendoring step); the release
  workflow and the Pages extensions repository stay as they are.
- `Tests/Blender/` (smoke, lineup, anim smoke, Eddie anims) stays and keeps working.

### What leaves the repo at the end

`Brutal/` (the top-level package), `python -m Brutal`, and every `Tests/corpus_*.py`, each only
after its replacement passes. `CLAUDE.md`, `README.md`, `Docs/formats.md` and the "Where to look"
table are updated to the new layout in the same changes. `CLAUDE.md` rule 5 (stdlib Python) moves
to the extension's decoder.

### Project tooling that reads game data (my call)

`Tools/Shaders/disasm.py` imports `shaders` and `Library`, which the extension carries, so it
imports them from `Blender/BrutalLegend/Brutal/`. `Tools/readme_art.py` needs `gfx`, which only
C++ will have, so it calls the Roadie binary (`extract --convert`, `ui fonts`, plus whatever export
verb its emblems need) and keeps its Pillow compositing in Python. Regenerating the README art
then needs a Roadie build; that is acceptable for a manual tool.

### Host-side details already settled

- `Workspace::Open` in Onyx 2.0.0 opens the path as a file before probing, so a folder cannot be
  opened directly; the Roadie host resolves a game folder or `Win/Packs` to a bundle path (or the
  install mount) before opening. Old verbs (`ls`, `types`, …) default to the install when given no
  path, as today.
- Onyx bundles no zlib; Roadie adds one (needed by the UI movie chain).
- The UI movie viewer needs an SVG rasterizer; the library is the builder's pick.

## Direction (not designed here, but must stay possible)

- **Writing:** each format module will later gain a writer (the inverse of its decoder) and an
  importer from PNG/glTF. Where cheap, decoders keep what they read (unknown fields, padding,
  order) in the decoded form rather than dropping it. This is **guidance, not a gate, in this
  round** (my call): the C++ decoders may mirror the Python ones, and the re-serialize gates
  arrive with project 3. Onyx 2.0.0 has export only; import will be Roadie's or a future Onyx
  layer.
- **Mod packages:** depend on reverse engineering how `BrutalLegend.exe` loads content over the
  shipped bundles (patch bundle, override folder, or rewriting). Nothing in this round decides it;
  the DFPF code should not assume the 20 shipped bundles are the only ones.

## Left to the builder

- The install-as-document mechanics (`Mounts` vs. a directory open vs. module state).
- Exact Onyx slots where the table above says "if Onyx lacks".
- The digest format of the parity gate.
- How the material viewer reaches game-accurate shading, and in which order.
- CI shape for the C++ build (Windows runner, unit suite only).
- Whether the Roadie binary is attached to GitHub releases in this round.
