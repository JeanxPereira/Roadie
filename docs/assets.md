# Asset support roadmap

Everything the PC install holds, measured on 2026-10-29 (census of all 71,095 bundle resources in
89 types, plus the loose `Data/` and `Win/Audio` folders). Status: **done** = decoder + corpus gate;
**parse** = generic text-object parser reads it (`brutal/textobj.py`, 11,678/11,678 in 69 types)
but nothing builds on it yet; **todo** = binary, undecoded.

## 1. Characters, props, vehicles

| Type | Count | Status | What it is / what it unlocks in Blender |
|---|---:|---|---|
| Mesh | 7,711 | **done** | geometry, skin, morphs; 694 MB |
| Rig | 302 | **done** | skeleton, inverse bind, flex (face) channel names |
| Texture | 10,672 | **done** | DDS (DXT1/DXT5, DXT5nm normals); 1.6 GB |
| Material | 2,748 | **done** | 25 shader families; textures, colors, blend modes |
| AnimResource | 15,866 | in progress | compressed skeletal + float (face) tracks; 111 MB |
| MeshSet | 3,921 | parse | LOD chain + per-LOD material list for a mesh (`LODData{Mesh=@..;Materials=[..]}`) → import the right LOD / full set |
| Outfit | 373 | parse | character variants (beard, black metal, DLC outfits) → mesh/material swaps |
| Stance, ComboAnim, ComboPose, AnimMap | 484 / 203 / 97 / 2 | parse | which animations a character uses per state → animation library per character |
| AttachmentPointTable | 65 | parse | sockets (weapons, riders) → empties/bone constraints |
| GibData | 152 | parse | dismemberment pieces and stumps → gib collections |
| SimulationData | 63 | parse | secondary motion / cloth bone setup |
| FurData | 4 | todo | fur shells (mastodon etc.) |
| PhysicsRigidBody | 1,593 | todo | Havok packfile (`57E0E057`) |
| VehicleKeyframeData | 129 | todo | scripted vehicle paths |

## 2. Maps / worlds

26 levels: `continent3` (the main open world, 16 × 16 tiles of 512 m), 13 DLC worlds
(`dlc1_*`, 8 × 8), 9 stage-battle maps (`sk_1..9`, 8 × 8), plus interiors/test levels.

| Type | Count | Status | What it is |
|---|---:|---|---|
| LevelData | 26 | parse | the world: tile grid, scale (512 × 1024 × 512), origin, climate, ocean, global objects, quad-tile LOD lists, world states |
| Heightfield | 1,667 | todo | per-tile height map, 524,288 bytes = 512 × 512 × u16; 879 MB → terrain mesh |
| QuadTileData | 2,188 | todo | terrain render tiles, 4 LOD levels |
| RndTileData, PhysicalSurfaceMap | 1,667 each | todo | terrain material blend / surface type per tile (`blend`) |
| TerrainMaterial | 108 | parse | terrain layer materials → terrain shader |
| ObjectData | 3,279 | todo (structure seen) | placed objects: `objd` header, `prot` records with position + quaternion + prototype name + text overrides → instanced props |
| PrototypeResource | 3 | todo | entity templates (`all.proto`) — needed to turn a placed prototype into its mesh |
| AmbTileData, AmbMeshDefinition | 163 / 42 | todo / parse | scattered ambient meshes (grass, rocks, debris) |
| CollisionShape | 4,946 | todo | Havok packfiles (`57E0E057`) → collision meshes |
| OceanData, WangTileset | 5 / 1 | parse / todo | ocean settings; tileable texture set |
| PathTileData, NavigationSystemGraph | 2,052 / 1 | todo | AI navigation (low priority) |

## 3. Lighting and atmosphere

| Type | Count | Status | What it is |
|---|---:|---|---|
| Weather | 146 | parse | the lighting rig of a time of day: `SunLight` (RSALight colour, intensity), `SunDeclination`, sky colours, fog (`FogSettings`), environment map, rim light, SSAO, post settings → Sun + World + fog |
| Climate | 47 | parse | a level's set of weathers (day/night cycle) |
| `lighting/textures/*` | — | done (DDS) | environment maps, glow gradients |
| `lighting/textures/rsalights/*` | 16 | todo | baked light data (0xB0 header, not DDS) |
| Cutscene lighting vignettes | — | parse | point lights authored as scripted entities (e.g. `dlc1/interactions/vignettes/lighting/*/pointlights`) |
| RenderLight* materials | 45+ | done (raw params) | light cards/volumes |

## 4. Cinematics

| Type | Count | Status | What it is |
|---|---:|---|---|
| Cutscene | 565 | parse | timeline scripts: actors, animations, shots, Lua commands |
| CameraPath | 1,437 | todo | camera animation → Blender cameras |
| CutsceneClump, VidSubtitles | 4 / 19 | parse | preload sets, subtitles |
| `Data/Cutscenes/*.bik` | 2.1 GB | external | Bink video (RAD tools / ffmpeg) |

## 5. Effects

| Type | Count | Status | What it is |
|---|---:|---|---|
| ParticleSystemData | 3,546 | todo | particle emitters (binary) |
| Effect, EffectTable, BuffEffect*, WaterEffectTable | 1,368 / 41 / 232 / 6 | parse | effect composition |

## 6. Audio, UI, text, gameplay (outside Blender's scope; CLI export)

| Area | Types / files | Status |
|---|---|---|
| Audio | `Win/Audio` 4.1 GB FMOD banks (DoubleFine Explorer already decodes FSB), AudioWavebankData/Markers, MusicSet, PlaylistResource, AudioEnvironment | parse (metadata) |
| UI | DUIMovie (79), FlashConfig, `Data/UI` 80 Scaleform movies (+ 159 Bink), HUDSkin, AlbumCover | **done** for movies, external images and fonts (`brutal/gfx.py`, `tests/corpus_gfx.py`); timelines/ActionScript not interpreted |
| Text | StringTable (40, all languages), Story, SystemLineCodes | parse |
| Scripts | Blob (362: Lua bytecode, `Data/Config/*.lua`) | todo |
| Gameplay | MissionData, Buff, TechTree, UnitInfos, RockSolo, EncounterTable, Difficulty, … (~30 types) | parse |

## Order of work for the Blender extension

1. Animation (codec in progress) → actions + face.
2. MeshSet / Outfit → import a whole character or prop with its LODs and variants.
3. Weather / Climate → sun, sky, fog, environment map: the game's lighting in one click.
4. World: Heightfield + terrain materials → terrain; ObjectData + PrototypeResource → placed props; Climate → lighting. Import a tile window around a point (continent3 is 8 × 8 km).
5. CameraPath + Cutscene → cinematics with cameras and actor animation.
6. Collision (Havok packfile), particles (approximate), ambient scatter.
