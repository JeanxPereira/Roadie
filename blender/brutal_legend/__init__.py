"""Brutal Legend importer: browse the game's bundles and import meshes, rigs, materials,
textures, morphs and animations straight from Win/Packs."""

import os

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup, UIList

from .brutal import paths

_LIB = None


def prefs():
    return bpy.context.preferences.addons[__package__].preferences


def library():
    global _LIB
    from .brutal.library import Library
    packs = os.path.join(prefs().game_dir, "Win", "Packs")
    if _LIB is None or _LIB.packs != packs:
        _LIB = Library(packs)
        _LIB.packs = packs
    return _LIB


def cache_dir():
    p = prefs().cache_dir or os.path.join(bpy.utils.extension_path_user(__package__, create=True), "cache")
    os.makedirs(p, exist_ok=True)
    return p


class BL_Preferences(AddonPreferences):
    bl_idname = __package__

    game_dir: StringProperty(name="Game folder", subtype="DIR_PATH", default=paths.DEFAULT_GAME_DIR)
    cache_dir: StringProperty(name="Texture cache", subtype="DIR_PATH",
                              description="Where extracted DDS files go (empty: extension user folder)")

    def draw(self, context):
        self.layout.prop(self, "game_dir")
        self.layout.prop(self, "cache_dir")


class BL_Result(PropertyGroup):
    path: StringProperty()
    type: StringProperty()


class BL_UL_results(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        icon = {"Mesh": "MESH_DATA", "AnimResource": "ACTION", "Texture": "TEXTURE",
                "Material": "MATERIAL", "Rig": "ARMATURE_DATA"}.get(item.type, "FILE")
        layout.label(text=item.path, icon=icon)


class BL_OT_search(Operator):
    bl_idname = "brutal_legend.search"
    bl_label = "Search"
    bl_description = "Search the game's resources"

    def execute(self, context):
        s = context.scene
        words = s.bl_query.lower().split()
        want = {"MESH": ("Mesh",), "ANIM": ("AnimResource",), "TEX": ("Texture",),
                "ALL": ("Mesh", "AnimResource", "Texture", "Material", "Rig")}[s.bl_filter]
        s.bl_results.clear()
        n = 0
        for _b, e in library().entries():
            if e.type in want and all(w in e.name.lower() for w in words):
                r = s.bl_results.add()
                r.path, r.type = e.name, e.type
                n += 1
                if n >= 2000:
                    break
        self.report({"INFO"}, f"{n} results")
        return {"FINISHED"}


class BL_OT_import(Operator):
    bl_idname = "brutal_legend.import_resource"
    bl_label = "Import"
    bl_description = "Import the selected resource"
    bl_options = {"REGISTER", "UNDO"}

    materials: BoolProperty(name="Materials", default=True)
    textures: BoolProperty(name="Textures", default=True)
    skeleton: BoolProperty(name="Skeleton & skin", default=True)
    morphs: BoolProperty(name="Morph targets", default=True)
    shading: bpy.props.EnumProperty(
        name="Shading", default="GAME",
        items=[("GAME", "Game", "The game's own lighting model (EEVEE): Lambert sun + sky ramp + rim, "
                "Phong spec only where the material has it"),
               ("PBR", "PBR", "Principled BSDF approximation, for export to other engines")])
    skip_nomaterial: BoolProperty(name="Hide 'nomaterial' helpers", default=True)
    path: StringProperty(options={"HIDDEN"})
    type: StringProperty(options={"HIDDEN"})

    def invoke(self, context, event):
        s = context.scene
        if not self.path and 0 <= s.bl_index < len(s.bl_results):
            r = s.bl_results[s.bl_index]
            self.path, self.type = r.path, r.type
        return self.execute(context)

    def execute(self, context):
        from . import importer
        if not self.path:
            self.report({"ERROR"}, "Nothing selected")
            return {"CANCELLED"}
        lib = library()
        col = context.collection
        if self.type == "Mesh":
            obj, arm = importer.build_mesh(lib, self.path, self, col, cache_dir())
            target = arm or obj
        elif self.type == "AnimResource":
            from . import anim
            arm = context.active_object
            if not arm or arm.type != "ARMATURE":
                self.report({"ERROR"}, "Select an imported armature first")
                return {"CANCELLED"}
            anim.apply(lib, self.path, arm)
            target = arm
        elif self.type == "Texture":
            img = importer.load_texture(lib, self.path, cache_dir())
            self.report({"INFO"}, f"Loaded image {img.name}")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, f"{self.type} import not supported")
            return {"CANCELLED"}
        for o in context.selected_objects:
            o.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        return {"FINISHED"}


class BL_OT_rig_anims(Operator):
    bl_idname = "brutal_legend.import_rig_anims"
    bl_label = "Import All Animations"
    bl_description = "Import every animation made for the selected armature's rig as browsable actions"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Clips", default="OWN",
        items=[("OWN", "Character's own", "Locomotion, gestures, lip-sync in the character's folder"),
               ("ALL", "Everything", "Also cutscenes, mounts, co-ops and vignettes (slow, large file)")])
    match: StringProperty(name="Only names with",
                          description="Space-separated words; keep clips whose name contains any (empty: all)")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        from . import anim
        arm = context.active_object
        if not arm or arm.type != "ARMATURE" or "bl_rig_hash" not in arm:
            self.report({"ERROR"}, "Select an imported armature first")
            return {"CANCELLED"}
        lib = library()
        own = arm.get("bl_path", "").rsplit("/", 2)[0] + "/"  # characters/.../a01_avatar/
        have = {a.get("bl_path") for a in bpy.data.actions}
        clips = [c for c in anim.rig_clips(lib, int(arm["bl_rig_hash"], 16), self.scope == "OWN", own)
                 if c not in have]
        words = self.match.lower().split()
        if words:
            clips = [c for c in clips if any(w in c.rsplit("/", 1)[-1].lower() for w in words)]
        wm = context.window_manager
        wm.progress_begin(0, len(clips))
        bad = 0
        for i, c in enumerate(clips):
            try:
                anim.apply(lib, c, arm, set_scene=False)
            except Exception as ex:  # one broken clip must not stop the batch
                bad += 1
                print("brutal_legend:", c, ex)
            wm.progress_update(i)
        wm.progress_end()
        self.report({"INFO"}, f"{len(clips) - bad} animations imported" + (f", {bad} failed" if bad else ""))
        return {"FINISHED"}


class BL_UL_actions(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        layout.label(text=item.name, icon="ACTION")
        layout.label(text=f"{int(item.frame_range[1])}f")

    def filter_items(self, context, data, propname):
        arm = context.active_object
        want = arm.get("bl_rig_hash") if arm else None
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item if a.get("bl_rig_hash") == want and want else 0 for a in items]
        if self.filter_name:
            f = self.filter_name.lower()
            flags = [x if f in a.name.lower() else 0 for x, a in zip(flags, items)]
        order = bpy.types.UI_UL_list.sort_items_by_name(items) if self.use_filter_sort_alpha else []
        return flags, order


def _play_action(scene, context):
    from . import anim
    arm = context.active_object
    if 0 <= scene.bl_action_index < len(bpy.data.actions) and arm and arm.type == "ARMATURE":
        act = bpy.data.actions[scene.bl_action_index]
        if act.get("bl_rig_hash") == arm.get("bl_rig_hash"):
            anim.play(arm, act)


def _weather_items(self, context):
    try:
        lib = library()
    except Exception:
        return [("", "(set the game folder)", "")]
    names = sorted(e.name for _b, e in lib.entries("Weather"))
    return [(n, n.replace("environments/climates/", ""), n) for n in names] or [("", "(none)", "")]


class BL_OT_weather(Operator):
    bl_idname = "brutal_legend.apply_weather"
    bl_label = "Apply Weather"
    bl_description = "Light the scene with a game Weather (sun, sky ramp, rim, fog), as the engine does"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import gameshader
        s = context.scene
        if not s.bl_weather_pick:
            return {"CANCELLED"}
        gameshader.apply_weather(s, library(), s.bl_weather_pick, s.bl_time_of_day)
        self.report({"INFO"}, f"Weather {s.bl_weather_pick}")
        return {"FINISHED"}


class BL_PT_browser(Panel):
    bl_label = "Brutal Legend"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Brutal Legend"

    def draw(self, context):
        s = context.scene
        col = self.layout.column()
        row = col.row(align=True)
        row.prop(s, "bl_query", text="", icon="VIEWZOOM")
        row.operator(BL_OT_search.bl_idname, text="", icon="FILE_REFRESH")
        col.prop(s, "bl_filter", expand=True)
        col.template_list("BL_UL_results", "", s, "bl_results", s, "bl_index", rows=12)
        col.operator(BL_OT_import.bl_idname, icon="IMPORT")
        arm = context.active_object
        if arm and arm.type == "ARMATURE" and "bl_rig_hash" in arm:
            box = self.layout.box()
            box.label(text=f"Animations: {arm.name}", icon="ARMATURE_DATA")
            box.operator(BL_OT_rig_anims.bl_idname, icon="IMPORT")
            box.template_list("BL_UL_actions", "", bpy.data, "actions", s, "bl_action_index", rows=10)
            box.label(text="Click a clip to play it (body + face)", icon="INFO")
        box = self.layout.box()
        box.label(text="Lighting", icon="LIGHT_SUN")
        box.prop(s, "bl_weather_pick", text="")
        box.prop(s, "bl_time_of_day")
        box.operator(BL_OT_weather.bl_idname, icon="WORLD")


classes = (BL_Preferences, BL_Result, BL_UL_results, BL_OT_search, BL_OT_import, BL_OT_rig_anims,
           BL_UL_actions, BL_OT_weather, BL_PT_browser)


@bpy.app.handlers.persistent
def _sync_sun(scene, depsgraph=None):
    from . import gameshader
    gameshader.sync_sun_from_lamp(scene)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    S = bpy.types.Scene
    S.bl_query = StringProperty(name="Search", options={"TEXTEDIT_UPDATE"})
    S.bl_filter = bpy.props.EnumProperty(items=[("MESH", "Meshes", ""), ("ANIM", "Anims", ""),
                                                ("TEX", "Textures", ""), ("ALL", "All", "")])
    S.bl_results = CollectionProperty(type=BL_Result)
    S.bl_index = IntProperty()
    S.bl_action_index = IntProperty(update=_play_action)
    S.bl_weather_pick = bpy.props.EnumProperty(name="Weather", items=_weather_items)
    S.bl_time_of_day = bpy.props.FloatProperty(
        name="Sun elevation", default=90.0, min=40.0, max=140.0,
        description="The engine's time-of-day angle (90 = noon; folded into 40..140 like the game)")
    bpy.app.handlers.depsgraph_update_post.append(_sync_sun)


def unregister():
    S = bpy.types.Scene
    if _sync_sun in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_sun)
    for p in ("bl_query", "bl_filter", "bl_results", "bl_index", "bl_action_index", "bl_weather_pick", "bl_time_of_day"):
        delattr(S, p)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
