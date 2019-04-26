#TODO count the density by area covered instead of vertices total vs group count
#TODO further optimization of update_particles_count() -  update only visible p_systems
#TODO further optimization - some checkings should be processed in a time interval
#TODO add feature - adjust density of all particle systems that use  the same v. group
#TODO add feature - enable / disable on all


bl_info = {
	"name": "Density",
	"author": "Jan Kadeřábek (jendabek@gmail.com)",
	"version": (0, 8),
	"blender": (2, 79, 0),
	"location": "Properties > Particle System",
	"description": "",
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
	vgroups_average_weight_cache = None
	allow_update_by_ui = True
	updated_timestamp = 0
	update_interval = 1
	use_update_interval = False
	last_obj = None
	last_mode = None
	last_p_systems_count = 0
	last_p_system = None
	last_density_group = None

class Particles_Density(bpy.types.Operator):
	bl_idname = "object.particles_density"
	bl_label = "Particles Auto Count"

class ParticlesDensity_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    density_tolerance = bpy.props.IntProperty(
        name = "Update Tolerance (%)",
        description = "The count is adjusted when the density gets different from the current one by the given percentage.\nUseful when working with large amount of particles to avoid slowdowns caused by changing the particles count constantly",
				min = 0,
				max = 100,
        default = 10)

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.prop(self, "density_tolerance", slider=True)
	
class OptionsPanel_Properties(PropertyGroup):
	
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
	
	enabled = BoolProperty(
			default=False,
			update=update_enabled,
			description="Enables / disables the auto-adjustment of particles count (Emission Number) for this particle system to get the desired density"
			)
	density = FloatProperty(
			update=update_density,
			description="Particles count per 1 square distance unit",
			default=1,
			min=0
			)
	
class OptionsPanel(bpy.types.Panel):
	bl_idname = "panel.particles_density"
	bl_label = "Density"
	bl_space_type = "PROPERTIES"
	bl_region_type = "WINDOW"
	bl_context = "particle"
	
	@classmethod
	def poll(cls, context):
		return context.active_object is not None and len(context.active_object.particle_systems) > 0

	def draw(self, context):
		layout = self.layout

		# row = layout.row()
		# row.label(text="Particle System:")
		
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
		row.prop(context.scene.optionspanel_properties, "density", text=density_label)

		layout.separator()
		row = layout.row()
		row.label(text="Global Preferences:")
		
		box = layout.box()
		row = box.row()
		row.prop(context.user_preferences.addons[__name__].preferences, "density_tolerance", slider=True, text="Update Tolerance (%)")

def update_vgroups_average_weight_cache():
	obj = bpy.context.object
	groups_weight_sums = {}

	for v in obj.data.vertices:
		for g in v.groups:
			if(g.group in groups_weight_sums):
				groups_weight_sums[g.group] = groups_weight_sums.get(g.group, 0) + g.weight
			else:
				groups_weight_sums[g.group] = 0
	
	if Globals.vgroups_average_weight_cache is not None:
		Globals.vgroups_average_weight_cache.clear()
	else:
		Globals.vgroups_average_weight_cache = {}

	vertices_count = len(obj.data.vertices)
	
	for vgroup in obj.vertex_groups:
		if vgroup.index in groups_weight_sums:
			Globals.vgroups_average_weight_cache[vgroup.index] = {"vgroup_name": vgroup.name, "weight_average": (groups_weight_sums[vgroup.index] / vertices_count)}
		else:
			Globals.vgroups_average_weight_cache[vgroup.index] = {"vgroup_name": vgroup.name, "weight_average": 0}
	
	print("weights cache updated")

def get_mesh_area(obj):
	bm = bmesh.new()
	bm.from_mesh(obj.data)
	mesh_area = sum(f.calc_area() for f in bm.faces)
	bm.free()

	return mesh_area

def get_p_system_density(obj, p_system):

	density = 0

	# update_vgroups_average_weight_cache()

	if p_system.vertex_group_density:
			vgroup = obj.vertex_groups[p_system.vertex_group_density]
			weight_average = Globals.vgroups_average_weight_cache[vgroup.index]["weight_average"]
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
	vgroups = obj.vertex_groups

	for p_system in particle_systems:
			
		if(p_system.settings["density_settings"]["enabled"] == False):
			continue

		if p_system.vertex_group_density:
			vgroup = vgroups[p_system.vertex_group_density]
			weight_average = Globals.vgroups_average_weight_cache[vgroup.index]["weight_average"]
		else:
			weight_average = 1

		p_system_density = p_system.settings["density_settings"]["density"]
		new_particles_count = round(weight_average * p_system_density * mesh_area)

		if p_system.settings.count != new_particles_count:
			
			if p_system.settings.count == 0 or abs(p_system.settings.count - new_particles_count) / p_system.settings.count > (bpy.context.user_preferences.addons[__name__].preferences.density_tolerance / 100):
				p_system.settings.count = new_particles_count
				print(p_system.name + " count updated")

	print("All particle systems checked in " + str(time.time() - time_start_updating))

@persistent
def on_scene_update(scene):

	obj = scene.objects.active

	#TODO add obj.type in ['MESH']?

	if obj is None or len(obj.particle_systems) == 0:
		return

	# if Globals.use_update_interval and (time.time() - Globals.updated_timestamp) < Globals.update_interval and Globals.last_obj == obj:
	# 	return

	
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
		obj.data.is_updated or
		Globals.vgroups_average_weight_cache is None or
		obj	!= Globals.last_obj or
		len(obj.vertex_groups) != len(Globals.vgroups_average_weight_cache) or
		len(obj.particle_systems) != Globals.last_p_systems_count or
		(obj.particle_systems.active == Globals.last_p_system and obj.particle_systems.active.vertex_group_density != Globals.last_density_group) or
		bpy.context.mode != Globals.last_mode):

		updates_needed = True

	else:
		for vgroup in obj.vertex_groups:
			if Globals.vgroups_average_weight_cache[vgroup.index]["vgroup_name"] != vgroup.name:
				updates_needed = True
				break
			
	
	if updates_needed:
		update_vgroups_average_weight_cache()
		update_particles_count(obj)
		Globals.updated_timestamp = time.time()
	
	Globals.last_density_group = obj.particle_systems.active.vertex_group_density
	Globals.last_p_system = obj.particle_systems.active
	Globals.last_p_systems_count = len(obj.particle_systems)
	Globals.last_obj = obj
	Globals.last_mode = bpy.context.mode

def register():
	bpy.utils.register_module(__name__)
	bpy.types.Scene.optionspanel_properties = PointerProperty(type=OptionsPanel_Properties)
	bpy.app.handlers.scene_update_pre.append(on_scene_update)


def unregister():
	bpy.app.handlers.scene_update_pre.remove(on_scene_update)
	del bpy.types.Scene.optionspanel_properties
	bpy.utils.unregister_module(__name__)
	

if __name__ == "__main__":
	register()