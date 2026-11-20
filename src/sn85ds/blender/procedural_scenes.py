"""Procedural 3D scenes rendered with Blender (run INSIDE Blender: blender -b --python <this> -- <json>).

Everything is generated from built-in primitives, modifiers and procedural textures in this
file; no third-party models, textures or HDRIs are used, so the renders are original work of
this project (licensed CC0 by the project). Output: 8-bit sRGB PNG frames ('Standard' view
transform), Cycles on the GPU (OptiX), seeded and deterministic in content.

Scenes: gears (mechanical, rotating), signs (architecture, signage text, thin edges),
ocean (reflective fluid surface), city (fast camera flight); Phase B adds forest (hair grass,
instanced leaves), terrain (mountain flyover), machine (crank/pistons, fans, conveyor),
clock (dial, ticks, numerals, gear train), interior (corridor/rooms with posters, shelves, tiles),
tunnel (fast flight past lights and numbered panels), chrome (mirror/glass objects),
particles (sparks / snow / confetti simulations), toon (EEVEE cel shading with inverted-hull
outlines). Fonts: DejaVu / Liberation / Ubuntu system fonts (licences do not restrict output).
"""

import json
import math
import random
import sys
import time

import bpy
import bmesh
from mathutils import Vector


def args() -> dict:
    return json.loads(sys.argv[sys.argv.index("--") + 1])


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_render(a: dict):
    s = bpy.context.scene
    if a.get("engine") == "eevee":
        s.render.engine = "BLENDER_EEVEE_NEXT"
        s.eevee.taa_render_samples = int(a.get("samples", 32))
        s.eevee.use_raytracing = True
        s.eevee.use_shadows = True
        s.render.use_motion_blur = True
        s.render.motion_blur_shutter = float(a.get("shutter", 0.5))
        _common_output(s, a)
        return
    s.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "OPTIX"
    s.cycles.device = "GPU"
    s.cycles.samples = int(a.get("samples", 48))
    s.cycles.use_adaptive_sampling = True
    s.cycles.adaptive_threshold = float(a.get("adaptive_threshold", 0.03))
    s.cycles.use_denoising = True
    s.cycles.denoiser = "OPTIX"
    s.cycles.seed = int(a["seed"]) % 100000
    s.render.use_motion_blur = True
    s.render.motion_blur_shutter = float(a.get("shutter", 0.5))
    s.cycles.max_bounces = int(a.get("bounces", 4))
    s.cycles.transparent_max_bounces = 8
    _common_output(s, a)


def _common_output(s, a: dict):
    s.render.resolution_x, s.render.resolution_y = a["width"], a["height"]
    s.render.resolution_percentage = 100
    s.render.use_overwrite = False  # resume: frames already on disk are skipped (driver removes the newest partial one)
    s.render.fps, s.render.fps_base = a["fps_num"], a["fps_den"]
    s.frame_start, s.frame_end = 1, a["frames"]
    s.render.image_settings.file_format = "PNG"
    s.render.image_settings.color_mode = "RGB"
    s.render.image_settings.color_depth = "8"
    s.view_settings.view_transform = a.get("view", "AgX")
    s.view_settings.look = "None"
    s.view_settings.exposure = float(a.get("exposure", -0.5))
    s.render.use_persistent_data = True
    s.render.filepath = a["out_dir"].rstrip("/") + "/frame_"


def mat(name, color, metallic=0.0, rough=0.5, emission=None, strength=0.0, transmission=0.0, ior=1.45):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    b.inputs["IOR"].default_value = ior
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
    if emission is not None:
        b.inputs["Emission Color"].default_value = (*emission, 1.0)
        b.inputs["Emission Strength"].default_value = strength
    return m


def textured_mat(name, kind, scale, c1, c2, rough=0.6, bump=0.2, metallic=0.0, vertical=False):
    """Principled material driven by a procedural texture (noise / voronoi / brick / checker / wave).

    ``vertical``: map world (x + y, z) instead of (x, y), so 2-D patterns (bricks, checkers)
    lie on axis-aligned walls instead of collapsing into streaks."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tex = {"noise": "ShaderNodeTexNoise", "voronoi": "ShaderNodeTexVoronoi", "brick": "ShaderNodeTexBrick",
           "checker": "ShaderNodeTexChecker", "wave": "ShaderNodeTexWave"}[kind]
    t = nt.nodes.new(tex)
    geo = nt.nodes.new("ShaderNodeNewGeometry")  # world-space position: textures stay isotropic in metres
    if vertical:
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        add = nt.nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        comb = nt.nodes.new("ShaderNodeCombineXYZ")
        nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
        nt.links.new(sep.outputs["X"], add.inputs[0])
        nt.links.new(sep.outputs["Y"], add.inputs[1])
        nt.links.new(add.outputs["Value"], comb.inputs["X"])
        nt.links.new(sep.outputs["Z"], comb.inputs["Y"])
        nt.links.new(comb.outputs["Vector"], t.inputs["Vector"])
    else:
        nt.links.new(geo.outputs["Position"], t.inputs["Vector"])
    t.inputs["Scale"].default_value = scale
    if kind == "noise":
        t.inputs["Detail"].default_value = 12.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*c1, 1)
    ramp.color_ramp.elements[1].color = (*c2, 1)
    out_socket = t.outputs["Fac"] if "Fac" in t.outputs else t.outputs[0]
    if kind in ("brick", "checker"):
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        if kind == "brick":
            t.inputs["Color1"].default_value = (*c1, 1)
            t.inputs["Color2"].default_value = (*c2, 1)
            t.inputs["Mortar"].default_value = (0.75, 0.73, 0.70, 1)
        else:
            t.inputs["Color1"].default_value = (*c1, 1)
            t.inputs["Color2"].default_value = (*c2, 1)
    else:
        nt.links.new(out_socket, ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = bump
    nt.links.new(out_socket, bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metallic
    return m


def sky(strength=0.25, sun_elev=0.6, sun_rot=0.8):
    w = bpy.data.worlds.new("sky")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    st = nt.nodes.new("ShaderNodeTexSky")
    st.sky_type = "NISHITA"
    st.sun_elevation = sun_elev
    st.sun_rotation = sun_rot
    bg = nt.nodes["Background"]
    bg.inputs["Strength"].default_value = strength
    nt.links.new(st.outputs["Color"], bg.inputs["Color"])


def camera(loc, look_at, lens=35.0):
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    cam.data.lens = lens
    d = Vector(look_at) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def key_cam(cam, frame, loc, look_at):
    cam.location = loc
    cam.rotation_euler = (Vector(look_at) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam.keyframe_insert("location", frame=frame)
    cam.keyframe_insert("rotation_euler", frame=frame)


def linear_fcurves(obj):
    if obj.animation_data and obj.animation_data.action:
        for fc in obj.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


def gear_mesh(name, teeth, r_out, r_in, width, hole=0.2):
    bm = bmesh.new()
    pts = []
    for i in range(teeth * 4):
        ang = 2 * math.pi * i / (teeth * 4)
        r = r_out if (i % 4) in (1, 2) else r_in
        pts.append((r * math.cos(ang), r * math.sin(ang)))
    top = [bm.verts.new((x, y, width / 2)) for x, y in pts]
    bot = [bm.verts.new((x, y, -width / 2)) for x, y in pts]
    bm.faces.new(top)
    bm.faces.new(list(reversed(bot)))
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        bm.faces.new((top[i], bot[i], bot[j], top[j]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    bev = ob.modifiers.new("bevel", "BEVEL")
    bev.width = 0.01
    bev.segments = 2
    return ob


# ---------------------------------------------------------------------------------------------

def scene_gears(a, rng):
    sky(0.12, 0.4, rng.uniform(0, 6.28))
    metals = [mat("steel", (0.8, 0.8, 0.82), 1.0, 0.25), mat("brass", (0.95, 0.7, 0.35), 1.0, 0.3),
              mat("copper", (0.95, 0.55, 0.4), 1.0, 0.35), mat("dark", (0.15, 0.15, 0.17), 1.0, 0.45)]
    floor = textured_mat("plate", "voronoi", 3.0, (0.08, 0.08, 0.09), (0.22, 0.22, 0.24), rough=0.45, bump=0.4, metallic=0.8)
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, -0.6))
    bpy.context.object.data.materials.append(floor)
    n = rng.randint(7, 12)
    frames = a["frames"]
    for i in range(n):
        teeth = rng.choice([12, 16, 20, 24, 32, 40])
        r = teeth * 0.05
        g = gear_mesh(f"g{i}", teeth, r, r * 0.86, rng.uniform(0.15, 0.35))
        g.location = (rng.uniform(-4, 4), rng.uniform(-2.5, 2.5), rng.uniform(-0.3, 0.6))
        g.data.materials.append(rng.choice(metals))
        speed = rng.choice([-1, 1]) * rng.uniform(0.3, 2.5) / teeth * 12  # rad/s
        g.rotation_euler = (rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), 0)
        g.keyframe_insert("rotation_euler", frame=1)
        g.rotation_euler[2] += speed * frames / (a["fps_num"] / a["fps_den"])
        g.keyframe_insert("rotation_euler", frame=frames)
        linear_fcurves(g)
        ax = bpy.data.objects.new(f"axle{i}", None)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=1.2, location=g.location)
        bpy.context.object.data.materials.append(metals[0])
    bpy.ops.object.light_add(type="AREA", location=(3, -3, 5))
    bpy.context.object.data.energy = 250
    bpy.context.object.data.size = 3
    cam = camera((0, -7, 4), (0, 0, 0), lens=rng.choice([35, 50]))
    r0, r1 = rng.uniform(-0.6, 0.0), rng.uniform(0.2, 0.8)
    for f, rr in ((1, r0), (frames, r1)):
        key_cam(cam, f, (7 * math.sin(rr), -7 * math.cos(rr), 4 - rr), (0, 0, 0))
    linear_fcurves(cam)


def scene_signs(a, rng):
    sky(0.2, rng.uniform(0.2, 0.9), rng.uniform(0, 6.28))
    wall = textured_mat("bricks", "brick", rng.uniform(1.6, 2.6), (0.45, 0.2, 0.14), (0.32, 0.15, 0.11), rough=0.8, bump=0.5, vertical=True)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 2, 2), rotation=(math.pi / 2, 0, 0))
    w = bpy.context.object
    w.scale = (60, 6, 1)
    w.data.materials.append(wall)
    ground = textured_mat("asphalt", "noise", 6, (0.05, 0.05, 0.06), (0.14, 0.14, 0.15), rough=0.9, bump=0.6)
    bpy.ops.mesh.primitive_plane_add(size=80, location=(0, 0, -1))
    bpy.context.object.data.materials.append(ground)
    words = ["PLATFORM 4", "EXIT", "NO PARKING 8-18", "CAFE", "OPEN 24H", "Track 12 -> 15", "TICKETS", "A-17", "PHARMACY",
             "SALE -30%", "Gate B 22", "Bus 108 / 74", "1 2 3 4 5 6 7 8 9 0", "WAY OUT", "Information", "Level -2", "ROOM 314"]
    colors = [(0.9, 0.9, 0.9), (0.05, 0.25, 0.6), (0.7, 0.05, 0.05), (0.95, 0.75, 0.05), (0.05, 0.4, 0.15), (0.02, 0.02, 0.02)]
    x = -28.0
    while x < 28:
        wpx = rng.uniform(1.5, 4.0)
        hpx = rng.uniform(0.5, 1.4)
        bg_col, fg_col = rng.sample(colors, 2)
        z = rng.uniform(0.2, 3.5)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x + wpx / 2, 1.95, z))
        panel = bpy.context.object
        panel.scale = (wpx, 0.04, hpx)
        panel.data.materials.append(mat(f"p{x}", bg_col, 0.0, 0.4))
        bpy.ops.object.text_add(location=(x + 0.08, 1.9, z - hpx * 0.25), rotation=(math.pi / 2, 0, 0))
        t = bpy.context.object
        t.data.body = rng.choice(words)
        t.data.size = hpx * rng.uniform(0.35, 0.55)
        t.data.extrude = 0.005
        t.data.materials.append(mat(f"t{x}", fg_col, 0.0, 0.3, emission=fg_col if rng.random() < 0.3 else None, strength=2.0))
        # thin frame rods
        for dz in (-hpx / 2 - 0.03, hpx / 2 + 0.03):
            bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=wpx + 0.1, location=(x + wpx / 2, 1.9, z + dz), rotation=(0, math.pi / 2, 0))
            bpy.context.object.data.materials.append(mat("rod", (0.7, 0.7, 0.72), 1.0, 0.3))
        x += wpx + rng.uniform(0.3, 1.5)
    cam = camera((-6, -6, 1.8), (-6, 2, 1.8), lens=rng.choice([28, 35, 50]))
    v = rng.uniform(1.0, 3.0) * rng.choice([-1, 1])  # m/s sideways
    dur = a["frames"] / (a["fps_num"] / a["fps_den"])
    x0 = -v * dur / 2
    key_cam(cam, 1, (x0, -6, 1.8), (x0 + 0.5, 2, 1.8))
    key_cam(cam, a["frames"], (x0 + v * dur, -6, 1.8), (x0 + v * dur + 0.5, 2, 1.8))
    linear_fcurves(cam)
    bpy.ops.object.light_add(type="SUN", rotation=(0.8, 0.1, 0.4))
    bpy.context.object.data.energy = 1.5


def scene_ocean(a, rng):
    sky(0.25, rng.uniform(0.05, 0.5), rng.uniform(0, 6.28))
    bpy.ops.mesh.primitive_plane_add(size=1)
    o = bpy.context.object
    oc = o.modifiers.new("ocean", "OCEAN")
    oc.size = rng.uniform(1.0, 2.0)
    oc.spatial_size = 50
    oc.resolution = 18
    oc.wave_scale = rng.uniform(0.6, 1.6)
    oc.choppiness = rng.uniform(0.6, 1.4)
    oc.random_seed = rng.randint(0, 9999)
    oc.time = 1.0
    oc.keyframe_insert("time", frame=1)
    oc.time = 1.0 + a["frames"] / (a["fps_num"] / a["fps_den"])
    oc.keyframe_insert("time", frame=a["frames"])
    linear_fcurves(o)
    water = mat("water", (0.02, 0.08, 0.1), 0.0, 0.05, transmission=0.9, ior=1.33)
    o.data.materials.append(water)
    bpy.ops.object.shade_smooth()
    for i in range(rng.randint(3, 7)):  # floating chrome buoys
        bpy.ops.mesh.primitive_uv_sphere_add(radius=rng.uniform(0.3, 0.9), location=(rng.uniform(-10, 10), rng.uniform(4, 25), 0.2))
        bpy.ops.object.shade_smooth()
        bpy.context.object.data.materials.append(mat(f"b{i}", (0.9, 0.9, 0.92), 1.0, 0.08))
    cam = camera((0, -6, 2.0), (0, 20, 0.5), lens=rng.choice([24, 35]))
    key_cam(cam, 1, (0, -6, 2.0), (0, 20, 0.5))
    key_cam(cam, a["frames"], (rng.uniform(-2, 2), -2, rng.uniform(1.4, 2.6)), (0, 24, 0.5))
    linear_fcurves(cam)


def scene_city(a, rng):
    sky(0.18, rng.uniform(0.05, 0.35), rng.uniform(0, 6.28))
    facade = textured_mat("windows", "brick", 0.9, (0.25, 0.26, 0.3), (0.55, 0.52, 0.38), rough=0.3, bump=0.1, metallic=0.2, vertical=True)
    roof = mat("roof", (0.2, 0.2, 0.22), 0.0, 0.7)
    road = textured_mat("road", "noise", 4, (0.04, 0.04, 0.05), (0.12, 0.12, 0.13), rough=0.9, bump=0.3)
    bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 0, 0))
    bpy.context.object.data.materials.append(road)
    for ix in range(-10, 11):
        for iy in range(-3, 60):
            if ix == 0 or rng.random() < 0.08:
                continue  # the avenue the camera flies along
            h = rng.uniform(3, 28) * (1.6 if abs(ix) < 3 else 1.0)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(ix * 6, iy * 6, h / 2))
            b = bpy.context.object
            b.scale = (rng.uniform(3, 5), rng.uniform(3, 5), h)
            b.data.materials.append(facade)
            b.data.materials.append(roof)
    cam = camera((0, -20, 8), (0, 40, 6), lens=rng.choice([20, 24, 28]))
    speed = rng.uniform(25, 45)  # m/s: fast camera
    dur = a["frames"] / (a["fps_num"] / a["fps_den"])
    key_cam(cam, 1, (0, -20, rng.uniform(5, 12)), (rng.uniform(-3, 3), 40, 6))
    key_cam(cam, a["frames"], (rng.uniform(-1.5, 1.5), -20 + speed * dur, rng.uniform(5, 14)), (rng.uniform(-3, 3), 40 + speed * dur, 6))
    linear_fcurves(cam)


# ---------------------------------------------------------------------------------- Phase B

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]


def font(rng):
    import os
    path = rng.choice([f for f in FONTS if os.path.exists(f)] or [None])
    return bpy.data.fonts.load(path, check_existing=True) if path else None


def text_obj(body, loc, rot, size, material, rng, extrude=0.004, align="LEFT"):
    bpy.ops.object.text_add(location=loc, rotation=rot)
    t = bpy.context.object
    t.data.body = body
    t.data.size = size
    t.data.extrude = extrude
    t.data.align_x = align
    f = font(rng)
    if f:
        t.data.font = f
    t.data.materials.append(material)
    return t


def dur_s(a):
    return a["frames"] / (a["fps_num"] / a["fps_den"])


def per_frame(obj, a, fn, path="location"):
    """Key a property on every frame from fn(t_seconds) (deterministic, no drivers needed)."""
    fps = a["fps_num"] / a["fps_den"]
    for f in range(1, a["frames"] + 1):
        setattr(obj, path, fn((f - 1) / fps))
        obj.keyframe_insert(path, frame=f)


def terrain_mat(snow_line=4.0, palette=None):
    m = bpy.data.materials.new("terrain")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 3.0
    nz.inputs["Detail"].default_value = 14.0
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "MULTIPLY_ADD"
    add.inputs[1].default_value = 1.5
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    pal = palette or [(0.0, (0.05, 0.12, 0.03)), (0.45, (0.12, 0.2, 0.05)), (0.65, (0.25, 0.22, 0.18)), (0.85, (0.85, 0.87, 0.9))]
    el = ramp.color_ramp.elements
    el[0].position, el[0].color = pal[0][0], (*pal[0][1], 1)
    el[1].position, el[1].color = pal[-1][0], (*pal[-1][1], 1)
    for pos, col in pal[1:-1]:
        e = el.new(pos)
        e.color = (*col, 1)
    mapr = nt.nodes.new("ShaderNodeMapRange")
    mapr.inputs["From Min"].default_value = -1.0
    mapr.inputs["From Max"].default_value = snow_line
    nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], add.inputs[0])
    nt.links.new(sep.outputs["Z"], add.inputs[2])
    nt.links.new(add.outputs["Value"], mapr.inputs["Value"])
    nt.links.new(mapr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    bp = nt.nodes.new("ShaderNodeBump")
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.inputs["Scale"].default_value = 40.0
    nt.links.new(vor.outputs["Distance"], bp.inputs["Height"])
    bp.inputs["Strength"].default_value = 0.4
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Roughness"].default_value = 0.85
    return m


def displaced_grid(size, subdiv, strength, noise_scale, seed, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=subdiv, y_subdivisions=subdiv, size=size, location=location)
    g = bpy.context.object
    tex = bpy.data.textures.new(f"clouds{seed}", "CLOUDS")
    tex.noise_scale = noise_scale
    tex.noise_depth = 6
    tex.noise_basis = "BLENDER_ORIGINAL"
    d = g.modifiers.new("disp", "DISPLACE")
    d.texture = tex
    d.strength = strength
    d.texture_coords = "GLOBAL"
    tex.intensity = 1.0
    # seed the pattern by offsetting the texture space
    emp = bpy.data.objects.new(f"texspace{seed}", None)
    bpy.context.collection.objects.link(emp)
    r = random.Random(seed)
    emp.location = (r.uniform(-500, 500), r.uniform(-500, 500), 0)
    d.texture_coords = "OBJECT"
    d.texture_coords_object = emp
    bpy.ops.object.shade_smooth()
    return g, emp


def add_grass(obj, rng, count, length, colors):
    m = mat("grass", colors[0], 0.0, 0.6)
    obj.data.materials.append(m)
    ps_mod = obj.modifiers.new("grass", "PARTICLE_SYSTEM")
    ps = ps_mod.particle_system
    ps.seed = rng.randint(0, 99999)
    st = ps.settings
    st.type = "HAIR"
    st.count = count
    st.hair_length = length
    st.use_advanced_hair = True
    st.child_type = "INTERPOLATED"
    st.child_percent = 10
    st.rendered_child_count = 5
    st.root_radius = 1.0
    st.tip_radius = 0.0
    st.radius_scale = 0.006
    st.factor_random = 0.6
    st.brownian_factor = 0.04
    st.material = len(obj.data.materials)
    return ps


def tree(rng, loc, height, leaf_obj, leaf_mat, bark):
    bpy.ops.mesh.primitive_cone_add(vertices=10, radius1=height * 0.045, radius2=height * 0.02, depth=height, location=(loc[0], loc[1], loc[2] + height / 2))
    trunk = bpy.context.object
    trunk.data.materials.append(bark)
    r = height * rng.uniform(0.22, 0.35)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=r, location=(loc[0], loc[1], loc[2] + height * rng.uniform(0.75, 0.9)))
    can = bpy.context.object
    can.scale = (1.0, 1.0, rng.uniform(1.0, 1.6))
    can.data.materials.append(leaf_mat)
    ps = can.modifiers.new("leaves", "PARTICLE_SYSTEM").particle_system
    ps.seed = rng.randint(0, 99999)
    st = ps.settings
    st.count = int(600 * (height / 6) ** 2)
    st.frame_start = st.frame_end = 1
    st.lifetime = 100000
    st.physics_type = "NO"
    st.emit_from = "FACE"
    st.render_type = "OBJECT"
    st.instance_object = leaf_obj
    st.particle_size = height * 0.03
    st.size_random = 0.5
    st.use_rotations = True
    st.rotation_mode = "NOR"
    st.phase_factor_random = 2.0
    st.rotation_factor_random = 0.6
    can.show_instancer_for_render = True
    return can


def add_boxes(name, boxes, materials):
    """Many boxes in ONE mesh object (fast: bpy.ops per box is O(n^2) in scene updates).
    boxes: (cx, cy, cz, sx, sy, sz, rot_z, material_index)."""
    from mathutils import Matrix
    bm = bmesh.new()
    for cx, cy, cz, sx, sy, sz, rz, mi in boxes:
        r = bmesh.ops.create_cube(bm, size=1.0)
        m = Matrix.Translation((cx, cy, cz)) @ Matrix.Rotation(rz, 4, "Z") @ Matrix.Diagonal((sx, sy, sz, 1.0))
        bmesh.ops.transform(bm, matrix=m, verts=r["verts"])
        for f in {f for v in r["verts"] for f in v.link_faces}:
            f.material_index = mi
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in materials:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


def scene_forest(a, rng):
    P = a.get("params", {})
    sky(rng.uniform(0.25, 0.45), rng.uniform(0.15, 0.9), rng.uniform(0, 6.28))
    season = P.get("season", rng.choice(["summer", "summer", "autumn", "spring"]))
    leaf_cols = {"summer": [(0.05, 0.22, 0.03), (0.12, 0.35, 0.06)], "autumn": [(0.6, 0.25, 0.03), (0.75, 0.5, 0.05)],
                 "spring": [(0.25, 0.5, 0.1), (0.6, 0.75, 0.3)]}[season]
    ground, _ = displaced_grid(80, 160, rng.uniform(0.6, 1.6), rng.uniform(4, 9), rng.randint(0, 9999))
    ground.data.materials.append(textured_mat("soil", "noise", 3.0, (0.08, 0.06, 0.04), (0.2, 0.16, 0.1), rough=0.95, bump=0.6))
    add_grass(ground, rng, int(P.get("grass", rng.randint(25000, 45000))), rng.uniform(0.12, 0.25),
              [(leaf_cols[0][0] * 0.8, leaf_cols[0][1] * 1.2, leaf_cols[0][2])])
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, -50))
    leaf = bpy.context.object
    leaf.scale = (1.0, 0.55, 1.0)
    leaf_mat = textured_mat("leaf", "voronoi", 30.0, leaf_cols[0], leaf_cols[1], rough=0.5, bump=0.3)
    leaf.data.materials.append(leaf_mat)
    leaf.hide_render = False
    bark = textured_mat("bark", "wave", 8.0, (0.08, 0.05, 0.03), (0.2, 0.15, 0.1), rough=0.9, bump=0.8, vertical=True)
    n = int(P.get("trees", rng.randint(25, 60)))
    for i in range(n):
        x, y = rng.uniform(-30, 30), rng.uniform(-10, 35)
        if abs(x) < 2.0 and y < 25:
            continue  # keep the camera path clear
        tree(rng, (x, y, 0.3), rng.uniform(4, 11), leaf, leaf_mat, bark)
    for i in range(rng.randint(10, 30)):  # rocks
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=rng.uniform(0.2, 0.9), location=(rng.uniform(-20, 20), rng.uniform(-5, 30), 0.3))
        bpy.context.object.data.materials.append(textured_mat(f"rock{i}", "voronoi", 6, (0.25, 0.25, 0.24), (0.45, 0.44, 0.42), rough=0.9, bump=0.7))
    h = rng.uniform(1.2, 2.5)
    cam = camera((0, -6, h), (0, 20, h), lens=rng.choice([24, 28, 35, 50]))
    v = P.get("speed", rng.uniform(0.8, 2.5))
    pan = rng.uniform(-0.5, 0.5)
    key_cam(cam, 1, (0, -6, h), (pan * 6, 20, h * 0.8))
    key_cam(cam, a["frames"], (rng.uniform(-0.8, 0.8), -6 + v * dur_s(a), h + rng.uniform(-0.3, 0.6)), (-pan * 6, 20 + v * dur_s(a), h * 0.8))
    linear_fcurves(cam)


def scene_terrain(a, rng):
    P = a.get("params", {})
    sky(rng.uniform(0.2, 0.4), rng.uniform(0.08, 0.7), rng.uniform(0, 6.28))
    relief = rng.uniform(70, 140)
    g, _ = displaced_grid(600, 420, relief, rng.uniform(35, 80), rng.randint(0, 9999))
    g.data.materials.append(terrain_mat(snow_line=relief * rng.uniform(0.25, 0.45)))
    if rng.random() < 0.5:
        bpy.ops.mesh.primitive_plane_add(size=600, location=(0, 0, -relief * rng.uniform(0.3, 0.42)))
        bpy.context.object.data.materials.append(mat("lake", (0.02, 0.06, 0.08), 0.0, 0.04, transmission=0.0))
    speed = P.get("speed", rng.uniform(15, 35))
    alt = rng.uniform(0.35, 0.6) * relief
    head = rng.uniform(0, 6.28)
    dx, dy = math.cos(head), math.sin(head)
    cam = camera((0, 0, alt), (dx * 100, dy * 100, alt * 0.3), lens=rng.choice([20, 24, 35]))
    d = speed * dur_s(a)
    sx, sy = -dx * d / 2, -dy * d / 2
    key_cam(cam, 1, (sx, sy, alt), (sx + dx * 100, sy + dy * 100, alt * 0.3))
    key_cam(cam, a["frames"], (sx + dx * d, sy + dy * d, alt + rng.uniform(-10, 10)), (sx + dx * (d + 100), sy + dy * (d + 100), alt * 0.25))
    linear_fcurves(cam)


def scene_machine(a, rng):
    sky(0.08, 0.3, rng.uniform(0, 6.28))
    paint = [mat("red", (0.6, 0.05, 0.03), 0.0, 0.35), mat("yellow", (0.85, 0.6, 0.05), 0.0, 0.4), mat("blue", (0.05, 0.15, 0.5), 0.0, 0.3),
             mat("green", (0.05, 0.3, 0.12), 0.0, 0.4)]
    steel = mat("steel", (0.75, 0.76, 0.78), 1.0, 0.2)
    dark = mat("dark", (0.1, 0.1, 0.11), 1.0, 0.5)
    rubber = mat("rubber", (0.02, 0.02, 0.02), 0.0, 0.8)
    floor = textured_mat("grating", "checker", rng.uniform(8, 16), (0.05, 0.05, 0.05), (0.3, 0.3, 0.32), rough=0.5, bump=0.5, metallic=0.9)
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, -1))
    bpy.context.object.data.materials.append(floor)
    fps = a["fps_num"] / a["fps_den"]
    # crankshaft + pistons
    n_cyl = rng.randint(3, 6)
    rpm = rng.uniform(60, 240)
    w = 2 * math.pi * rpm / 60
    r_c, l_rod = 0.35, 1.2
    x0 = -n_cyl * 0.6
    for i in range(n_cyl):
        ph = i * 2 * math.pi / n_cyl
        x = x0 + i * 1.2
        bpy.ops.mesh.primitive_cylinder_add(radius=0.38, depth=0.9, location=(x, 0, 0))
        piston = bpy.context.object
        piston.data.materials.append(steel)
        web = gear_mesh(f"web{i}", rng.choice([12, 16, 20]), 0.5, 0.43, 0.15)
        web.location = (x, 0, 0)
        web.data.materials.append(rng.choice(paint))
        for f in range(1, a["frames"] + 1):
            th = w * (f - 1) / fps + ph
            z = r_c * math.cos(th) + math.sqrt(l_rod ** 2 - (r_c * math.sin(th)) ** 2) + 0.5
            piston.location = (x, 0, z)
            piston.keyframe_insert("location", frame=f)
            web.rotation_euler = (math.pi / 2, th, 0)
            web.keyframe_insert("rotation_euler", frame=f)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.42, depth=2.4, location=(x, 0, 2.2))  # cylinder liner (open view)
        liner = bpy.context.object
        liner.scale = (1, 1, 1)
        liner.data.materials.append(dark)
        liner.hide_render = True  # open view: pistons stay visible
    # fans
    for k in range(rng.randint(1, 3)):
        hub = (rng.uniform(-4, 4), rng.uniform(2, 5), rng.uniform(1.5, 3.5))
        blades = rng.randint(3, 9)
        bpy.ops.object.empty_add(location=hub)
        piv = bpy.context.object
        for b in range(blades):
            bpy.ops.mesh.primitive_cube_add(size=1, location=hub)
            bl = bpy.context.object
            bl.scale = (0.08, 1.2, 0.35)
            bl.rotation_euler = (0.35, 0, 0)
            bl.location = (hub[0], hub[1], hub[2])
            bl.data.materials.append(rng.choice([steel] + paint))
            bl.parent = piv
            bl.matrix_parent_inverse = piv.matrix_world.inverted()
            bl.rotation_euler = (0, b * 2 * math.pi / blades, 0)
            bl.location = (hub[0] + 0.7 * math.sin(b * 2 * math.pi / blades), hub[1], hub[2] + 0.7 * math.cos(b * 2 * math.pi / blades))
        spd = rng.uniform(1.0, 6.0)
        piv.keyframe_insert("rotation_euler", frame=1)
        piv.rotation_euler[1] += spd * 2 * math.pi * dur_s(a)
        piv.keyframe_insert("rotation_euler", frame=a["frames"])
        linear_fcurves(piv)
    # conveyor with rollers and boxes
    y_c = -2.5
    for i in range(24):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=1.6, location=(-7 + i * 0.6, y_c, -0.4), rotation=(math.pi / 2, 0, 0))
        ro = bpy.context.object
        ro.data.materials.append(steel)
        ro.keyframe_insert("rotation_euler", frame=1)
        ro.rotation_euler[1] += 1.5 / 0.12 * dur_s(a)
        ro.keyframe_insert("rotation_euler", frame=a["frames"])
        linear_fcurves(ro)
    for i in range(rng.randint(5, 10)):
        bpy.ops.mesh.primitive_cube_add(size=0.5, location=(-8 + i * 1.7, y_c, -0.03))
        bx = bpy.context.object
        bx.data.materials.append(textured_mat(f"box{i}", "noise", 12, (0.5, 0.35, 0.18), (0.65, 0.48, 0.28), rough=0.9, bump=0.2))
        bx.keyframe_insert("location", frame=1)
        bx.location.x += 1.5 * dur_s(a)
        bx.keyframe_insert("location", frame=a["frames"])
        linear_fcurves(bx)
    bpy.ops.object.light_add(type="AREA", location=(2, -4, 6))
    bpy.context.object.data.energy = 400
    bpy.context.object.data.size = 4
    cam = camera((0, -9, 3.5), (0, 0, 1), lens=rng.choice([28, 35, 50]))
    r0, r1 = rng.uniform(-0.5, 0.0), rng.uniform(0.1, 0.6)
    key_cam(cam, 1, (9 * math.sin(r0), -9 * math.cos(r0), 3.5), (0, 0, 1))
    key_cam(cam, a["frames"], (8 * math.sin(r1), -8 * math.cos(r1), 2.8), (0, 0, 1.2))
    linear_fcurves(cam)


def scene_clock(a, rng):
    sky(0.1, 0.4, rng.uniform(0, 6.28))
    face_col = rng.choice([(0.92, 0.9, 0.84), (0.05, 0.05, 0.06), (0.1, 0.18, 0.35)])
    ink = (0.03, 0.03, 0.03) if face_col[0] > 0.5 else (0.95, 0.92, 0.8)
    ink_m = mat("ink", ink, 0.0, 0.4)
    brass = mat("brass", (0.95, 0.72, 0.38), 1.0, 0.25)
    steel = mat("steel", (0.8, 0.8, 0.82), 1.0, 0.2)
    bpy.ops.mesh.primitive_cylinder_add(radius=3.0, depth=0.1, location=(0, 0, 0), rotation=(math.pi / 2, 0, 0))
    bpy.context.object.data.materials.append(textured_mat("face", "noise", 20, face_col, tuple(c * 0.92 for c in face_col), rough=0.6, bump=0.05))
    bpy.ops.mesh.primitive_torus_add(major_radius=3.05, minor_radius=0.12, location=(0, -0.05, 0), rotation=(math.pi / 2, 0, 0))
    bpy.context.object.data.materials.append(brass)
    for i in range(60):
        ang = i * 2 * math.pi / 60
        long = i % 5 == 0
        bpy.ops.mesh.primitive_cube_add(size=1, location=(2.75 * math.sin(ang), -0.07, 2.75 * math.cos(ang)), rotation=(0, ang, 0))
        t = bpy.context.object
        t.scale = (0.025 if not long else 0.06, 0.01, 0.18 if not long else 0.32)
        t.data.materials.append(ink_m)
    roman = ["XII", "I", "II", "III", "IIII", "V", "VI", "VII", "VIII", "IX", "X", "XI"]
    use_roman = rng.random() < 0.5
    for i in range(12):
        ang = i * 2 * math.pi / 12
        label = roman[i] if use_roman else str(12 if i == 0 else i)
        t = text_obj(label, (2.25 * math.sin(ang), -0.08, 2.25 * math.cos(ang) - 0.15), (math.pi / 2, 0, 0), 0.42, ink_m, rng, align="CENTER")
    hands = [(1.6, 0.09, 1 / 43200.0), (2.4, 0.06, 1 / 3600.0), (2.6, 0.02, rng.choice([1 / 60.0, 1.0 / 6]))]  # rev/s; fast "second" hand
    for k, (ln, wd, rev) in enumerate(hands):
        bpy.ops.object.empty_add(location=(0, -0.12 - 0.02 * k, 0))
        piv = bpy.context.object
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.12 - 0.02 * k, ln / 2 - 0.2))
        h = bpy.context.object
        h.scale = (wd, 0.01, ln)
        h.data.materials.append(ink_m if k < 2 else mat("red", (0.7, 0.05, 0.03), 0.0, 0.3))
        h.parent = piv
        piv.rotation_euler = (0, rng.uniform(0, 6.28), 0)
        piv.keyframe_insert("rotation_euler", frame=1)
        piv.rotation_euler[1] += rev * 2 * math.pi * dur_s(a) * (1 if k == 2 else 40)  # minute/hour hands sped up visibly
        piv.keyframe_insert("rotation_euler", frame=a["frames"])
        linear_fcurves(piv)
    for i in range(rng.randint(4, 8)):  # gear train behind a cut-away (right side)
        teeth = rng.choice([16, 20, 24, 30])
        g = gear_mesh(f"cg{i}", teeth, teeth * 0.04, teeth * 0.034, 0.12)
        g.rotation_euler = (math.pi / 2, 0, 0)
        g.location = (rng.uniform(3.3, 6.5), 0.3, rng.uniform(-2.5, 2.5))
        g.data.materials.append(rng.choice([brass, steel]))
        g.keyframe_insert("rotation_euler", frame=1)
        g.rotation_euler[1] += rng.choice([-1, 1]) * rng.uniform(0.5, 3) * dur_s(a)
        g.keyframe_insert("rotation_euler", frame=a["frames"])
        linear_fcurves(g)
    bpy.ops.object.light_add(type="AREA", location=(-3, -6, 4))
    bpy.context.object.data.energy = 300
    bpy.context.object.data.size = 3
    cam = camera((0, -9, 0), (1.5, 0, 0), lens=rng.choice([35, 50]))
    key_cam(cam, 1, (rng.uniform(-1, 1), -9, rng.uniform(-0.5, 0.5)), (1.2, 0, 0))
    key_cam(cam, a["frames"], (rng.uniform(0, 3), -7.5, rng.uniform(-0.5, 0.8)), (2.0, 0, 0))
    linear_fcurves(cam)


WORDS = ["EXIT", "Floor 3", "Room 214", "Library", "Quiet please", "Meeting 14:30", "Lab B-12", "Archive", "Storage",
         "Fire door keep closed", "Lift", "Stairs", "Reception", "Cafe open 08-17", "Platform 2", "No entry",
         "Gallery", "Auditorium", "Toilets", "First aid", "Wi-Fi: guest", "Lockers 101-160", "Office 3.07", "Workshop"]


def scene_interior(a, rng):
    P = a.get("params", {})
    sky(0.6, rng.uniform(0.2, 0.8), rng.uniform(0, 6.28))
    L = 40.0
    wall_c = rng.choice([(0.8, 0.78, 0.72), (0.6, 0.66, 0.7), (0.75, 0.6, 0.5), (0.9, 0.9, 0.9)])
    wall = textured_mat("plaster", "noise", 10, wall_c, tuple(c * 0.92 for c in wall_c), rough=0.9, bump=0.08, vertical=True)
    tiles = textured_mat("tiles", rng.choice(["checker", "brick"]), rng.uniform(1.5, 3.5), (0.85, 0.85, 0.82), (0.15, 0.15, 0.17), rough=0.25, bump=0.15)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, L / 2, 0))
    fl = bpy.context.object
    fl.scale = (4, L, 1)
    fl.data.materials.append(tiles)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, L / 2, 3.2))
    ce = bpy.context.object
    ce.scale = (4, L, 1)
    ce.data.materials.append(mat("ceil", (0.9, 0.9, 0.9), 0.0, 0.9))
    for sx in (-2, 2):
        bpy.ops.mesh.primitive_plane_add(size=1, location=(sx, L / 2, 1.6), rotation=(0, math.pi / 2, 0))
        w = bpy.context.object
        w.scale = (3.2, L, 1)
        w.data.materials.append(wall)
    lamp = mat("lamp", (1, 1, 1), emission=(1.0, 0.95, 0.85), strength=rng.uniform(4, 10))
    add_boxes("lamps", [(0, 1.5 + i * 3, 3.18, 0.4, 1.2, 0.02, 0, 0) for i in range(int(L / 3))], [lamp])
    book_mats = [mat(f"book{i}", tuple(rng.uniform(0.05, 0.8) for _ in range(3)), 0.0, 0.6) for i in range(12)]
    shelf_m = mat("shelf", (0.35, 0.22, 0.12), 0.0, 0.6)
    boxes = []
    colors = [(0.9, 0.9, 0.9), (0.05, 0.25, 0.6), (0.7, 0.05, 0.05), (0.95, 0.75, 0.05), (0.05, 0.4, 0.15), (0.02, 0.02, 0.02)]
    y = 1.0
    while y < L - 2:
        side = rng.choice([-1, 1])
        kind = rng.random()
        if kind < 0.45:  # poster / sign with text lines
            wpx, hpx = rng.uniform(0.5, 1.4), rng.uniform(0.4, 1.0)
            bg, fg = rng.sample(colors, 2)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(side * 1.98, y, rng.uniform(1.2, 2.2)))
            pn = bpy.context.object
            pn.scale = (0.02, wpx, hpx)
            pn.data.materials.append(mat(f"pb{y}", bg, 0.0, 0.5))
            fm = mat(f"pf{y}", fg, 0.0, 0.4)
            for li in range(rng.randint(1, 4)):
                txt = rng.choice(WORDS) if li == 0 else " ".join(str(rng.randint(10, 9999)) for _ in range(rng.randint(1, 4)))
                text_obj(txt, (side * 1.955, y - side * wpx * 0.45, pn.location.z + hpx * 0.30 - li * hpx * 0.26),
                         (math.pi / 2, 0, -side * math.pi / 2), hpx * (0.24 if li == 0 else 0.13), fm, rng)
            y += wpx + rng.uniform(0.6, 2.0)
        elif kind < 0.75:  # shelf of books (one mesh, palette materials)
            for row in range(4):
                z = 0.3 + row * 0.55
                boxes.append((side * 1.8, y + 0.9, z, 0.4, 1.8, 0.03, 0, 0))
                yy = y + 0.05
                while yy < y + 1.75:
                    bw = rng.uniform(0.03, 0.09)
                    bh = rng.uniform(0.28, 0.42)
                    boxes.append((side * 1.82, yy + bw / 2, z + 0.015 + bh / 2, 0.3, bw, bh, 0, 1 + rng.randrange(12)))
                    yy += bw + 0.004
            y += 2.5
        else:  # door with frame and number
            bpy.ops.mesh.primitive_cube_add(size=1, location=(side * 1.99, y + 0.5, 1.05))
            d = bpy.context.object
            d.scale = (0.03, 0.95, 2.1)
            d.data.materials.append(mat(f"door{y}", rng.choice(colors), 0.0, 0.4))
            text_obj(str(rng.randint(100, 499)), (side * 1.96, y + 0.25, 1.75), (math.pi / 2, 0, -side * math.pi / 2), 0.16,
                     mat("num", (0.95, 0.95, 0.95), 1.0, 0.2), rng)
            y += 1.6
    if boxes:
        add_boxes("shelves", boxes, [shelf_m] + book_mats)
    cam = camera((0, 0.5, 1.6), (0, 10, 1.5), lens=rng.choice([20, 24, 28]))
    v = P.get("speed", rng.uniform(0.8, 2.2))
    yaw = rng.uniform(-0.6, 0.6)
    key_cam(cam, 1, (rng.uniform(-0.6, 0.6), 0.5, 1.6), (yaw * 4, 10, 1.5))
    key_cam(cam, a["frames"], (rng.uniform(-0.6, 0.6), 0.5 + v * dur_s(a), 1.6), (-yaw * 4, 10 + v * dur_s(a), 1.4))
    linear_fcurves(cam)


def scene_tunnel(a, rng):
    bpy.context.scene.world = bpy.data.worlds.new("dark")
    L = 900.0
    R = rng.uniform(3.0, 5.0)
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=R, depth=L, location=(0, L / 2, 0), rotation=(math.pi / 2, 0, 0))
    tube = bpy.context.object
    tube.data.materials.append(textured_mat("concrete", "noise", 2.0, (0.25, 0.25, 0.26), (0.45, 0.44, 0.42), rough=0.9, bump=0.4))
    bpy.ops.object.shade_smooth()
    lc = rng.choice([(1.0, 0.85, 0.6), (0.7, 0.85, 1.0), (1.0, 0.5, 0.2)])
    lamp = mat("lamp", (1, 1, 1), emission=lc, strength=rng.uniform(15, 40))
    panel_m = mat("panel", (0.9, 0.9, 0.9), 0.0, 0.4)
    ink = mat("ink", (0.02, 0.02, 0.02), 0.0, 0.5)
    spacing = rng.uniform(4, 8)
    boxes = []
    for i in range(int(L / spacing)):
        y = i * spacing
        for sd in (-1, 1):
            boxes.append((sd * R * 0.7, y, R * 0.7, 0.15, 1.2, 0.08, 0, 0))
        if i % 3 == 0:
            boxes.append((-R * 0.92, y, 0.0, 0.02, 1.2, 0.6, 0, 1))
            if y < 120 + 60 * dur_s(a):  # numbered panels only where the camera passes
                text_obj(f"{int(y)} m", (-R * 0.9, y - 0.5, -0.15), (math.pi / 2, 0, -math.pi / 2), 0.35, ink, rng)
    add_boxes("lights_panels", boxes, [lamp, panel_m])
    for k in range(rng.randint(2, 6)):  # cables
        ang = rng.uniform(0.3, 1.2) * rng.choice([-1, 1])
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=L, location=(R * 0.95 * math.sin(ang), L / 2, R * 0.95 * math.cos(ang)), rotation=(math.pi / 2, 0, 0))
        bpy.context.object.data.materials.append(mat(f"cable{k}", (0.05, 0.05, 0.05), 0.0, 0.5))
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, L / 2, -R * 0.75))
    road = bpy.context.object
    road.scale = (R * 1.3, L, 1)
    road.data.materials.append(textured_mat("road", "noise", 5, (0.03, 0.03, 0.035), (0.1, 0.1, 0.11), rough=0.6, bump=0.3))
    add_boxes("lanes", [(0, i * 6, -R * 0.75 + 0.01, 0.12, 3, 0.004, 0, 0) for i in range(int(L / 6))], [mat("lane", (0.9, 0.9, 0.85), 0.0, 0.5)])
    speed = rng.uniform(25, 60)
    cam = camera((0, 5, 0), (0, 50, 0), lens=rng.choice([18, 24, 28]))
    d = speed * dur_s(a)
    sway = rng.uniform(-0.8, 0.8)
    key_cam(cam, 1, (sway, 5, -R * 0.3), (0, 60, -R * 0.2))
    key_cam(cam, a["frames"], (-sway, 5 + d, -R * 0.2), (0, 60 + d, -R * 0.1))
    linear_fcurves(cam)


def scene_chrome(a, rng):
    sky(rng.uniform(0.1, 0.3), rng.uniform(0.2, 0.8), rng.uniform(0, 6.28))
    floor = textured_mat("floor", rng.choice(["checker", "voronoi", "wave"]), rng.uniform(1, 4), (0.9, 0.9, 0.9), (0.05, 0.05, 0.06), rough=rng.uniform(0.05, 0.3), bump=0.05)
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0))
    bpy.context.object.data.materials.append(floor)
    mirror = mat("mirror", (0.95, 0.95, 0.95), 1.0, 0.02)
    gold = mat("gold", (1.0, 0.76, 0.33), 1.0, 0.08)
    glass = mat("glass", (0.95, 0.97, 1.0), 0.0, 0.0, transmission=1.0, ior=1.5)
    colored = [mat(f"car{i}", c, 0.4, 0.15) for i, c in enumerate([(0.7, 0.02, 0.02), (0.02, 0.2, 0.7), (0.05, 0.5, 0.1)])]
    objs = []
    for i in range(rng.randint(6, 14)):
        kind = rng.choice(["sphere", "torus", "cube", "monkey", "cyl"])
        loc = (rng.uniform(-5, 5), rng.uniform(-3, 5), 0)
        sc = rng.uniform(0.4, 1.2)
        if kind == "sphere":
            bpy.ops.mesh.primitive_uv_sphere_add(radius=sc, location=(loc[0], loc[1], sc), segments=48, ring_count=24)
        elif kind == "torus":
            bpy.ops.mesh.primitive_torus_add(major_radius=sc, minor_radius=sc * 0.3, location=(loc[0], loc[1], sc * 1.2), rotation=(rng.uniform(0, 1.5), 0, 0))
        elif kind == "cube":
            bpy.ops.mesh.primitive_cube_add(size=sc * 1.4, location=(loc[0], loc[1], sc * 0.7))
            bev = bpy.context.object.modifiers.new("b", "BEVEL")
            bev.width, bev.segments = 0.05, 3
        elif kind == "monkey":
            bpy.ops.mesh.primitive_monkey_add(size=sc * 1.6, location=(loc[0], loc[1], sc))
            bpy.context.object.modifiers.new("s", "SUBSURF").levels = 2
        else:
            bpy.ops.mesh.primitive_cylinder_add(radius=sc * 0.5, depth=sc * 2.5, location=(loc[0], loc[1], sc * 1.25), vertices=48)
        o = bpy.context.object
        bpy.ops.object.shade_smooth()
        o.data.materials.append(rng.choice([mirror, mirror, gold, glass] + colored))
        o.keyframe_insert("rotation_euler", frame=1)
        o.rotation_euler[2] += rng.uniform(-2, 2) * dur_s(a)
        o.keyframe_insert("rotation_euler", frame=a["frames"])
        linear_fcurves(o)
        objs.append(o)
    for i in range(rng.randint(2, 5)):  # coloured light strips -> sharp reflections
        bpy.ops.mesh.primitive_cube_add(size=1, location=(rng.uniform(-8, 8), rng.uniform(4, 9), rng.uniform(1, 5)))
        st = bpy.context.object
        st.scale = (rng.uniform(1, 4), 0.1, 0.1)
        st.data.materials.append(mat(f"strip{i}", (1, 1, 1), emission=tuple(rng.uniform(0.2, 1) for _ in range(3)), strength=rng.uniform(5, 20)))
    cam = camera((0, -10, 3), (0, 0, 0.8), lens=rng.choice([35, 50, 85]))
    r0 = rng.uniform(-0.8, 0.8)
    r1 = r0 + rng.choice([-1, 1]) * rng.uniform(0.3, 1.0)
    key_cam(cam, 1, (10 * math.sin(r0), -10 * math.cos(r0), rng.uniform(1.5, 4)), (0, 1, 0.8))
    key_cam(cam, a["frames"], (10 * math.sin(r1), -10 * math.cos(r1), rng.uniform(1.0, 3.5)), (0, 1, 0.8))
    linear_fcurves(cam)


def scene_particles(a, rng):
    P = a.get("params", {})
    kind = P.get("kind", rng.choice(["sparks", "snow", "confetti"]))
    if kind == "snow":
        sky(rng.uniform(0.1, 0.25), rng.uniform(0.05, 0.3), rng.uniform(0, 6.28))
    else:
        sky(0.03, 0.05, rng.uniform(0, 6.28))
    g, _ = displaced_grid(60, 80, 0.4, 6, rng.randint(0, 9999))
    g.data.materials.append(textured_mat("ground", "noise", 4, (0.05, 0.05, 0.05), (0.2, 0.2, 0.21), rough=0.8, bump=0.4) if kind != "snow"
                            else mat("snowground", (0.85, 0.87, 0.9), 0.0, 0.6))
    if kind == "sparks":
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.02, location=(0, 0, -100))
        inst = bpy.context.object
        inst.data.materials.append(mat("spark", (1, 0.6, 0.2), emission=(1.0, rng.uniform(0.35, 0.7), 0.1), strength=rng.uniform(30, 80)))
        bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=1.0, location=(0, 4, 0.5))
        em = bpy.context.object
        em.data.materials.append(mat("steel", (0.6, 0.6, 0.62), 1.0, 0.3))
        count, life, vel, rnd, size, grav = 6000, 40, 6.0, 3.0, 1.0, 1.0
    elif kind == "snow":
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.025, location=(0, 0, -100))
        inst = bpy.context.object
        inst.data.materials.append(mat("flake", (0.95, 0.96, 1.0), 0.0, 0.4))
        bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 8, 9))
        em = bpy.context.object
        count, life, vel, rnd, size, grav = 25000, 400, 0.0, 0.4, 1.0, 0.05
        bpy.ops.object.effector_add(type="TURBULENCE", location=(0, 8, 3))
        bpy.context.object.field.strength = rng.uniform(2, 6)
        bpy.context.object.field.size = 2.0
    else:
        bpy.ops.mesh.primitive_plane_add(size=0.06, location=(0, 0, -100))
        inst = bpy.context.object
        inst.data.materials.append(mat("conf", (0.9, 0.2, 0.3), 0.3, 0.3))
        bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 6, 7))
        em = bpy.context.object
        count, life, vel, rnd, size, grav = 8000, 300, 0.5, 1.5, 1.0, 0.15
    em.show_instancer_for_render = kind == "sparks"  # hide the emitter mesh, keep its particles visible
    ps = em.modifiers.new("ps", "PARTICLE_SYSTEM").particle_system
    ps.seed = rng.randint(0, 99999)
    st = ps.settings
    st.count = count
    st.frame_start = -life if kind != "sparks" else 1
    st.frame_end = a["frames"]
    st.lifetime = life
    st.lifetime_random = 0.5
    st.normal_factor = vel
    st.factor_random = rnd
    st.effector_weights.gravity = grav
    st.render_type = "OBJECT"
    st.instance_object = inst
    st.particle_size = size
    st.size_random = 0.6
    st.use_rotations = True
    st.angular_velocity_mode = "RAND" if kind == "confetti" else "NONE"
    st.angular_velocity_factor = 6.0
    st.rotation_factor_random = 1.0
    st.phase_factor_random = 2.0
    ps.point_cache.frame_start = int(st.frame_start)   # pre-roll for snow / confetti (negative start)
    ps.point_cache.frame_end = int(a["frames"])
    if kind == "sparks":
        st.emit_from = "FACE"
        bpy.ops.object.light_add(type="POINT", location=(0, 4, 1.5))
        bpy.context.object.data.energy = 300
        bpy.context.object.data.color = (1.0, 0.6, 0.3)
    cam = camera((0, -6, 1.6), (0, 4, 1.5), lens=rng.choice([24, 35, 50]))
    key_cam(cam, 1, (rng.uniform(-2, 2), -6, rng.uniform(1, 2.5)), (0, 4, 1.5))
    key_cam(cam, a["frames"], (rng.uniform(-2, 2), -5, rng.uniform(1, 2.5)), (0, 4, 1.8))
    linear_fcurves(cam)


def toon_mat(name, color, outline=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if outline:
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (0.01, 0.01, 0.01, 1)
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        m.use_backface_culling = True
        return m
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    dif.inputs["Color"].default_value = (*color, 1)
    s2r = nt.nodes.new("ShaderNodeShaderToRGB")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    el = ramp.color_ramp.elements
    el[0].position, el[0].color = 0.0, (*(c * 0.45 for c in color), 1)
    el[1].position, el[1].color = 0.5, (*color, 1)
    e = el.new(0.12)
    e.color = (*(c * 0.75 for c in color), 1)
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(dif.outputs[0], s2r.inputs[0])
    nt.links.new(s2r.outputs["Color"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def outlined(obj, outline_mat, thickness):
    obj.data.materials.append(outline_mat)
    sol = obj.modifiers.new("outline", "SOLIDIFY")
    sol.thickness = -thickness
    sol.use_flip_normals = True
    sol.material_offset = len(obj.data.materials) - 1
    sol.use_rim = False


def scene_toon(a, rng):
    a["view"] = "Standard"  # cel colours as authored (AgX desaturates flat toon colours)
    a["exposure"] = 0.0
    w = bpy.data.worlds.new("toonsky")
    bpy.context.scene.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (*rng.choice([(0.45, 0.7, 1.0), (1.0, 0.75, 0.55), (0.6, 0.85, 0.9)]), 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    ol = toon_mat("outline", (0, 0, 0), outline=True)
    pal = [(0.95, 0.3, 0.25), (0.25, 0.55, 0.95), (0.98, 0.8, 0.2), (0.35, 0.8, 0.35), (0.85, 0.45, 0.9), (1.0, 0.6, 0.2)]
    bpy.ops.mesh.primitive_plane_add(size=200)
    gr = bpy.context.object
    gr.data.materials.append(toon_mat("grass", rng.choice([(0.35, 0.75, 0.3), (0.55, 0.8, 0.35), (0.8, 0.7, 0.45)])))
    th = rng.uniform(0.02, 0.05)
    for i in range(rng.randint(12, 30)):  # houses and trees
        x, y = rng.uniform(-25, 25), rng.uniform(3, 40)
        if abs(x) < 3:
            continue
        if rng.random() < 0.5:
            hgt = rng.uniform(1.5, 4)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, hgt / 2))
            hs = bpy.context.object
            hs.scale = (rng.uniform(1.5, 3), rng.uniform(1.5, 3), hgt)
            hs.data.materials.append(toon_mat(f"h{i}", rng.choice(pal)))
            outlined(hs, ol, th)
            bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=max(hs.scale[0], hs.scale[1]) * 0.8, depth=1.2, location=(x, y, hgt + 0.6), rotation=(0, 0, math.pi / 4))
            rf = bpy.context.object
            rf.data.materials.append(toon_mat(f"r{i}", rng.choice(pal)))
            outlined(rf, ol, th)
        else:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=1.6, location=(x, y, 0.8))
            tk = bpy.context.object
            tk.data.materials.append(toon_mat(f"t{i}", (0.45, 0.28, 0.15)))
            outlined(tk, ol, th)
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=rng.uniform(0.9, 1.6), location=(x, y, 2.4))
            cn = bpy.context.object
            cn.data.materials.append(toon_mat(f"c{i}", rng.choice([(0.2, 0.6, 0.25), (0.3, 0.7, 0.2), (0.9, 0.5, 0.15)])))
            outlined(cn, ol, th)
    fence_m = toon_mat("fence", rng.choice([(0.95, 0.95, 0.9), (0.6, 0.4, 0.25)]))
    posts = []
    for sd in (-1, 1):
        x = sd * rng.uniform(2.5, 4.0)
        for i in range(40):
            posts.append((x, -6 + i * 0.8, 0.45, 0.08, 0.08, 0.9, 0, 0))
        posts.append((x, 10, 0.75, 0.05, 32, 0.07, 0, 0))
        posts.append((x, 10, 0.35, 0.05, 32, 0.07, 0, 0))
    fence = add_boxes("fence", posts, [fence_m])
    outlined(fence, ol, th * 0.6)
    for i in range(rng.randint(3, 7)):  # clouds
        bpy.ops.mesh.primitive_uv_sphere_add(radius=rng.uniform(1.5, 3), location=(rng.uniform(-30, 30), rng.uniform(30, 60), rng.uniform(10, 18)))
        cl = bpy.context.object
        cl.scale = (2.2, 1.0, 0.7)
        bpy.ops.object.shade_smooth()
        cl.data.materials.append(toon_mat(f"cloud{i}", (0.98, 0.98, 1.0)))
        outlined(cl, ol, th * 2)
    fps = a["fps_num"] / a["fps_den"]
    for k in range(rng.randint(3, 7)):  # bouncing characters (capsule body + eyes)
        col = rng.choice(pal)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(0, 0, 0.5))
        body = bpy.context.object
        body.scale = (1, 1, 1.3)
        bpy.ops.object.shade_smooth()
        body.data.materials.append(toon_mat(f"b{k}", col))
        outlined(body, ol, th)
        for ex in (-0.18, 0.18):
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.11, location=(ex, -0.42, 0.3))
            eye = bpy.context.object
            eye.data.materials.append(toon_mat("eye", (1, 1, 1)))
            eye.parent = body
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.05, location=(ex, -0.52, 0.3))
            pu = bpy.context.object
            pu.data.materials.append(toon_mat("pupil", (0.02, 0.02, 0.02)))
            pu.parent = body
        x0, y0 = rng.uniform(-2.2, 2.2), rng.uniform(-1, 6)
        vx, vy = rng.uniform(-1.5, 1.5), rng.uniform(-0.5, 2.0)
        hop = rng.uniform(1.5, 3.0)
        amp = rng.uniform(0.5, 1.5)
        for f in range(1, a["frames"] + 1):
            t = (f - 1) / fps
            ph = (t * hop) % 1.0
            z = 0.65 + amp * 4 * ph * (1 - ph)
            squash = 1.0 - 0.25 * max(0.0, 1 - ph * 8) if ph < 0.12 else 1.0
            body.location = (x0 + vx * t, y0 + vy * t, z)
            body.scale = (1 / math.sqrt(squash), 1 / math.sqrt(squash), 1.3 * squash)
            body.keyframe_insert("location", frame=f)
            body.keyframe_insert("scale", frame=f)
    bpy.ops.object.light_add(type="SUN", rotation=(0.9, 0.2, rng.uniform(0, 6.28)))
    bpy.context.object.data.energy = 3.0
    cam = camera((0, -7, 1.8), (0, 4, 0.8), lens=rng.choice([28, 35, 50]))
    v = rng.uniform(0.3, 1.2)
    key_cam(cam, 1, (rng.uniform(-1.5, 1.5), -7, rng.uniform(1.2, 2.6)), (0, 4, 0.8))
    key_cam(cam, a["frames"], (rng.uniform(-1.5, 1.5), -7 + v * dur_s(a), rng.uniform(1.2, 2.6)), (rng.uniform(-1, 1), 4 + v * dur_s(a), 0.8))
    linear_fcurves(cam)


SCENES = {"gears": scene_gears, "signs": scene_signs, "ocean": scene_ocean, "city": scene_city,
          "forest": scene_forest, "terrain": scene_terrain, "machine": scene_machine, "clock": scene_clock,
          "interior": scene_interior, "tunnel": scene_tunnel, "chrome": scene_chrome, "particles": scene_particles,
          "toon": scene_toon}


def main():
    a = args()
    reset()
    rng = random.Random(int(a["seed"]))
    setup_render(a)
    SCENES[a["scene"]](a, rng)
    setup_render(a)  # factory reset clears nothing after this point; re-apply after scene build
    if any(ps.settings.type == "EMITTER" and ps.settings.physics_type != "NO" for o in bpy.context.scene.objects for ps in o.particle_systems):
        bpy.ops.ptcache.bake_all(bake=True)  # simulate particles once, frame by frame, before rendering
    t = time.time()
    if a.get("preview"):
        sc = bpy.context.scene
        sc.render.resolution_percentage = 50
        for f in (1, max(1, a["frames"] // 2)):
            sc.frame_set(f)
            sc.render.filepath = a["out_dir"].rstrip("/") + f"/frame_{f:04d}.png"
            bpy.ops.render.render(write_still=True)
        print(json.dumps({"rendered_frames": 2, "seconds": round(time.time() - t, 1), "blender": bpy.app.version_string}))
        return
    bpy.ops.render.render(animation=True)
    print(json.dumps({"rendered_frames": a["frames"], "seconds": round(time.time() - t, 1), "blender": bpy.app.version_string}))


main()
