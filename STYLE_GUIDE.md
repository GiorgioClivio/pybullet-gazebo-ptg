# PTG environment visual language

Aim for readable, restrained semirealism with simple physical geometry. The current
profile is `apartment_office`, version 2. Future metro and cave generators should
reuse the material/geometry pipeline and backend-neutral scene schema, with their
own layouts, asset families and finish profiles. Only apartment/office is implemented.

## Materials and colour

- Structural walls, corridors and ceilings keep one warm white/greige building paint.
  Rooms take a **style family** from their use (replaces the former "one wall paint per
  building" rule; mapping and seeds in README "Room style families", code in
  `room_styles.py`):
  - corporate: today's restrained look (offices, meeting rooms, service rooms);
  - warm: warm paint (.90/.86/.82), warm planks/tile tint, walnut skirting and door
    architraves, dark window surrounds with a sill board; furniture tints walnut, oak,
    charcoal, one terracotta accent (bedrooms, private bathrooms, domestic kitchens);
  - wayfinding: the warm base plus a yellow band at 1.05 to 1.17 m, a dark base line,
    yellow door architraves, a door plate and a pictogram sign on the corridor side
    (lounges, living rooms, private offices; never bedrooms);
  - lab (labs, preferring larger rooms), two variants, one lab in six is Lab D66: the
    aseptic lab (white walls, light grey tile, cyan skirting, white/light grey/cyan
    benches, fume hoods and glassware) and Lab D66, the robotics lab where PTG was born
    (white walls, grey vinyl-look floor, grey blinds, tile ceiling, cyan-seat task chairs,
    white desks on grey frames, birch pegboard with robot models, "LAB D66" room sign).
    Seed 66 builds only Lab D66, from the lab's floor plan (README, "Seed 66 is Lab D66").
  Per-room paint lives on 3 mm skins on the room side of each wall segment (a body has
  one texture on all faces and walls are shared). Families change tints only: base
  material images stay shared by the whole building. Plaster has very subtle texture,
  without large patches, brick patterns or decorative panels.
- Two compatible floor finishes: warm grey ceramic tile and oak parquet. Corridors,
  landings and wet rooms are tiled; approximately 75% of dry rooms use parquet. Tile modules are
  0.50 × 0.50 m; staggered planks are 1.00 × 0.25 m.
- Furniture uses oak, charcoal metal, off-white ceramics and six muted fabric/book
  accents: slate, olive, clay, sand, charcoal and warm grey. Natural green is reserved
  for plants. No independent saturated colour randomisation per model.
- Every opaque material uses the same simple albedo pipeline. Base material images
  are grayscale, lightly patterned and tinted by the palette. A wood/fabric finish
  shares one texture specification throughout a building. Pictures, notices, signs
  and screens are deliberate printed colour images with desaturated inks.
- This is an albedo/shading workflow for PyBullet, without PBR normal maps, costly
  reflections or baked photographic textures. Future supplied models should follow
  this same level of detail and palette rather than introduce another art style.

## Shape and budget

Use 44-triangle chamfered panels for furniture; bevels are usually at most 8 mm on
hard materials and 35 mm on cushions. Legs, lamps, vases, bottles and pots use
12 radial segments. Foliage uses low resolution ellipsoids; mug handles are curved.
Screens use one flat two-triangle face, 2 mm in front of the bevelled physical bezel,
with the stand behind the display. This separation prevents depth-buffer fighting.
Architecture retains inexpensive boxes and actual openings.

Target fewer than 200,000 visible triangles per default 12-room storey. Tests check
this target for seeds 0, 7 and 13, and verify mesh envelopes, normals and winding.
This is a geometry target, not an FPS guarantee for every robot/sensor setup.
The seed 7 example contains 122,890 triangles, 449 semantic instances and 2,417
static parts. More rooms, floors and objects increase the cost. Mesh construction,
collision shapes and texture images are cached where they can be shared.
Generated PNGs have a 64 MiB disk-cache limit, with active scene images pinned;
unneeded old generated images are evicted and recreated when required. The complete
workspace including previews was about 75 MB at validation. Future supplied assets
and installed runtime dependencies are outside the generated-cache cap.

Reserve detail for silhouettes, furniture structure, recognizable household objects
and useful landmarks. Clocks, switches, vents, printed notices and artwork break up
walls without changing their paint. Vary room contents and layouts to reduce visual
aliasing, preserving the reserved 0.90 m routes. Density is measured by semantic
instances rather than counting each chair leg or clock mark as an object.
Room identity comes from function as well as appearance: bathrooms, kitchens,
laundries, workshops and meeting rooms supplement the original room types. Place
toiletries in bathrooms, dishes/appliances in kitchens and equipment at workbenches.
Cables belong near equipment and use six-sided tubes; keep them off all travel lanes.

## Physics and backend contract

All dimensions are metres, Z up. `scene["boxes"]` remains the legacy name for the
part list; a part may now have `shape` equal to `bevel`, `lathe`, `ellipsoid` or
`handle`, `display` or `cable`. Missing `shape` means a box. Each part exports its envelope `size`, world
`center`, material, colour and optional texture specification. Turned shapes can
export a normalized `[radius, height]` profile and an axis (0/1/2). `geometry.mesh`
reconstructs the visual vertices, normals, UVs and triangles from this specification.
Display and cable rotation is encoded by quarter-turn `facing`; a cable also stores
its normalized XY `path`. Slabs export `collision_size`, extended by 1 mm along X/Y
to stitch collision seams without overlapping visual floor surfaces.

Architecture and chamfered furniture use box collisions; turned parts use convex
hulls, and cables use static triangle collision. Approximations stay conservative, including small filled cavities in
handles. Scene generation and images finish before opening PyBullet. A future
Gazebo exporter should reproduce these visual meshes and collision approximations,
not reroll the environment. Save the JSON as well as its seed for archived runs.

Every storey must contain a simple cycle through at least three spaces, even with
zero optional loops. Tree-shaped partitions gain a physical east return corridor.
Export its witness in `loop_routes`: space IDs, portal indices, closed XYZ route,
length and cycle rank. Routes use reserved room hubs and doorway approaches.

`semantics.py` supplies COCO80 class hints where a model has a corresponding class;
unsupported classes stay unmapped. These are ground truth labels, never evidence
that a real detector recognizes the render. Keep geometry recognizable, then
measure recall and localisation with the actual robot cameras and models.

`scene["style"]` exports the profile, version, texture version and building palette;
`scene["geometry_stats"]` exports triangle counts and curved part counts. The robot
model, sensor extrinsics, locomotion and mapping stack remain the responsibility of the
host simulation. Preview camera heights and the walk controller do not represent a
calibrated sensor or dynamics model.
