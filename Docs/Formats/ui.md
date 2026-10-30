# UI: Scaleform GFx movies, the Flash system, and how the game drives them

Decoder: `Brutal/gfx.py` (movie container, tag stream, external images, exports/imports,
DefineFont3 glyphs, shapes, morphs, edit texts, placements, sprites); gates: `Tests/corpus_gfx.py`,
`Tests/corpus_render.py`, `Tests/corpus_ttf.py`. Offline rendering and font export: §13.
This document describes the runtime system. Addresses are `BrutalLegend.exe` (Steam build); every
game function named below was renamed in the IDA database
(`.evidence/ida/BrutalLegend.exe.i64`) — the original `sub_` address is the address given.
Functions inside the Scaleform library (0xAA0000–0xC20000) keep their `sub_` names; their role is
given from strings and call patterns.

The data facts in §2 are enforced over the full corpus (79 `DUIMovie`, 80 `.gfx` blobs) by
`Tests/corpus_gfx.py`: movies parse to their header length, bundle Blob = loose file, every external
image resolves to a listed Texture of the block-rounded size, every FontMap target exists.

## 1. Library and renderer

| Fact | Evidence |
|---|---|
| Scaleform GFx **2.1.57** | string `"2.1.57"` next to `"gfxVersion"` (0xE3D598/0xE3D5A4), used by sub_ADE200 |
| Flash player version reported to AS: `$version` = `"WIN 8,0,0,0"` (AS2 / SWF 8 runtime) | 0xE3E578, sub_AE75F0 |
| Loader accepts only GFX 2.x files (`CFX`/`GFX` signature, zlib body for `CFX`) | `"incompatible GFX file, version 2.x expected"`, sub_ABCB80 |
| Renderer: **Direct3D 9**, Scaleform's `GRendererD3D9Impl` compiled into the game (RTTI `.?AVGRendererD3D9Impl@@`, vtable 0xE8696C, code 0x476F20–0x47A290) | `GRendererD3D9Impl_Ctor` (sub_476A60) |
| The game wraps it in `GFxRendererDF` (240 bytes, own critical section, render-snapshot list `FlashRenderSnapshotImpl`) | `GFxRendererDF_Ctor` (sub_4734F0) |
| Renderer creation: `FlashSystem_CreateRenderer` (sub_475AE0) allocates the D3D9 renderer, calls its vtable +0x7C with the game's D3D device / present parameters / HWND (`SetDependentVideoMode`-style, exact signature unknown), wraps it in `GFxRendererDF` and stores it in loader block +0 | sub_475AE0 |
| Memory: game allocator classes `FlashMemoryAllocator`, `FlashMemoryDebugAllocator` installed before the loader (`sub_AA0E50`/`sub_AA0E80` at the top of `FlashSystem_InitLoader`) | RTTI 0xF80518 / 0xF804D4 |

Imports in the shipped movies are only `Shared/ControllerIcons.swf` (98 movies) and
`gfxfontlib.swf` (94 movies) — the latter is GFx's built-in alias for the installed `GFxFontLib`
(string 0xE3B618, sub_AC3450).

## 2. Data

| Resource | Type (index) | Content |
|---|---|---|
| `ui/flash/<x>/<x>.DUIMovie` | `DUIMovie` (79) | `{FlashFile=Data/UI/<X>/Opt/<X>.gfx; Textures=[@ui/flash/<x>/<img>,...]}` |
| `data/ui/<x>/opt/<x>.gfx.Blob` | `Blob` | the movie file, byte-identical to the loose copy `Data/UI/<X>/Opt/<X>.gfx` (checked on Pause); 80 blobs = 79 movies + `data/ui/fonts/opt/englishfonts.gfx` |
| `ui/flash/<x>/<img>.Texture` | `Texture` | the movie's external images |
| `ui/flashconfig.FlashConfig` | `FlashConfig` (1) | font configuration (§5) |
| `ui/input/aliases.InputAliases` | `InputAliases` | input alias → button and line code (§10) |
| `stringtable/*.StringTable` | `StringTable` (40) | localized line codes (§9) |
| `ui/hud/{a,b,d}/{a,b,d}skin.HUDSkin`, `ui/albumcovers/*.AlbumCover` | `HUDSkin` (3), `AlbumCover` (15) | post-process settings, not Flash data (§11) |

`DUIMovie` reflection: `DUIMovie_RegisterAttributes` (sub_46F760) registers `FlashFile`
(`ReferenceAttribute<Name>`, object +0) and `Textures` (`ReferenceAttribute<Array<RsRef<Texture>>>`,
object +4). Resource manager `RsObjectManager<DUIMovie>`, type descriptor at 0xF78B18.

`.gfx` files are gfxexport output: tag 1000 (ExporterInfo, version 0x020F, bitmap format 0x0E,
prefix = movie name, e.g. `Pause`) and one tag 1001 (DefineExternalImage:
`u16 char id, u16 format, u16 width, u16 height, pascal export name, pascal file name`, file name
`<img>.dds`) per image. **Corpus check (79/79):** `Textures` is exactly the set
`@ui/flash/<lower(prefix)>/<lower(file name without extension)>` over the movie's tag-1001 records,
and the ExporterInfo prefix equals the movie's folder name. The `_i<hex>` names seen in some movies
are gfxexport's default names for unnamed bitmaps, not a separate mechanism.

## 3. The Flash system object

One global, `dword_1009CA8`, 1868 bytes, built by `FlashSystem_Create` (sub_46EDD0) →
`FlashSystem_Ctor` (sub_4684C0). Every access to a movie view is serialized by the critical section
`stru_100E5C0`.

| Offset | Content | Source |
|---|---|---|
| +0x00 | u8 loader initialized | `FlashSystem_InitLoader` sets it |
| +0x04 | movie currently advancing (FSCommand context) | `FlashSystem_AdvancePlayer` |
| +0x08 | loader block (112 bytes, below) | sub_468470 |
| +0x0C/+0x14 | array of live movie instances | `FlashMovie_Load` appends |
| +0x3C | Lua state used by the FSCommand bridge (argument of `FlashSystem_Create`) | sub_46EDD0 |
| +0x40 | u8 "advancing" | sub_469280 |
| +0x41 | u8 profanity filter on (`/bleep/` markup) | `FlashText_ExpandMarkup` |
| +0x48/+0x50 | input-focus stack of movies (top receives input) | `FlashSystem_PushInputFocus` (sub_4691E0) |
| +0x54, +0x58 | per-player 1/30 s advance accumulators | sub_469280 |
| +0x5C | 2 × 848-byte per-player input snapshots | sub_469280, `FlashMovie_RouteInput` |
| +0x708 | handle of `Data/UI/Fonts/Opt/EnglishFonts.gfx` (kept loaded) | sub_46EDD0 |
| +0x70C | the `PhysicalInputIcons` movie instance (loaded on first `CreateMovie`) | `FlashSystem_CreateMovie` |
| +0x73C | optional external FSCommand listener (object, vtable +4 called first) — written by sub_6D1420 and sub_8BF420, purpose **unknown** | `FlashFSCommandHandler_Callback` |

Loader block (`FlashSystem+8`), filled by `FlashSystem_InitLoader` (sub_46A5F0). GFx state IDs are
the values passed to the loader's `SetState` (vtable +8); class names come from RTTI or, where
marked, from usage:

| Block offset | Object | GFx state ID |
|---|---|---|
| +0x00 | `GFxRendererDF` | — |
| +0x04 | `FlashFileOpener` (sub_46AC50) | given to the `GFxLoader` constructor |
| +0x08 | `GFxRenderConfig(renderer)` (sub_AA3BC0), flag 0x10 set at +0x1C | 1 |
| +0x0C | movie def of the shared font file | — |
| +0x10 | `GFxLoader` (sub_AA3730) | — |
| +0x14 | `FlashTranslator` | 3 |
| +0x18 | `FlashFSCommandHandler` (holds the translator at +0x18) | 8 (set per movie def, §4) |
| +0x1C | `FlashImageCreator` | 12 |
| +0x20 | `FlashLogger` (sub_46AC80) | 4 |
| — | font map (sub_AA45C0; receives `MapFont`) — class from usage | 20 |
| — | font library (sub_AA4AB0; receives `AddFontsFrom`) — class from usage | 18 |

The 'flash' Lua module is registered in `FlashSystem_Create` (`sub_A6CF60(off_F78B08, off_F78B0C)`,
§8). `FlashSystem_ReleaseLoader` (sub_4687A0) tears the block down; `FlashSystem_Shutdown`
(sub_468670) frees the object.

## 4. Loading a DUIMovie

```
FlashSystem_CreateAndLoadMovie(duiHandle, async, priority)          sub_468A50
  FlashSystem_CreateMovie(sys, duiHandle, 3, !async)                sub_468900
    first call: load PhysicalInputIcons the same way (sys+0x70C)
    FlashMovie_Ctor (120 bytes)                                     sub_4708C0
    FlashMovie_BindDUIMovie(movie, duiHandle, 3, requestTextures)   sub_468B30
      resolve DUIMovie (RsObjectManager<DUIMovie>, off_F78B18)
      FlashMovie_RequestTextures: copy Textures handles to movie+0x68, request each
        Texture resource (off_F77868) with priority dword_E8317C[3]   sub_470AC0
      FlashFileOpener_RemapPath(FlashFile) -> resource name           sub_46AD30
      request the Blob resource (off_F78C60); keep its handle at movie+0x64
  FlashMovie_Load(movie, sys, duiHandle, priority, async)           sub_468C80
    FlashSystem_InitLoader on first use                              sub_46A5F0
    GFxLoader::GetMovieInfo(FlashFile)          sub_AA34A0  (fails -> movie dropped)
    GFxLoader::CreateMovie(FlashFile, 0)        sub_AA34F0  -> movieDef at view+4
    movieDef state bag SetState(8, FSCommandHandler)
    movieDef vtable +0x44 (CreateInstance)      -> GFxMovieView at view+0
    view SetBackgroundAlpha(movie+0x11 ? 0 : 1) (vtable +0x7C; stores alpha·255)
    view vtable +0x78 (0)                       (stores an int at +0xDC; meaning unknown)
    append movie to sys+0x0C list, release the Blob handle (movie+0x64)
```

`FlashMovie_Load` takes the `FlashFile` string straight from the `DUIMovie` (field +0) and gives it
to GFx unchanged; resolution happens in the file opener.

### File opener (`FlashFileOpener`, vtable 0xE85A80)

`FlashFileOpener_OpenFile` (sub_4760F0, vtable +4) receives every path GFx opens (the movie itself
and its imports, already made relative to the movie and with the `.gfx` extension):

1. `FlashFileOpener_RemapPath` (sub_46AD30): if the path contains `/Shared/`, the part after it is
   remapped — `ControllerIcons.gfx` → `Data/UI/PhysicalInputIcons/Opt/PhysicalInputIcons.gfx`, any
   other `X.gfx` → `Data/UI/X/Opt/X.gfx`. Otherwise the path is used as is (truncated to 259 chars).
   Where GFx turns the import name `Shared/ControllerIcons.swf` into `.../Shared/ControllerIcons.gfx`
   is inside the library and was not traced (assumption: GFx's import-extension substitution).
2. `FlashFile_OpenBlob` (sub_475EF0): looks the path up as a resource name (sub_449D70; the names are
   the lower-cased paths of the `.gfx.Blob` resources) and wraps it in a `BlobFile` (sub_45AAA0).
   No resource → returns 0 (GFx then logs `GFxLoader failed to open`); the loose files under
   `Data/UI` are not read by this path.
3. The `BlobFile` is wrapped in a `GDelegatedFile_DF` (`GFile` subclass) and returned.

vtable +8 (sub_AA3300) is the library default (`GSysFile::GetFileStat` modification time).

### Image creator (`FlashImageCreator`, vtable 0xE85A5C)

`FlashImageCreator_CreateImage` (sub_475D80, vtable +4), for create-info type 2 (image from file,
i.e. a tag-1001 external image):

1. `SplitPath` (sub_4418E0) splits the file name (string at file-info +0x18) at the last `/` or `\`.
2. Builds `UI/Flash/<a>/<b>` where `<b>` is the file part (`staircase.dds`) and `<a>` is the
   C string at `*(file-info +0x14) + 8`. Assumption: that object is the movie's ExporterInfo and
   `<a>` its prefix (`Pause`) — consistent with the 79/79 corpus check in §2; not proven from code.
3. Resolves the name (sub_407700) to a `Texture` resource handle and gets the loaded object
   (sub_450760 with off_F77868). The `.dds` extension does not stop the match (the resource name
   is `ui/flash/pause/staircase`); how sub_407700 drops it was not traced.
4. Wraps the game texture in a GFx image info sized from the texture's u16 width/height at
   +0x1C/+0x1E (sub_AA6200).

Any other create-info, a failed split, or a missing texture falls back to the library's
`GFxImageCreator::CreateImage` (sub_AA3850). Because `FlashMovie_RequestTextures` requested every
`Textures` entry before the movie is created, the textures are resident when GFx asks for them.

## 5. Fonts and FlashConfig

`FlashConfig` reflection: `FlashConfig_RegisterAttributes` (sub_46B2D0) — `FontIndexMap`
(`ArrayAttribute<u32>` indexed by `enum Languages`, 6 entries) and `FontMapping`
(`Array<FontMapper>`). `FontMapper_RegisterAttributes` (sub_46AFA0) — `FontMap`
(`HashTable<String, Tuple<String, GFxFontMap::MapFontFlags>>`) and `SharedFontFile` (`String`).
`MapFontFlags_RegisterEnum` (sub_46A580): `MFF_Normal`=0, `MFF_Italic`=1, `MFF_Bold`=2,
`MFF_BoldItalic`=3, `MFF_Original`=4.

Installation (`FlashSystem_InitLoader`): the config is `UI/FlashConfig` (`FlashConfig_GetHandle`
sub_46C460, `FlashConfig_Resolve` sub_46A540). The entry used is
`FontMapping[FontIndexMap[current language]]` (language index at `*dword_1009CC4`):

1. `GFxLoader::CreateMovie(SharedFontFile)` → loader block +0x0C.
2. For every `FontMap` pair: `MapFont(name, font, flags, 1.0)` (sub_AA4660) on the font map
   (state 20). The shipped config maps `$Condensed`→`TG_Condensed`, `$Fancy`→`Schreibweise`,
   `$Menu`→`TG_Menu`, all `MFF_Original`; `FontIndexMap` is `[0,0,0,0,0,0]`.
3. `AddFontsFrom(fontMovieDef, 0)` (sub_AA4A30) on the font library (state 18) — the movies' import
   of `gfxfontlib.swf` then resolves to these fonts.

Without a `FlashConfig` the code falls back to `Data/UI/Fonts/Opt/EnglishFonts.gfx` with
`$Fancy`→`Schreibweise` and `$Menu`→`Trade Gothic LT Std Extended`.

## 6. Running movies

Movie instance (`FlashMovie_Ctor`, 120 bytes). Known fields:

| Offset | Field |
|---|---|
| +0x00 | owning player index (0/1), or 2 = system movie |
| +0x08 / +0x09 | enabled (current / requested; `DisableMovie` clears +0x09) |
| +0x0A | receives input |
| +0x10 | u8 loading |
| +0x11 | transparent (background alpha 0) — `FlashMovie_SetTransparent` (sub_470C40) |
| +0x12 | u8 "native resolution" (returned by `IsNativeResolution`) |
| +0x18 | mouse enabled (`sub_470C90`, also view vtable +0x90; meaning of that slot **unknown**) |
| +0x1C | priority (0x8000 default) |
| +0x5C | f32 advance-rate scale (1.0) |
| +0x60 | view holder (172 bytes): +0 `GFxMovieView*`, +4 `GFxMovieDef*`, +0x60 Bink background, +0x64 u8 advanced, +0x68 member-path cache |
| +0x64 | `Blob` handle of the `.gfx` while loading |
| +0x68 | `Array<RsRef<Texture>>` (the `Textures` list) |

Per frame:

- `FlashSystem_AdvancePlayer` (sub_469280): dt clamped to 1/15 s; each player's accumulator steps the
  movies at a fixed **30 Hz** (`Advance(rate · 1/30, 0)`, view vtable +0x70). For each enabled movie
  of that player it sets the FSCommand context (sys+4), and if the movie receives input and is the
  top of the focus stack, runs `FlashMovie_RouteInput` first. `FlashSystem_AdvanceMovie` (sub_469570)
  advances a single movie with a caller-supplied dt (max 33.3 ms).
- `FlashSystem_DisplayAll` (sub_46A0E0): `Display` (view vtable +0x74) for every enabled, advanced
  movie (when called for the whole list, only those with priority ≥ 16), then flushes the renderer snapshot (sub_473770).
- `FlashSystem_ReleaseMovie` (sub_469070) disables and frees an instance.
- `FlashMovie_AttachBinkBackground` (sub_471430): if the movie def has an image resource exported as
  `BinkVideoBackground`, its image is replaced by a dynamic texture of the same size (sub_6605A0) that
  the video player writes into. Used by FrontEnd, EndCredits, Video, INTR_Branching, DemoIntro.

GFxMovieView vtable slots used by the game (GFxMovieRoot vtable 0xE392B4; the GFx 2.1 method each
slot is assigned to is from the implementation's strings/callees):

| Slot | Method | Implementation |
|---|---|---|
| +0x14 | `GotoLabeledFrame(label, offset)` | sub_AAD030 |
| +0x2C | `SetVariable(path, GFxValue, setType)` (`"NULL pathToVar passed to SetVariable"`) | sub_AB6400 |
| +0x30 | `GetVariable` | sub_AAF7B0 |
| +0x34 | `SetVariableArray(type, path, index, data, count, setType)` | sub_AB6530 |
| +0x38 | `SetVariableArraySize` | sub_AB6910 |
| +0x44 / +0x48 / +0x4C | `Invoke(fmt, …)` / `Invoke(args, n)` / `InvokeArgs` (reach `InvokeParsed` sub_ADAE40 / sub_AD7B40) | sub_AAFDA0 / sub_AB25A0 / sub_AAFE50 |
| +0x70 / +0x74 | `Advance(dt, catchUp)` / `Display()` | sub_AB5530 / sub_AAF420 |
| +0x7C | `SetBackgroundAlpha(f32)` | sub_AB6FA0 |
| +0x84 | `HandleEvent(GFxEvent&)` | sub_AACC40 |

GFxValue type codes seen: 3 number (double), 4 string, 5 wide string. Event types: 1 mouse move,
2 mouse down, 3 mouse up, 5 key down, 6 key up.

## 7. Game → movie

The game never calls the `Invoke` slots: a scan of every register-indirect call in game code
(0x401000–0xAA0000) to slots +0x44/+0x48/+0x4C of a movie view found none (heuristic scan; a call
through a stored pointer would be missed). Communication is by variables, labels and key events:

- `FlashMovie_SetVariableString` / `…StringW` / `…Number` (sub_471AE0 / sub_471B40 / sub_471C10):
  `SetVariable(path, value, 0)` under the movie lock. `FlashMovie_SetDirty` (sub_471BA0) sets
  `g_dirty = 1`.
- `FlashMovie_SetRoot{Bool,Number,String,StringW}` (sub_471750, sub_4717C0, sub_471830,
  sub_4718A0) and the `…At(index)` variants (sub_471910, sub_471980, sub_471A00, sub_471A70): set a
  member of the movie root by a game `Name`, through a per-movie cache (`sub_471FE0`) of resolved
  members (`sub_AB4750`); setters `sub_AB2C90` (bool), `sub_AB2CD0` (number), `sub_AB2D10` (string),
  `sub_AB2D80` (wide string). 51 / 29 / 23 / 6 direct callers (plus 34/11/5/3 for the indexed ones).
- `FlashMovie_GotoLabeledFrame` (sub_470CD0); `CcPlayFlashMovie_Start` also jumps to an optional label.
- Key events from `FlashMovie_RouteInput` (§10).

Variable names the exe writes (string literals at the call sites): `_g_returnedLineCode`,
`_g_returnedLanguage`, `g_dirty`, `g_Navigator.buttons` (array), `g_Navigator.stick_x`,
`.stick_y`, `.stick_rt_x`, `.stick_rt_y`, `g_fModalTimeRemaining` (MessageBox),
`g_SystemMessage`, `g_TextChatMessage`, `g_TextChatLocalMessage`, `g_bsChatMode` (HUD),
`bFinishedSaving` (Saving), `Tips` (Loading), `JournalEntered`, `goStraightToPage`,
`bCameFromPause`, `bShowDrawings` (Journal), `MapEntered` (Map), `AbandonHeaderText`,
`AbandonTextLeft`, `AbandonTextRight` (AbandonDialog), `iNextState` (Postgame_Lobby),
`MotorForgeGreetingIndex` (Motorforge), `cardname`, `info`, `_global.template` (tutorial cards
`UI/Flash/TC_%s/TC_%s`, sub_58E1D0), and the HUD set written by `BuddhaHUD` (0x7DC000–0x7E1000):
`bHUD_Hints`, `bHUD_AcceptReject`, `bHUD_Alerts`, `bHUD_Dpad`, `bHUD_Health`, `bHUD_Timer`,
`bHUD_Solos`, `bHUD_BuildMenu`, `bHUD_Resource`, `bHUD_Popcap`, `fLastCashRatio`, `bShowXYZCount`,
`uXYZCount_X/Y/Z`, `XYZCount_XYDesc`, `XYZCount_ZDesc`, `CoopName`, `CoopLineCode`,
`bCoopUsageItemEnabled`, `bCoopUsageItemAvailable`, `fCoopUsageItemTimer`, `UnlockTitle`,
`UnlockSubtitle`, `UnlockDisplayID`, `SubtitleLine`, `SubtitleFrame`, `IntroText`, `ObjectiveText`,
`bAcceptRejectSetting`, `bMissionWarningMessage`, `bOA_Any{Move,Follow,Defend,Charge}Order`,
`bRecent{Move,Follow,Defend,Charge}Order`, alert icons `bVisible`, `bEnabled`, `nIconIndex`,
`iconname`, `bCreated`, `bCurrentAlert`, `fAlertRotation`, `bAlertDanger`, `bWasVisible`, and the
build menu (sub_900120) `bAllowedToCancel`, `iFans`, `iPopCap`, `iPopulation`, `radialtheta`,
`selectedindex`, `bAdvance`, `bBuildMenuTeamModifierActive`, `bNegativeBuildRateModifier`,
`buildQueueUIIndex`, `fCurrentBuildPercent`. The list is the literals found near the setter calls;
names passed through variables are not in it.

## 8. Movie → game: FSCommand

`FlashFSCommandHandler` (vtable 0xE85A40; ctor sub_467C10, 52 bytes; +0x14 current movie (set by
`FlashSystem_AdvancePlayer`), +0x18 translator, +0x1C Lua state, +0x20 u8 "in Lua call", +0x30
pushed-argument count).
`FlashFSCommandHandler_Callback` (sub_467C60, vtable +4) receives `(movie, command, arg)`. The
command name up to the first `(` is hashed with `StrHashFNV` (sub_447D30: FNV-1a 32 seeded by the
caller, then `x·8193; x^=x>>7; x·=9; x^=x>>17; x·=33`) and compared with lazily hashed literals:

| Command | Effect |
|---|---|
| `GetLineCodeText` | arg = 11-char line code (5th char a digit) → localized text through `FlashText_ExpandMarkup`, written as wide string to `_g_returnedLineCode` (`FlashFS_GetLineCodeText` sub_4680A0); otherwise `"Unknown Linecode"` |
| `DisableMovie` | clears the movie's requested-enabled flag (+0x09) |
| `IsNativeResolution` | sets the AS variable named by *arg* to the number `movie+0x12` (`FlashFS_IsNativeResolution` sub_468200) |
| `GetCurrentLanguage` | `_g_returnedLanguage` = language enum name, string (`FlashFS_GetCurrentLanguage` sub_4681A0) |
| `L:Begin` | start a Lua call: arg is a dotted path (`a.b.c`) resolved from the globals onto the Lua stack (`FlashFS_LuaBegin` sub_468260) |
| `boolean` / `number` / `string` | (inside `L:Begin`) push arg as Lua boolean (`== "true"`), number (`atof`), or string (sub_A6BFF0) |
| `L:Exec` | `lua_pcall`-style call (sub_A76EC0) and store the results into the AS variable named by *arg* (`FlashFS_LuaExec` sub_468350 → `FlashFS_StoreLuaResults` sub_46A1A0) |
| anything else | first offered to the external listener at `FlashSystem+0x73C`; if it declines: `name()` (empty parentheses, nothing after) is rewritten as `L:Begin name` + `L:Exec arg`; any other text is run as the Lua chunk `return <command>` and its results stored into *arg* (`FlashFS_LuaEvalReturn` sub_46A3A0) |

`true`/`false` hashes are computed alongside the others but are not compared in this function.
Results (`FlashFS_StoreLuaResults`): one result → `SetVariable(arg, v)`; several →
`SetVariableArraySize(arg, n)` then `SetVariableArray` per element; Lua booleans become numbers 0/1,
numbers stay numbers, strings become strings, anything else `null`.

Commands in the shipped movies (literal `FSCommand:` strings, 80 files): `DisableMovie` (75 movies),
`IsNativeResolution` (75), `GetLineCodeText` (74), `GetCurrentLanguage` (47),
`game.PlayHintBannerSound()`, `game.PlayFireTributeSound()` (HUD), `setup.reset()`,
`setup.findGames(kHT_LAN)`, `frontend.continueGame()` (FrontEnd). Many more Lua names appear as
string constants assembled at run time (e.g. `flash.isNativeResolution` 46×,
`profile.GetCurrentLanguage` 37×, `game.ExitInspectionMovie`, `flash.SayLine`, `flash.runVideo`,
`hud.GetHintText`, `frontend.startNewGame`, `app.DoQuit`). The literal `L:Begin` does not occur in
any shipped movie; the typed-argument protocol is unused by the data. Result variables observed:
`_g_nativeResolution` (149), `g_GameCommandResult` (74).

### Lua modules relevant to UI

Lua bindings are static tables `{char* module, entries*, u32 count, u32 capacity}` filled by
one-line initializers in 0xDE0000–0xE30000 that append `{name, cfunction}`. UI-relevant ones:

| Module (table) | Functions |
|---|---|
| `flash` (0xF78B08) | `runVideo`, `stopVideo`, `isVideoDone`, `pauseVideo`, `isVideoPaused`, `videoEnableLoadBalancedIO`, `isNativeResolution`, `setBlurBackBuffer`, `SayLine`, `StopLastLine` |
| `hud` (0xF7878C) | `OnFlashConsumedChatMessage`, `DisplayLineCode` (`Lua_hud_DisplayLineCode` sub_4AAC40), `DisplayLineCodeWithDuration`, `DisplayText`, `ClearLineCodeDisplay`, `SetDisplayOnlyCustomAlerts`, `DisplayElement`, `IsDisplayingElement`, `StartFireTributeSound`, `StopFireTributeSound`, `ShowMissionWarningMessage`, `ShowXYZCount`, `DisplayUnlockNotification`, `SetMissionIntroText`, `SetMissionObjectiveText`, `ShowMissionIntro`, `SetActiveTimer`, `SetAlbumCoverEffect` (`Lua_hud_SetAlbumCoverEffect` sub_7E26F0), `SetAlbumCoverStrength`, `SetSubtitleFrameOffScreen`, `StartCountdownMovie`, `EnableFlash` (`Lua_hud_EnableFlash` sub_7E2860), `IsFlashEnabled`, `GetHintText`, `SetAcceptReject` |
| `frontend` (0xF794B4) | menu/credits/concept art/overlays: `showOptionsMenu`, `showCredits`, `HideCredits`, `ShowConceptTexture`, `ShowINTR`, `ShowMPTU`, `ShowConceptArtBrowser`, `ShowPlayerDetails`, `OverlayVisible`, `ShowSaveIcon`, `GetInitialSysUI`, `startNewGame`, `continueGame`, … (54 entries) |
| `app` (0xF79304) | `ShowPauseUI`, `ShowLoadingScreen`, `SetLoadingTexture`, `StartCustomLoadingScreen`, `IsSystemUIActive`, `QuitToMenu`, … |
| `game` (0xF78678) | journal/map/video/hint/objective helpers: `GetVideoSubtitles`, `GetVideoFilename`, `SetGameJournalState`, `ShowJournalEntry`, `TutorialCardUnPause`, `PlayHintBannerSound`, `SetInGameModalGUIState`, `UseMessageDrivenMouse`, `GetSystemLineCode`, … (690 initializers found, capacity 750) |
| `profile` (0xF78638) | `GetCurrentLanguage`, `SetLanguage`, `ApplyLanguage`, `EnableSubtitles`, `IsSubtitlesEnabled`, `EnableGameHints`, `IsSysUIActive`, … |

The module name pointer is at table −8; the full per-table lists are reproducible by scanning the
initializers (each stores a string literal and a function pointer).

## 9. Text and localization

`FlashTranslator` (vtable 0xE85A4C; GFx state 3). `FlashTranslator_GetCaps` (sub_467660) returns 6
(capability bits; bit meanings per the GFx 2.1 headers not verified). `FlashTranslator_Translate`
(sub_467670) is called by GFx for every text field:

- Key `*XXXXXXXXXXX` (12–14 wide chars, the 5th character a digit): a **line code**. The text after
  `*` goes to `LineCode_FromString` (sub_442AA0: upper-cases, hashes, looks up / interns a line-code
  id); the string is entry `id` of the table at `*(dword_1009CC4+0x1C)` (8-byte records, char* at
  +0, count `*(dword_1009CC4+0x14) >> 6`), else `"Unknown Linecode"`. 77 of the 80 `.gfx` contain
  `*`-prefixed strings.
- Any other text is passed through markup expansion and replaced only if it changed.

`FlashText_ExpandMarkup` (sub_467810) rewrites the text as HTML:

| Markup | Output |
|---|---|
| `/return/` | newline |
| `/bleep/` … `/bleep/` | when the profanity filter is on (FlashSystem +0x41), the enclosed characters are replaced cycling `#$!#*@^!*` (0xF80714) |
| `/<alias>/` | for each input bound to the alias (`InputAliases_Find` sub_46FB80, hash table 0xF79BA4): `<img src='<symbol>' align='baseline' vspace='-8' width='25%' height='25%'>` |
| `&` | `&amp;` |
| unmatched `/…` | copied literally |

Icon symbol for an input id: 1–237 (keyboard) → `kINPUT_Key<keyname>` (key name from the keyboard
device, vtable +0x20); 238–247 → the `kINPUT_*` enum name (mouse: `kINPUT_MouseButton0`…);
248–298 (gamepad) → `<kINPUT enum name>_<pad family>`, only when a gamepad device is active. The
symbols are exports of `PhysicalInputIcons.gfx` (211 exports, one per external image), e.g.
`kINPUT_GamepadButton1_Xbox360`, `kINPUT_GamepadButton1_PS3`, `kINPUT_GamepadButton1_Generic`,
`kINPUT_MouseButton0`; GFx resolves `img src` against the imported icon movie. The family string's
source is read through sub_679D60/sub_679C80 (**unknown** detail; the exported suffixes are
`Xbox360`, `PS3`, `Generic`).

StringTable consumers: the string table set is a reflected object with `StringTables`
(`Array<RsRef<StringTable>>`), `AudioProjects`, `LocalizedLanguageCode`
(`StringTables_RegisterAttributes` sub_494030); a `StringTable` carries `LineCodeData`
(`SortedArray<LineCode, LineCodeData>`, `LineCodeData_RegisterAttributes` sub_494510). The merged
lookup table at `dword_1009CC4` is written by sub_4068D0 and sub_492CC0 (not traced further). Named
handles: `StringTable/BrutalLegend` (sub_407680) and `StringTable/System` (sub_4DE820, used by the
system-message code and `game.GetSystemLineCode`). From ActionScript, text reaches the movie through
the translator (`*` keys), `GetLineCodeText`, and Lua functions returning line-code strings
(`game.GetVideoSubtitles`, `hud.GetHintText`, …).

## 10. Input

`InputAliases` (`ui/input/aliases`): `ButtonInputAliases`, `AnalogInputAliases`, `StickInputAliases`,
each `Array<Tuple<enum ButtonInputs|AnalogInputs|StickInputs, Name, LineCode, int>>`
(`InputAliases_RegisterAttributes` sub_67EEB0). Example `<kBI_Accept,Accept,PMTE145TEXT,38>`: the
Name is the `/alias/` used in text, the LineCode its display name; the int is **unknown** (not read
by the code traced here).

`FlashMovie_RouteInput` (sub_469650), run for the top movie of the focus stack, once per changed
input frame:

- 14 navigator buttons: `g_Navigator.buttons[i]` = held time (number) via `SetVariableArray`; on a
  press (sub_67BBD0 repeat test 0.5 s / 4 Hz, or the movie's override device) sends `KeyDown`+`KeyUp`
  with the key code from the table 0xF78B68: `A B X Y S K Up Down Left Right L R [ ]`
  (65, 66, 88, 89, 83, 75, 38, 40, 37, 39, 76, 82, 219, 221). Assumption: slots are pad
  A, B, X, Y, Start, Back, D-pad ×4, LB, RB, LT, RT (by the letters).
- Left stick (repeat-tested) → arrow keys 37–40 (or 45–48 when movie flag +0x0B is clear), right
  stick → key codes 41–44, both as KeyDown+KeyUp; the combined navigation vector (stick plus the
  movie's override device) → KeyDown 49–52. `g_Navigator.stick_x/y`, `stick_rt_x/y` = the stick
  values, ×15 when per-player flags +0x65/+0x66 are set (meaning **unknown**).
- Mouse (when movie +0x18): mouse move and button down/up events at the cursor position; when the
  view's vtable +0x5C returns 4 the x coordinate is shifted by `(16·h/9 − w)/2` of the back buffer
  (sub-pixel details of that slot **unknown**).

Controller icons: movies import `Shared/ControllerIcons.swf`, which the file opener redirects to
`PhysicalInputIcons.gfx` (§4); that movie is loaded once and kept (`FlashSystem+0x70C`,
`PhysicalInputIcons_GetHandle` sub_46C370). `ui/flash/xbox360_controllericons` and
`ui/flash/ps3_controllericons` also exist as `DUIMovie`s; no code path that loads them was found.
The config key `sDefaultControllerIcons` (read in sub_404880) is a lead; its use was not traced.

## 11. HUD, HUDSkin, AlbumCover, other hosts

`BuddhaHUD` (vtable 0xEBCE64) owns the HUD movies; `BuddhaHUD_CreateMovies` (sub_7DFBC0) creates them
with `FlashSystem_CreateAndLoadMovie` (priority 0x8001 for the main HUD, 0x8000 / 0x8064 others),
all transparent: `UI/Flash/HUD/HUD`, `Alerts_Faction_{A,B,D}`, `CoopHint`, `MissionTitle`,
`Subtitle`, `TextChat`. `BuddhaHUD_EnableFlash` (sub_7DCDC0, from `hud.EnableFlash`) releases them
all when disabled. `HUD_GetLocalPlayerHUD` (sub_4AA780) returns the local player's HUD (player +0x68).

`HUDSkin` is **not Flash data**: `HUDSkin_RegisterAttributes` (sub_7E1CB0) — `PostNoiseTexture`,
`HealthZones` (`HealthZoneParams` with `SpikePostModifiers`), `NearDeathHPFFadeInTime`,
`NearDeathHPFCutoff`, `NearDeathSoundCue`, `NearDeathAudioEnvironment`: low-health post-process and
audio. It is referenced as `RsRef<HUDSkin>` by the player-avatar settings object (attribute list
sub_79C850, string `"Describes what resources to use when displaying the HUD."`).

`AlbumCover` is not Flash data either: `AlbumCover_RegisterAttributes` (sub_7E1A60) — `CoversFX`
(`Array<AlbumCoverFX>`); `AlbumCoverFX_RegisterAttributes` (sub_7E1650) — `WeatherTags`,
`FogModifiers`, `PostModifiers`. `hud.SetAlbumCoverEffect(name)` resolves the resource
(sub_7E3640) and stores the handle at HUD +0x274; `SetAlbumCoverStrength` sets its weight.

Other movie hosts:

- `CoFlashTexture` (component, vtable 0xE8DA74): `CoFlashTexture_CreateMovie` (sub_506440) loads its
  `FlashMovie` (`RsRef<DUIMovie>`) transparent and hands it to sub_705710 together with a
  `DiffuseTexture` parameter object — assumption from the names: the movie is rendered into the
  owner's diffuse texture.
- `CcPlayFlashMovie` (cutscene command "Play Flash Movie", attribute `DUIFilename:RsRef<DUIMovie>`):
  `CcPlayFlashMovie_Start` (sub_6240F0) loads the movie and optionally jumps to a frame label.
- Front end and system screens, by `DUIMovie` name: `UI/Flash/FrontEnd`, `Postgame_Lobby`,
  `PlayerPopups`, `Pause`, `INTR_Branching`, `Video_MPTU`, `ConceptArt`, `EndCredits`,
  `FrontCredits`, `MessageBox`, `Saving`, `Loading`, `SurveyPopup`, `Video`, `Map`, `Journal`,
  `AbandonDialog`, `DemoIntro`, `Motorforge`, `RadialSolos_{A,B,D}`, `Playlist`, `Countdown`,
  `BuildMenu_Faction_{A,B,D}`, `TC_<card>` (tutorial cards).

## 12. Renamed functions

| Address | Name |
|---|---|
| 0x46EDD0 | `FlashSystem_Create` |
| 0x4684C0 | `FlashSystem_Ctor` |
| 0x46A5F0 | `FlashSystem_InitLoader` |
| 0x4687A0 | `FlashSystem_ReleaseLoader` |
| 0x468670 | `FlashSystem_Shutdown` |
| 0x475AE0 | `FlashSystem_CreateRenderer` |
| 0x476A60 | `GRendererD3D9Impl_Ctor` |
| 0x4734F0 | `GFxRendererDF_Ctor` |
| 0x468900 | `FlashSystem_CreateMovie` |
| 0x468A50 | `FlashSystem_CreateAndLoadMovie` |
| 0x469070 | `FlashSystem_ReleaseMovie` |
| 0x469280 | `FlashSystem_AdvancePlayer` |
| 0x469570 | `FlashSystem_AdvanceMovie` |
| 0x46A0E0 | `FlashSystem_DisplayAll` |
| 0x4691E0 | `FlashSystem_PushInputFocus` |
| 0x4708C0 | `FlashMovie_Ctor` |
| 0x468B30 | `FlashMovie_BindDUIMovie` |
| 0x468C80 | `FlashMovie_Load` |
| 0x470AC0 | `FlashMovie_RequestTextures` |
| 0x469650 | `FlashMovie_RouteInput` |
| 0x470C40 | `FlashMovie_SetTransparent` |
| 0x470CD0 | `FlashMovie_GotoLabeledFrame` |
| 0x471430 | `FlashMovie_AttachBinkBackground` |
| 0x471AE0 / 0x471B40 / 0x471C10 | `FlashMovie_SetVariableString` / `…StringW` / `…Number` |
| 0x471BA0 | `FlashMovie_SetDirty` |
| 0x471750 / 0x4717C0 / 0x471830 / 0x4718A0 | `FlashMovie_SetRootBool` / `…Number` / `…String` / `…StringW` |
| 0x471910 / 0x471980 / 0x471A00 / 0x471A70 | `FlashMovie_SetRootBoolAt` / `…NumberAt` / `…StringAt` / `…StringWAt` |
| 0x4760F0 | `FlashFileOpener_OpenFile` |
| 0x46AD30 | `FlashFileOpener_RemapPath` |
| 0x475EF0 | `FlashFile_OpenBlob` |
| 0x475D80 | `FlashImageCreator_CreateImage` |
| 0x4418E0 | `SplitPath` |
| 0x467660 | `FlashTranslator_GetCaps` |
| 0x467670 | `FlashTranslator_Translate` |
| 0x467810 | `FlashText_ExpandMarkup` |
| 0x46FB80 | `InputAliases_Find` |
| 0x442AA0 | `LineCode_FromString` |
| 0x447D30 | `StrHashFNV` |
| 0x467C10 | `FlashFSCommandHandler_Ctor` |
| 0x467C60 | `FlashFSCommandHandler_Callback` |
| 0x4680A0 | `FlashFS_GetLineCodeText` |
| 0x4681A0 | `FlashFS_GetCurrentLanguage` |
| 0x468200 | `FlashFS_IsNativeResolution` |
| 0x468260 | `FlashFS_LuaBegin` |
| 0x468350 | `FlashFS_LuaExec` |
| 0x46A3A0 | `FlashFS_LuaEvalReturn` |
| 0x46A1A0 | `FlashFS_StoreLuaResults` |
| 0x46F760 | `DUIMovie_RegisterAttributes` |
| 0x46B2D0 | `FlashConfig_RegisterAttributes` |
| 0x46AFA0 | `FontMapper_RegisterAttributes` |
| 0x46A580 | `MapFontFlags_RegisterEnum` |
| 0x46C460 | `FlashConfig_GetHandle` |
| 0x46A540 | `FlashConfig_Resolve` |
| 0x46C370 | `PhysicalInputIcons_GetHandle` |
| 0x67EEB0 | `InputAliases_RegisterAttributes` |
| 0x494030 | `StringTables_RegisterAttributes` |
| 0x494510 | `LineCodeData_RegisterAttributes` |
| 0x7E1CB0 | `HUDSkin_RegisterAttributes` |
| 0x7E1A60 | `AlbumCover_RegisterAttributes` |
| 0x7E1650 | `AlbumCoverFX_RegisterAttributes` |
| 0x7DFBC0 | `BuddhaHUD_CreateMovies` |
| 0x7DCDC0 | `BuddhaHUD_EnableFlash` |
| 0x4AA780 | `HUD_GetLocalPlayerHUD` |
| 0x7E2860 | `Lua_hud_EnableFlash` |
| 0x7E26F0 | `Lua_hud_SetAlbumCoverEffect` |
| 0x4AAC40 | `Lua_hud_DisplayLineCode` |
| 0x506440 | `CoFlashTexture_CreateMovie` |
| 0x6240F0 | `CcPlayFlashMovie_Start` |

## 13. Offline: frame rendering and font export

Code: `Brutal/gfxsvg.py` (SVG of one root frame), `Brutal/image.py` (BC1/BC3 to RGBA, PNG
writer), `Brutal/ttf.py` (DefineFont3 to TrueType); CLI `python -m Brutal ui render` and
`python -m Brutal ui fonts`. Gates: `Tests/corpus_render.py`, `Tests/corpus_ttf.py`. None of this
is engine code; it reproduces what the data describes, with the gaps listed below.

**Movie content in the corpus** (gate `Tests/corpus_render.py`, every tag of the 80 movies, root
and sprites): 1,410 DefineShape 1–4, 19 DefineMorphShape 1–2, 760 DefineEditText, 40,870
PlaceObject2/3, all decoded to their exact length. Fill styles: 981 solid and 3,777 bitmap; no
gradient. Bitmap fills: 1,904 name the movie's own DefineExternalImage, 99 an id imported from
`Shared/ControllerIcons.swf` (an exported external image of `PhysicalInputIcons.gfx`, §10), 1,774
name 65535 in a style no edge selects. Filters: Glow 157, DropShadow 24. Blend modes: multiply 18,
add 3, screen 1. No placement has a ClipDepth (no mask layer anywhere). 33 placements carry clip
actions.

**What a frame is.** The root display list is replayed from frame 0 through the requested frame
(PlaceObject2/3, RemoveObject2); `--label` picks the frame holding that FrameLabel. Several screens
are empty at frame 0 and are driven to a label by their scripts: FrontEnd (labels from
`Title Screen` at frame 2 to `attract_end`), MissionTitle (frame 0 holds only `Start` and a
DoAction; the card is placed in later frames). Nested sprites show their frame 0 by default; with
`--settle` each sprite shows the first frame whose DoAction holds a top-level ActionStop (0x07),
the frame a tweened panel rests on (Pause `mainMenu` stops at frame 8, `fullyOpen`, with `Main` slid
in from y = −8600 to −840 twips). The settle rule is a heuristic over bytecode, not execution: a
`stop()` behind a branch counts.

**Rendered:** depth order, matrices, colour transforms (alpha-only as opacity, otherwise an sRGB
colour matrix), blend modes multiply / screen / lighten / darken / difference / overlay / hardlight
/ add (`plus-lighter`), clip layers as SVG clip paths of the clip character's fill geometry (path
exercised by a synthetic display list only, since the corpus has none), shapes with every fill
style's edges joined into closed contours (fill1 forward, fill0 reversed; even-odd, non-zero for
DefineShape4 with the winding flag), line styles, gradients (`userSpaceOnUse`, the ±16384-twip
square through the fill matrix), bitmap fills as patterns of the decoded texture (cropped to the
DefineExternalImage size), morph shapes interpolated at the placement ratio, imported characters
and bitmaps, edit texts set in DefineFont3 outlines, Glow / DropShadow (outer) as SVG blur filters.

Text: the field's own DefineFont3 when it has glyphs; a glyph-less DefineFont3, an HTML `face`, or
a `gfxfontlib.swf` import resolves by name through `FontMap` to the shared font movie (§5). HTML
subset: `p align`, `br`, `font face/size/color/letterSpacing/kerning`, `textformat`, `li`. Line
codes (`*XXXX`) are drawn as their keys and are not wrapped; translator markup (`/alias/`, §9) is
drawn literally. **Assumptions** (Flash Player conventions, not verified against the Scaleform 2.1
code): 2 px gutter inside the field, first baseline at gutter + ascent, line step ascent + descent +
leading, word wrap at spaces; filter blur as Gaussian stdDeviation = blur px / 2; quality passes
ignored.

**Not rendered:** ActionScript (frame scripts, clip actions, variables: whatever a script shows,
hides, moves or fills in), the translator's line-code lookup, inner / knockout Glow and DropShadow,
the other filter kinds, blend modes subtract / invert / alpha / erase, gradient linear-RGB
interpolation, CacheAsBitmap, HTML `img`, text auto-size growth, line strokes inside clip geometry.
Sprites do not advance with the root when a later frame or label is rendered.

**Images.** BC1 / BC3 per the D3D definitions (bit-replicated RGB565, BC1 3-colour mode when
`c0 <= c1`, BC3 colour block always 4-colour, 8- or 6-level alpha), interpolants rounded to nearest;
gate: bit-exact on synthetic blocks, within 1 level of ImageMagick's DDS decoder on 27 sampled UI
textures.

**TrueType.** `unitsPerEm` 2048 = 10 DefineFont3 units (the shared fonts only use multiples of 10),
y flipped, quadratic contours copied point for point (`Q` control = off-curve point, closing point
dropped); contour direction by nesting depth for the non-zero rule; `hmtx` from the layout
advances, `kern` format 0 from the layout pairs whose two characters exist (22 pairs across the
shared fonts name characters the fonts lack and are dropped), `hhea` ascender / descender / line
gap from the layout block, `cmap` format 4. Gate: all three shared fonts and the 42 embedded fonts
re-read by an independent parser (table and file checksums, loca, maxp maxima, bboxes, cmap,
hmtx, kern, every contour equal to its source, cyclically, either direction) and, when installed,
by fontTools.

## 14. Open questions

- The object at image-file-info +0x14 whose `+8` string is the first `UI/Flash/%s/%s` component
  (assumed ExporterInfo prefix; the data check agrees 79/79) and how the resource lookup sub_407700
  ignores the `.dds` extension.
- Where GFx rewrites the import `Shared/ControllerIcons.swf` to `…/Shared/ControllerIcons.gfx`.
- GFx state IDs 18 and 20: class names inferred from the calls made on them (font library, font map).
- Movie-view slots +0x78 (int stored at +0xDC) and +0x90 (byte at +0x100) — called by the game,
  meaning unknown.
- The external FSCommand listener at `FlashSystem+0x73C` (written by sub_6D1420, sub_8BF420).
- The `int` in `InputAliases` tuples; the navigator button slot meanings (0xF78B68) beyond the key
  letters; the pad-family string source in `FlashText_ExpandMarkup`.
- The binary layout of `StringTable` resources and the build of the merged table at `dword_1009CC4`
  (sub_4068D0, sub_492CC0).
- The game-code Invoke scan is a heuristic; an `Invoke` through a stored function pointer would not
  be found.
