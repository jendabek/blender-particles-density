#TODO count the density by area covered instead of vertices total vs group count
#TODO further optimization of update_particles_count() -  update only visible p_systems
#TODO further optimization - some checkings should be processed in a time interval
#TODO edit feature - adjust density of all particle systems that use  the same v. group - make it more clear (disbled ones should be modifier as well?)
#TODO add feature - enable / disable on all;


bl_info = {
    "name": "Density",
    "author": "Jan Kadeřábek (jendabek@gmail.com)",
    "version": (0, 8, 5),
    "blender": (2, 80, 0),
    "location": "Properties > Particle System",
    "description": "Adjusts the particles count automatically to preserve the desired density",
    "category": "Particles"}

import bpy
import math
import bmesh
import time

from bpy.props import (StringProperty,
                         BoolProperty,
                         IntProperty,
                         FloatProperty,
                         FloatVectorProperty,
                         EnumProperty,
                         PointerProperty,
                         )
from bpy.types import (Panel,
                         Operator,
                         AddonPreferences,
                         PropertyGroup,
                         )
from bpy.app.handlers import persistent



class Globals():
    update_count_tolerance = 0.1
    v_groups_average_weight_cache = None
    allow_update_by_ui = True
    updated_timestamp = 0
    update_interval = 1
    use_update_interval = False
    last_obj = None
    last_mode = None
    last_p_systems_count = 0
    last_p_system = None
    last_density_group = None

class PD_Weight_Paint_Mode_Exit(bpy.types.Operator):
    bl_idname = "view3d.weight_paint_mode_exit"
    bl_label = "Weight Paint Mode Exit"
    bl_description = "Exits to Object mode"

    def execute(self, context): 
        bpy.ops.object.mode_set(mode="OBJECT")
        return {'FINISHED'}

    @classmethod
    def poll(cls, context):
        return bpy.context.mode == "PAINT_WEIGHT"

class PD_Weight_Paint_Particle_System_Vertex_Group_Density(bpy.types.Operator):
    bl_idname = "view3d.weight_paint_by_particle_system"
    bl_label = "Weight Paint Particle System Vertex Group Density"
    bl_description = "Enters weight painting of this vertex group"

    def execute(self, context): 
        obj = context.object
        p_system_active = obj.particle_systems.active
        if p_system_active and p_system_active.vertex_group_density:
            for v_group in obj.vertex_groups:
                if v_group.name == p_system_active.vertex_group_density:
                    if obj.vertex_groups.active_index != v_group.index:
                        obj.vertex_groups.active_index = v_group.index
                    break

            if obj.mode != "WEIGHT_PAINT":
                bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
        
        return {'FINISHED'}

class PD_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    density_tolerance: bpy.props.IntProperty(
        name = "Update Tolerance (%)",
        description = "The count will be adjusted only when the difference from the current one reaches the given %.\nUseful when working with large amount of particles to avoid slowdowns caused by changing the count with every small edits",
                min = 0,
                max = 100,
        default = 10)

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.prop(self, "density_tolerance", slider=True)
    
class PD_OptionsPanel_Properties(PropertyGroup):
    
    def update_enabled(self, context):
        obj = context.active_object
        
        
        p_system = obj.particle_systems.active
        p_system.settings["density_settings"]["enabled"] = self.enabled

        # set density based on the current particles count
        if self.enabled == True:
            new_density = get_p_system_density(obj, p_system)
            if(new_density == 0):
                self.density = 1
            else:
                self.density = new_density
    
    def update_density(self, context):
        obj = context.active_object
        obj.particle_systems.active.settings["density_settings"]["density"] = self.density

        
        if(Globals.allow_update_by_ui):
            update_particles_count(obj)
    
    def multiply_density_v_group(self, context):
        
        if(Globals.allow_update_by_ui):

            obj = context.active_object
            v_group_density = obj.particle_systems.active.vertex_group_density

            if v_group_density:
                for psystem in obj.particle_systems:

                    if(psystem.vertex_group_density == v_group_density and psystem.settings["density_settings"]["enabled"]):
                        psystem.settings["density_settings"]["density"] *= self.density_same_v_group_multiplier

            Globals.allow_update_by_ui = False

            self.density_same_v_group_multiplier = 1
            update_particles_count(obj)

            Globals.allow_update_by_ui = True

    def multiply_density(self, context):
        
        if(Globals.allow_update_by_ui):

            obj = context.active_object
            obj.particle_systems.active.settings["density_settings"]["density"] *= self.density_multiplier

            Globals.allow_update_by_ui = False

            self.density_multiplier = 1
            update_particles_count(obj)

            Globals.allow_update_by_ui = True

    enabled: BoolProperty(
        default=False,
        update=update_enabled,
        description="Enables / disables the automatic particles count adjustment for this particle system"
    )
    density: FloatProperty(
        min=0,
        update=update_density,
        default=1,
        description="Sets the particles density for this particle system"
    )
    density_multiplier: FloatProperty(
        default = 1,
        update=multiply_density,
        description="Mutliplies the density by the given multiplier"
    )

    density_same_v_group_multiplier: FloatProperty(
        default = 1,
        update=multiply_density_v_group,
        description="Multiplies the density for all particle systems which use this vertex group"
    )
    
class PD_OptionsPanel(bpy.types.Panel):
    bl_idname = "PANEL_PT_particles_density_1"
    bl_label = "Density"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "particle"
    
    @classmethod
    def poll(cls, context):
        return context.active_object is not None and len(context.active_object.particle_systems) > 0

    def draw(self, context):
        layout = self.layout
        p_system = context.object.particle_systems.active
        
        box = layout.box()

        row = box.row()
        row.prop(context.scene.optionspanel_properties, "enabled", text='Enabled')

        density_label = "Particles per"
        unit_system = bpy.context.scene.unit_settings.system
        if unit_system == "METRIC":
            density_label += " Meter"
        elif unit_system == "IMPERIAL":
            density_label += " Foot"
        else:
            density_label += " Unit"

        row = box.row()
        row.enabled = context.scene.optionspanel_properties.enabled
        # split = row.split(0.6)

        # left = split.column(align=True)
        row.prop(context.scene.optionspanel_properties, "density", text=density_label)
        # left.prop(context.scene.optionspanel_properties, "density", text=density_label)

        # right = split.column()
        # right.prop(context.scene.optionspanel_properties, "density_multiplier", text="Multiply")
        
        # layout.separator()

        # if p_system.vertex_group_density:

        #     box = layout.box()

        #     row = box.row()
        #     row.label(text=p_system.vertex_group_density + " - Vertex Group:")

        #     row = box.row()
        #     row.operator("view3d.weight_paint_by_particle_system", text="Paint Weights", icon="MOD_VERTEX_WEIGHT")
            
            
        #     op = row.operator("view3d.weight_paint_mode_exit", text="Exit Paint", icon="FILE_PARENT")
            
        #     row = box.row()
        #     row.prop(context.scene.optionspanel_properties, "density_same_v_group_multiplier", text="Multiply")

        #     layout.separator()
        
        # box = layout.box()

        # row = box.row()
        # row.label(text="Options:")
        # row = box.row()
        # row.prop(context.preferences.addons[__name__].preferences, "density_tolerance", slider=True, text="Update Tolerance (%)")

class PD_OptionsPanel_Density_Vertex_Group(bpy.types.Panel):
    bl_idname = "PANEL_PT_particles_density_vertex_group_1"
    bl_parent_id = "PANEL_PT_particles_density_1"
    bl_context = "particle"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_label = "Vertex Group Options"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        p_system = context.object.particle_systems.active
        if p_system.vertex_group_density:
            return True
        else:
            return False

    def draw(self, context):
        layout = self.layout
        p_system = context.object.particle_systems.active

        box = layout.box()
        row = box.row()
        row.label(text=p_system.vertex_group_density + ":")

        row = box.row()
        row.operator("view3d.weight_paint_by_particle_system", text="Paint Weights", icon="BRUSH_DATA")
        
        op = row.operator("view3d.weight_paint_mode_exit", text="Exit Paint", icon="FILE_PARENT")
        
        row = box.row()
        row.prop(context.scene.optionspanel_properties, "density_same_v_group_multiplier", text="Multiply Density")

        layout.separator()

class PD_OptionsPanel_Extra(bpy.types.Panel):
    bl_idname = "PANEL_PT_particles_density_extra_1"
    bl_parent_id = "PANEL_PT_particles_density_1"
    bl_context = "particle"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_label = "Global Options"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        row = box.row()
        row.prop(context.preferences.addons[__name__].preferences, "density_tolerance", slider=True, text="Update Tolerance (%)")

def update_v_groups_average_weight_cache():
    obj = bpy.context.object
    groups_weight_sums = {}

    for v in obj.data.vertices:
        for g in v.groups:
            if(g.group in groups_weight_sums):
                groups_weight_sums[g.group] = groups_weight_sums.get(g.group, 0) + g.weight
            else:
                groups_weight_sums[g.group] = 0
    
    if Globals.v_groups_average_weight_cache is not None:
        Globals.v_groups_average_weight_cache.clear()
    else:
        Globals.v_groups_average_weight_cache = {}

    vertices_count = len(obj.data.vertices)
    
    for v_group in obj.vertex_groups:
        
        average = 0

        if v_group.index in groups_weight_sums:
            average = groups_weight_sums[v_group.index] / vertices_count
    
        Globals.v_groups_average_weight_cache[v_group.index] = {"v_group_name": v_group.name, "weight_average": average}

    print("weights average cache updated")

def get_mesh_area(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    mesh_area = sum(f.calc_area() for f in bm.faces)
    bm.free()

    return mesh_area

def get_p_system_density(obj, p_system):

    density = 0

    # update_v_groups_average_weight_cache()

    if p_system.vertex_group_density:
            v_group = obj.vertex_groups[p_system.vertex_group_density]
            weight_average = Globals.v_groups_average_weight_cache[v_group.index]["weight_average"]
    else:
            weight_average = 1
    
    mesh_area = get_mesh_area(obj)

    if weight_average > 0 and mesh_area > 0:
        density = p_system.settings.count / weight_average / mesh_area

    return density

def update_particles_count(obj):
        
    time_start_updating = time.time()
    particle_systems = obj.particle_systems
    
    if len(particle_systems) == 0:
        return
    
    mesh_area = get_mesh_area(obj)
    v_groups = obj.vertex_groups

    for p_system in particle_systems:
            
        if(p_system.settings["density_settings"]["enabled"] == False):
            continue

        if p_system.vertex_group_density:
            v_group = v_groups[p_system.vertex_group_density]
            weight_average = Globals.v_groups_average_weight_cache[v_group.index]["weight_average"]
        else:
            weight_average = 1

        p_system_density = p_system.settings["density_settings"]["density"]
        new_particles_count = round(weight_average * p_system_density * mesh_area)

        if p_system.settings.count != new_particles_count:
            
            if p_system.settings.count == 0 or abs(p_system.settings.count - new_particles_count) / p_system.settings.count > (bpy.context.preferences.addons[__name__].preferences.density_tolerance / 100):
                p_system.settings.count = new_particles_count
                print(p_system.name + " count updated")

    print("All particle systems checked in " + str(time.time() - time_start_updating))

@persistent
def on_scene_update(scene):

    obj = bpy.context.active_object
    
    #TODO add obj.type in ['MESH']?

    if obj is None or len(obj.particle_systems) == 0:
        return

    # if Globals.use_update_interval and (time.time() - Globals.updated_timestamp) < Globals.update_interval and Globals.last_obj == obj:
    #   return

    
    #init custom particle settings data
    for p_system in obj.particle_systems:
        try:
            p_system.settings["density_settings"]
        except KeyError:
            p_system.settings["density_settings"] = {"enabled": False, "density": 1}
            

    p_system_active = obj.particle_systems.active

    p_system_active_enabled = bool(p_system_active.settings["density_settings"]["enabled"])
    p_system_active_density = p_system_active.settings["density_settings"]["density"]


    Globals.allow_update_by_ui = False
    
    #to avoid UI lags, set values only if changed
    if scene.optionspanel_properties.enabled != p_system_active_enabled:
        scene.optionspanel_properties.enabled = p_system_active_enabled

    if scene.optionspanel_properties.density != p_system_active_density:
        scene.optionspanel_properties.density = p_system_active_density

    Globals.allow_update_by_ui = True


    #update if necessarry
    updates_needed = False

    
    if(
        Globals.v_groups_average_weight_cache is None or
        obj != Globals.last_obj or
        len(obj.vertex_groups) != len(Globals.v_groups_average_weight_cache) or
        len(obj.particle_systems) != Globals.last_p_systems_count or
        (obj.particle_systems.active == Globals.last_p_system and obj.particle_systems.active.vertex_group_density != Globals.last_density_group) or
        bpy.context.mode != Globals.last_mode):

        updates_needed = True

    else :
        for v_group in obj.vertex_groups:
            if Globals.v_groups_average_weight_cache[v_group.index]["v_group_name"] != v_group.name:
                updates_needed = True
                break
                
    if updates_needed == False:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for update in depsgraph.updates:
            if update.id.original == obj and update.is_updated_geometry:
                updates_needed = True
                break
                    
    if updates_needed:
        update_v_groups_average_weight_cache()
        update_particles_count(obj)
        Globals.updated_timestamp = time.time()
    
    Globals.last_density_group = obj.particle_systems.active.vertex_group_density
    Globals.last_p_system = obj.particle_systems.active
    Globals.last_p_systems_count = len(obj.particle_systems)
    Globals.last_obj = obj
    Globals.last_mode = bpy.context.mode

classes = [
    PD_Weight_Paint_Particle_System_Vertex_Group_Density,
    PD_Weight_Paint_Mode_Exit,
    PD_AddonPreferences,
    PD_OptionsPanel_Properties,
    PD_OptionsPanel,
    PD_OptionsPanel_Density_Vertex_Group,
    PD_OptionsPanel_Extra
]

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.optionspanel_properties = PointerProperty(type=PD_OptionsPanel_Properties)
    bpy.app.handlers.depsgraph_update_post.append(on_scene_update)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(on_scene_update)
    del bpy.types.Scene.optionspanel_properties
    for c in classes:
        bpy.utils.unregister_class(c)
    

if __name__ == "__main__":
    register()