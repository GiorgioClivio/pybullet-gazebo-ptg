"""Metric household silhouettes; a small shared procedural catalog, no model files."""
import math


def _build_toilet(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of toilet."""
    box(0, -.05, .14, .25, .37, .28, "ceramic", white, shape="lathe")
    box(0, .05, .33, .40, .54, .24, "ceramic", white, shape="lathe", profile=bowl)
    box(0, .05, .46, .42, .56, .035, "plastic", white, shape="handle", axis=2)
    box(0, -.23, .62, .40, .17, .44, "ceramic", white)
    box(.11, -.23, .85, .07, .045, .012, "metal", chrome)


def _build_sink(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of sink."""
    box(0, 0, .35, .59, .45, .70, "plastic", white)
    for x in (-.14, .14):
        box(x, .232, .34, .27, .025, .61, "plastic", (.67, .68, .65, 1))
        box(x/3, .25, .51, .018, .025, .11, "metal")
    box(0, 0, .77, .62, .47, .14, "ceramic", white, shape="lathe", profile=bowl)
    box(.18, -.15, .91, .027, .027, .20, "metal", chrome, shape="lathe")
    box(.18, -.09, 1., .025, .14, .025, "metal", chrome)
    box(0, -.23, 1.35, .55, .03, .65, "metal", (.65, .70, .70, 1))
    box(0, .20, .87, .12, .07, .035, "ceramic", white)
    box(-.18, -.10, .92, .075, .075, .16, "ceramic", white, shape="lathe")
    box(-.18, -.10, 1.05, .014, .014, .17, "plastic", color)
    box(-.18, -.10, 1.14, .020, .022, .04, "paper", white)
    box(0, .27, .40, .22, .025, .30, "fabric", color)


def _build_shower(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of shower."""
    box(0, 0, .035, .90, .90, .07, "ceramic", white)
    box(0, 0, .075, .75, .75, .02, "plastic", (.62, .63, .60, 1))
    box(0, -.39, 1.08, .025, .025, 1.94, "metal", chrome, shape="lathe")
    box(0, -.29, 2.04, .025, .24, .025, "metal", chrome)
    box(0, -.19, 2.03, .18, .18, .025, "metal", chrome, shape="lathe")
    box(-.43, 0, 1., .018, .85, 1.9, "glass", (.75, .80, .79, .35))


def _build_refrigerator(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of refrigerator, washing_machine, oven."""
    w, d, h = {"refrigerator": (.66, .65, 1.82), "washing_machine": (.60, .60, .85), "oven": (.60, .60, .89)}[name]
    box(0, 0, h/2, w, d, h, "plastic", white)
    if name == "refrigerator":
        for z, height in ((.59, 1.12), (1.49, .59)):
            box(0, d/2+.01, z, w-.03, .035, height, "plastic", white)
            box(-.24, d/2+.045, z+.1, .025, .035, .30, "metal", chrome)
    elif name == "washing_machine":
        box(0, d/2+.02, .40, .44, .04, .44, "metal", chrome, shape="lathe", axis=1)
        box(0, d/2+.045, .40, .34, .015, .34, "plastic", dark, shape="lathe", axis=1)
        box(0, d/2+.056, .39, .23, .008, .22, "fabric", color, shape="ellipsoid")
        box(.18, d/2+.025, .74, .065, .03, .065, "plastic", dark, shape="lathe", axis=1)
    else:
        box(0, d/2+.015, .41, .53, .025, .51, "metal", dark)
        box(0, d/2+.034, .41, .39, .008, .33, "plastic", (.16, .19, .19, 1))
        box(0, d/2+.06, .70, .42, .04, .025, "metal", chrome)
        for x in (-.16, .16):
            box(x, d/2+.02, .80, .045, .03, .045, "metal", shape="lathe", axis=1)
            for y in (-.15, .15):
                box(x, y, h+.008, .20, .20, .016, "metal", dark, shape="handle", axis=2)


def _build_kitchen_counter(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of kitchen_counter, workbench."""
    w, d = (1.15, .60) if name == "kitchen_counter" else (1.35, .65)
    if name == "workbench":
        legs(w, d, .85)
    else:
        box(0, 0, .41, w-.03, d-.04, .82, "plastic", (.64, .65, .61, 1))
        for x in (-w/4, w/4):
            box(x, d/2, .43, w/2-.025, .03, .73, "plastic", white)
            box(x, d/2+.025, .68, .13, .025, .018, "metal")
    box(0, 0, .87, w, d, .045)
    if name == "workbench":
        box(-.40, -.15, .99, .32, .23, .20, "metal", color)
        box(-.40, -.15, 1.11, .16, .025, .025, "metal")


def _build_microwave(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of microwave."""
    box(0, 0, .15, .47, .35, .30, "plastic", white)
    box(-.04, .183, .15, .32, .016, .22, "plastic", dark)
    box(.16, .20, .15, .025, .025, .16, "metal", chrome)
    for z in (.08, .22):
        box(.20, .18, z, .026, .01, .026, "metal", shape="lathe", axis=1)


def _build_laundry_basket(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of laundry_basket, bucket."""
    box(0, 0, .22, .38, .34, .44, "plastic", (.65, .62, .53, 1), shape="lathe", profile=bowl)
    if name == "laundry_basket":
        for x, z in ((-.07, .43), (.07, .48)):
            box(x, 0, z, .23, .24, .08, "fabric", color)
    else:
        box(0, 0, .49, .34, .02, .25, "metal", shape="handle", axis=1)


def _build_stool(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of stool."""
    legs(.36, .36, .43, .035)
    box(0, 0, .46, .40, .40, .06, "wood", shape="lathe")


def _build_backpack(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of backpack, toolbox."""
    w, d, h = (.34, .23, .46) if name == "backpack" else (.43, .25, .24)
    mat = "fabric" if name == "backpack" else "metal"
    box(0, 0, h/2, w, d, h, mat, color)
    box(0, d/2+.01, h*.35, w*.7, .045, h*.4, mat, color)
    box(0, 0, h+.035, w*.4, .025, .07, "plastic", dark, shape="handle", axis=1)


def _build_towel(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of towel."""
    for i in range(3):
        box(i*.008, 0, .018+i*.024, .33-i*.01, .23, .024, "fabric", color)


def _build_toothbrush(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of toothbrush."""
    box(0, 0, .013, .018, .18, .022, "plastic", color)
    box(0, .065, .033, .024, .04, .025, "paper", white)


def _build_bowl(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of bowl."""
    box(0, 0, .06, .23, .23, .12, "ceramic", white, shape="lathe", profile=bowl)


def _build_cable(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of cable."""
    path = [[-.48+i*.96/24, .42*math.sin(i*math.pi/12)] for i in range(25)]
    box(0, 0, .007, .95, .42, .014, "plastic", dark, shape="cable", path=path, facing=0)
    box(.45, 0, .017, .055, .032, .034, "plastic", dark)


def _build_lab_bench(name, box, legs, color, white, chrome, dark, bowl):
    """Parts of lab_bench, lab_white_desk, lab_task_chair, fume_hood, test_tube_rack, beaker, flask, reagent_bottle."""
    _aseptic(name, box, legs, white, chrome, dark)


HOUSEHOLD_MODELS = {"toilet": _build_toilet, "sink": _build_sink, "shower": _build_shower,
                    "refrigerator": _build_refrigerator, "washing_machine": _build_refrigerator,
                    "oven": _build_refrigerator, "kitchen_counter": _build_kitchen_counter,
                    "workbench": _build_kitchen_counter, "microwave": _build_microwave,
                    "laundry_basket": _build_laundry_basket, "bucket": _build_laundry_basket, "stool": _build_stool,
                    "backpack": _build_backpack, "toolbox": _build_backpack, "towel": _build_towel,
                    "toothbrush": _build_toothbrush, "bowl": _build_bowl, "cable": _build_cable,
                    "lab_bench": _build_lab_bench, "lab_white_desk": _build_lab_bench,
                    "lab_task_chair": _build_lab_bench, "fume_hood": _build_lab_bench,
                    "test_tube_rack": _build_lab_bench, "beaker": _build_lab_bench, "flask": _build_lab_bench,
                    "reagent_bottle": _build_lab_bench}


def build(name, box, legs, color):
    """Append the parts of household model `name` through the box/legs helpers of furniture._model."""
    white, chrome, dark = (.86, .85, .81, 1), (.55, .58, .58, 1), (.08, .09, .10, 1)
    bowl = [[.48, -.5], [.76, -.36], [1, .40], [1, .5], [.83, .5], [.67, .12], [0, -.25]]
    if name in HOUSEHOLD_MODELS:
        HOUSEHOLD_MODELS[name](name, box, legs, color, white, chrome, dark, bowl)
    elif name.startswith("lab_"):
        _lab(name, box, legs, white, chrome, dark)
    else:
        raise ValueError(name)


# Laboratory catalogue: Lab D66, the robotics lab where PTG was born (room_styles "lab" family).
# Lab D66 furniture: cyan-seat task chairs on white 5-star bases, white desks, a birch pegboard with
# shelves, white cabinets; from the photos: grey steel desk frames, dual monitors, robot models.
LAB_WHITE, LAB_GREY, LAB_CYAN = (.94, .94, .93, 1), (.58, .60, .62, 1), (.20, .66, .76, 1)
BIRCH, BIRCH_SHELF, MESH = (.86, .74, .55, 1), (.80, .66, .46, 1), (.10, .11, .13, 1)
ROBOT_DARK, ROBOT_ORANGE, ROBOT_WHITE = (.16, .16, .17, 1), (.90, .50, .16, 1), (.90, .90, .88, 1)


def _lab_lab_desk(name, box, legs, white, chrome, dark, front):
    """Parts of lab_desk."""
    w, d, h = 1.60, .80, .75
    box(0, 0, h - .0125, w, d, .025, "plastic", LAB_WHITE)
    for x in (-w / 2 + .12, w / 2 - .12):
        box(x, 0, .3675, .06, .06, .675, "metal", LAB_GREY)
        box(x, 0, .015, .06, .66, .03, "metal", LAB_GREY)
    box(0, 0, h - .045, w - .24, .05, .04, "metal", LAB_GREY)
    for mx in (-.29, .29):
        box(mx, -.24, h + .31, .54, .05, .32, "screen")
        box(mx, -.285, h + .10, .05, .04, .18, "metal", LAB_GREY)
        box(mx, -.24, h + .008, .22, .16, .016, "metal", LAB_GREY)
    box(0, .07, h + .01, .44, .14, .02, "plastic", dark)
    box(.52, .15, h + .01, .33, .23, .02, "metal", (.30, .31, .33, 1))
    box(.52, .04, h + .13, .33, .02, .22, "screen")


def _lab_lab_chair(name, box, legs, white, chrome, dark, front):
    """Parts of lab_chair."""
    box(0, 0, .05, .62, .62, .10, "plastic", LAB_WHITE, shape="star")
    box(0, 0, .27, .05, .05, .34, "metal", chrome, shape="lathe")
    box(0, 0, .45, .46, .44, .03, "plastic", LAB_WHITE)
    box(0, .01, .495, .47, .45, .07, "fabric", LAB_CYAN)
    for x in (-.20, .20):
        box(x, -.215, .72, .03, .03, .48, "plastic", LAB_WHITE)
    box(0, -.215, .955, .43, .03, .03, "plastic", LAB_WHITE)
    box(0, -.215, .75, .38, .015, .36, "fabric", MESH)


def _lab_lab_pegboard(name, box, legs, white, chrome, dark, front):
    """Parts of lab_pegboard."""
    w = 2.40
    box(0, -.12, 1.50, w, .018, 1.30, "wood", BIRCH)
    box(-.62, -.106, 1.66, 1.0, .008, .62, "paper", (1, 1, 1, 1), shape=None)  # plain box: fit-to-face poster image
    shelves = ((-1.15, -.08, 1.05), (.05, 1.15, 1.05), (.05, 1.15, 1.34), (.20, 1.15, 1.66))
    for x0, x1, z in shelves:
        box((x0 + x1) / 2, -.021, z, x1 - x0, .18, .02, "wood", BIRCH_SHELF)
    for x in (-1.0, -.78, -.56):  # spare wheels on the lower left shelf
        box(x, -.03, 1.14, .16, .08, .16, "plastic", ROBOT_DARK, shape="lathe", axis=1)
    top = 1.06  # rover on the lower right shelf
    box(.40, -.02, top + .08, .26, .14, .07, "plastic", ROBOT_WHITE)
    for x in (.31, .40, .49):
        for y in (-.10, .06):
            box(x, y, top + .035, .07, .03, .07, "plastic", ROBOT_DARK, shape="lathe", axis=1)
    box(.47, -.02, top + .19, .02, .02, .15, "metal", chrome)
    box(.47, -.02, top + .28, .07, .05, .04, "plastic", ROBOT_WHITE)
    top = 1.35  # quadcopter on the middle shelf: + frame, four rotors
    box(.62, -.02, top + .03, .10, .10, .04, "plastic", ROBOT_DARK)
    box(.62, -.02, top + .045, .40, .02, .015, "plastic", ROBOT_DARK)
    box(.62, -.02, top + .045, .02, .16, .015, "plastic", ROBOT_DARK)
    for dx, dy in ((-.20, 0), (.20, 0), (0, -.08), (0, .08)):
        box(.62 + dx, -.02 + dy, top + .06, .14, .14 if dy == 0 else .02, .008, "plastic", ROBOT_ORANGE, shape="lathe")
    top = 1.67  # robot arm on the top shelf
    box(.75, -.02, top + .02, .10, .10, .04, "metal", ROBOT_DARK, shape="lathe")
    box(.75, -.02, top + .15, .04, .04, .22, "metal", ROBOT_ORANGE)
    box(.85, -.02, top + .26, .20, .04, .04, "metal", ROBOT_ORANGE)
    box(.96, -.02, top + .23, .03, .05, .06, "metal", ROBOT_DARK)
    box(.30, -.02, top + .07, .16, .12, .12, "cardboard")


def _lab_lab_cabinet(name, box, legs, white, chrome, dark, front):
    """Parts of lab_cabinet."""
    w, d, h = 1.0, .50, 2.0
    box(0, 0, h / 2, w, d, h, "plastic", LAB_WHITE)
    for x in (-w / 4, w / 4):
        box(x, d / 2 + .008, h / 2 + .01, w / 2 - .012, .016, h - .06, "plastic", front)
    for x in (-.03, .03):
        box(x, d / 2 + .025, 1.05, .015, .018, .22, "metal", chrome)
    box(-.18, 0, h + .14, .45, .38, .28, "cardboard")
    box(.25, .02, h + .10, .32, .30, .20, "cardboard")


def _lab_lab_drawers(name, box, legs, white, chrome, dark, front):
    """Parts of lab_drawers."""
    w, d, h = 1.0, .50, .90
    box(0, 0, (h - .025) / 2, w, d, h - .025, "plastic", LAB_WHITE)
    box(0, 0, h - .0125, w, d, .025, "plastic", LAB_WHITE)
    for i in range(4):
        for j in range(5):
            x, z = -w / 2 + (i + .5) * w / 4, .06 + (j + .5) * (h - .10) / 5
            box(x, d / 2 + .006, z, w / 4 - .02, .012, (h - .10) / 5 - .02, "plastic", front)
            box(x, d / 2 + .016, z, .04, .008, .012, "metal", chrome)


def _lab_lab_solder_bench(name, box, legs, white, chrome, dark, front):
    """Parts of lab_solder_bench."""
    w, d = 2.40, .70
    legs(w, d, .88, .05)
    box(0, 0, .895, w, d, .03, "plastic", LAB_WHITE)
    box(-.30, -d / 2 + .01, 1.40, 1.20, .015, .70, "plastic", LAB_WHITE)
    box(-.30, -d / 2 + .06, 1.47, 1.00, .02, .02, "metal", chrome)
    for i, color in enumerate(((.78, .12, .12, 1), (.45, .20, .62, 1), (.90, .72, .15, 1), (.20, .42, .75, 1), (.78, .12, .12, 1))):
        box(-.70 + i * .2, -d / 2 + .06, 1.47, .06, .07, .07, "plastic", color, shape="lathe", axis=0)
    box(-.85, 0, .30, .50, .50, .58, "metal", (.92, .75, .12, 1))
    box(-.85, .252, .42, .10, .004, .10, "paper", (.95, .95, .92, 1))
    box(.15, -.10, .96, .25, .18, .10, "plastic", (.20, .22, .24, 1))
    box(.32, -.12, 1.0, .03, .03, .18, "metal", chrome, shape="lathe")
    for x in (.60, 1.00):
        box(x, -.18, .925, .12, .12, .03, "metal", LAB_GREY, shape="lathe")
        box(x, -.18, 1.16, .015, .015, .44, "metal", LAB_GREY, shape="lathe")
        box(x, -.10, 1.38, .17, .02, .17, "metal", (.85, .86, .86, 1), shape="lathe", axis=1, profile=[[1, -.5], [1, .5]])
    box(-1.00, .05, .99, .30, .30, .16, "plastic", (.18, .55, .30, 1))


def _lab_lab_tv(name, box, legs, white, chrome, dark, front):
    """Parts of lab_tv."""
    box(0, 0, 1.575, 2.0, .06, 1.15, "screen")
    box(0, -.045, 1.575, .40, .03, .30, "metal", ROBOT_DARK)


def _lab_lab_cupboard(name, box, legs, white, chrome, dark, front):
    """Parts of lab_cupboard."""
    w, d, h = 1.0, .50, 2.0
    box(0, 0, h / 2, w, d, h, "plastic", LAB_WHITE)
    for x in (-w / 4, w / 4):
        box(x, d / 2 + .008, h / 2 + .01, w / 2 - .012, .016, h - .06, "plastic", front)
    for x in (-.03, .03):
        box(x, d / 2 + .025, 1.05, .015, .018, .22, "metal", chrome)
    for x in (-.24, .24):
        box(x, 0, h + .15, .44, .40, .30, "plastic", (.12, .13, .14, 1))


def _lab_lab_printer(name, box, legs, white, chrome, dark, front):
    """Parts of lab_printer."""
    w, d, h = .80, .80, 1.60
    box(0, 0, .35, w, d, .70, "plastic", LAB_WHITE)
    for x in (-w / 2 + .02, w / 2 - .02):
        for y in (-d / 2 + .02, d / 2 - .02):
            box(x, y, 1.15, .03, .03, .90, "metal", chrome)
    box(0, 0, h - .01, w, d, .02, "metal", chrome)
    box(0, d / 2 - .02, 1.15, w - .06, .01, .86, "glass", (.80, .88, .90, .35))
    box(0, -.05, .88, .50, .45, .30, "metal", ROBOT_DARK)
    box(0, -.03, .75, .40, .40, .04, "plastic", (.78, .12, .12, 1))


def _lab_lab_rolling_drawers(name, box, legs, white, chrome, dark, front):
    """Parts of lab_rolling_drawers."""
    for i, x in enumerate((-.50, 0, .50)):
        box(x, 0, .37, .45, .48, .64, "plastic", LAB_WHITE)
        for z in (.20, .38, .56):
            box(x, .245, z, .38, .012, .015, "metal", ROBOT_DARK)
        for cx in (x - .17, x + .17):
            box(cx, 0, .025, .04, .03, .05, "plastic", ROBOT_DARK, shape="lathe", axis=1)
    box(-.50, -.02, .84, .44, .36, .30, "wood", (.78, .60, .38, 1))
    for z in (.75, .84, .93):
        box(-.50, .162, z, .38, .008, .07, "wood", (.70, .52, .32, 1))


def _lab_lab_mat(name, box, legs, white, chrome, dark, front):
    """Parts of lab_mat."""
    box(0, 0, .006, .90, .90, .012, "plastic", (.78, .12, .14, 1), shape=None)


def _lab_lab_bin(name, box, legs, white, chrome, dark, front):
    """Parts of lab_bin."""
    box(0, 0, .20, .32, .32, .40, "plastic", (.12, .34, .80, 1), shape="lathe", profile=[[.82, -.5], [.86, -.45], [1, .48], [.97, .5]])


LAB_MODELS = {"lab_desk": _lab_lab_desk, "lab_chair": _lab_lab_chair, "lab_pegboard": _lab_lab_pegboard,
              "lab_cabinet": _lab_lab_cabinet, "lab_drawers": _lab_lab_drawers,
              "lab_solder_bench": _lab_lab_solder_bench, "lab_tv": _lab_lab_tv, "lab_cupboard": _lab_lab_cupboard,
              "lab_printer": _lab_lab_printer, "lab_rolling_drawers": _lab_lab_rolling_drawers,
              "lab_mat": _lab_lab_mat, "lab_bin": _lab_lab_bin}


def _lab(name, box, legs, white, chrome, dark):
    """Front +y, back -y against the wall."""
    front = (.97, .97, .96, 1)
    if name in LAB_MODELS:
        LAB_MODELS[name](name, box, legs, white, chrome, dark, front)


# Aseptic laboratory (5 labs in 6; Lab D66 is the sixth): white, light grey, one cyan accent.
ASEPTIC = ("lab_bench", "lab_white_desk", "lab_task_chair", "fume_hood", "test_tube_rack", "beaker", "flask", "reagent_bottle")
ASEPTIC_WHITE, ASEPTIC_GREY, ASEPTIC_CYAN = (.93, .94, .94, 1), (.78, .80, .81, 1), (.22, .64, .72, 1)
GLASS, LIQUIDS = (.80, .90, .92, .45), ((.30, .62, .78, 1), (.86, .62, .20, 1), (.45, .72, .40, 1))
BOTTLE = [[.68, -.5], [.9, -.44], [1, -.25], [1, .22], [.72, .4], [.6, .5]]


def _aseptic_lab_bench(name, box, legs, white, chrome, dark, front):
    """Parts of lab_bench."""
    w, d = 1.80, .75
    box(0, -.02, .02, w - .06, d - .12, .04, "plastic", (.40, .42, .43, 1))
    box(0, -.01, .45, w - .02, d - .08, .78, "plastic", ASEPTIC_WHITE)
    for x in (-.6, 0, .6):
        box(x, d / 2 - .035, .46, .58, .02, .70, "plastic", front)
        box(x + .22, d / 2 - .019, .70, .02, .012, .14, "metal", chrome)
    box(0, 0, .87, w, d, .04, "plastic", ASEPTIC_GREY)
    for x in (-w / 2 + .05, w / 2 - .05):
        box(x, -d / 2 + .06, 1.21, .03, .04, .64, "metal", chrome)
    for z in (1.25, 1.52):
        box(0, -d / 2 + .12, z, w - .04, .22, .02, "plastic", ASEPTIC_WHITE)
    for i, x in enumerate((-.72, -.60, -.40, .18, .40, .58, .70)):
        box(x, -d / 2 + .12, 1.31, .06, .06, .10, "glass", (LIQUIDS[i % 3][:3]) + (.85,), shape="lathe", profile=BOTTLE)


def _aseptic_lab_white_desk(name, box, legs, white, chrome, dark, front):
    """Parts of lab_white_desk."""
    w, d, h = 1.40, .70, .75
    legs(w, d, h - .04, .045)
    box(0, 0, h - .02, w, d, .04, "plastic", ASEPTIC_WHITE)
    px = -w / 2 + .22
    box(px, -.01, .37, .40, .58, .64, "plastic", ASEPTIC_WHITE)
    for z in (.18, .38, .58):
        box(px, .285, z, .37, .02, .17, "plastic", front)
        box(px, .298, z + .05, .14, .012, .015, "plastic", ASEPTIC_CYAN)
    box(.12, -.19, h + .31, .50, .05, .30, "screen")
    box(.12, -.235, h + .09, .05, .035, .16, "metal", chrome)
    box(.12, -.17, h + .01, .22, .16, .02, "metal", chrome)
    box(.12, .12, h + .012, .42, .14, .02, "plastic", (.86, .87, .87, 1))


def _aseptic_lab_task_chair(name, box, legs, white, chrome, dark, front):
    """Parts of lab_task_chair."""
    for w, d in ((.56, .05), (.05, .56)):
        box(0, 0, .075, w, d, .035, "plastic", ASEPTIC_GREY)
    for x, y in ((-.255, 0), (.255, 0), (0, -.255), (0, .255)):
        box(x, y, .03, .05, .03, .05, "plastic", dark, shape="lathe", axis=1)
    box(0, 0, .25, .055, .055, .30, "metal", chrome, shape="lathe")
    box(0, 0, .42, .48, .46, .05, "plastic", ASEPTIC_WHITE)
    box(0, .01, .48, .46, .44, .07, "fabric", ASEPTIC_CYAN)
    box(0, -.22, .62, .05, .03, .30, "metal", chrome)
    box(0, -.24, .86, .44, .04, .38, "plastic", ASEPTIC_WHITE)
    box(0, -.21, .86, .40, .03, .32, "fabric", ASEPTIC_CYAN)


def _aseptic_fume_hood(name, box, legs, white, chrome, dark, front):
    """Parts of fume_hood."""
    w, d = 1.20, .80
    box(0, 0, .44, w, d - .04, .80, "plastic", ASEPTIC_WHITE)
    box(0, d / 2 - .03, .44, w - .06, .02, .66, "plastic", front)
    box(0, 0, .87, w, d, .04, "plastic", ASEPTIC_GREY)
    for x in (-w / 2 + .03, w / 2 - .03):
        box(x, 0, 1.55, .06, d, 1.32, "plastic", ASEPTIC_WHITE)
    box(0, -d / 2 + .03, 1.55, w - .12, .04, 1.32, "plastic", (.85, .87, .87, 1))
    box(0, 0, 2.28, w, d, .14, "plastic", ASEPTIC_WHITE)
    box(0, d / 2 - .04, 1.93, w - .12, .02, .44, "glass", GLASS)
    box(0, d / 2 - .04, 1.69, w - .12, .04, .04, "metal", chrome)
    box(0, d / 2 - .015, 2.25, w - .30, .02, .05, "plastic", ASEPTIC_CYAN)


def _aseptic_test_tube_rack(name, box, legs, white, chrome, dark, front):
    """Parts of test_tube_rack."""
    box(0, 0, .005, .20, .08, .01, "plastic", ASEPTIC_WHITE)
    box(0, 0, .07, .20, .08, .008, "plastic", ASEPTIC_WHITE)
    for x in (-.095, .095):
        box(x, 0, .04, .01, .08, .07, "plastic", ASEPTIC_WHITE)
    for i in range(5):
        x = -.072 + i * .036
        box(x, 0, .0325, .016, .016, .045, "plastic", LIQUIDS[i % 3], shape="lathe", profile=[[.8, -.5], [1, -.3], [1, .5]])
        box(x, 0, .0875, .016, .016, .065, "glass", GLASS, shape="lathe", profile=[[1, -.5], [1, .5]])


def _aseptic_beaker(name, box, legs, white, chrome, dark, front):
    """Parts of beaker."""
    box(0, 0, .025, .085, .085, .05, "plastic", LIQUIDS[0], shape="lathe", profile=[[.95, -.5], [1, -.4], [1, .5]])
    box(0, 0, .085, .085, .085, .07, "glass", GLASS, shape="lathe", profile=[[1, -.5], [1, .42], [1.0, .5]])


def _aseptic_flask(name, box, legs, white, chrome, dark, front):
    """Parts of flask."""
    box(0, 0, .04, .12, .12, .08, "plastic", LIQUIDS[1], shape="lathe", profile=[[1, -.5], [1, -.42], [.62, .5]])
    box(0, 0, .135, .075, .075, .11, "glass", GLASS, shape="lathe", profile=[[1, -.5], [.4, .1], [.4, .5]])


def _aseptic_reagent_bottle(name, box, legs, white, chrome, dark, front):
    """Parts of reagent_bottle."""
    box(0, 0, .08, .07, .07, .16, "glass", (.55, .33, .14, .9), shape="lathe", profile=BOTTLE)
    box(0, 0, .175, .035, .035, .03, "plastic", white, shape="lathe")


ASEPTIC_MODELS = {"lab_bench": _aseptic_lab_bench, "lab_white_desk": _aseptic_lab_white_desk,
                  "lab_task_chair": _aseptic_lab_task_chair, "fume_hood": _aseptic_fume_hood,
                  "test_tube_rack": _aseptic_test_tube_rack, "beaker": _aseptic_beaker, "flask": _aseptic_flask,
                  "reagent_bottle": _aseptic_reagent_bottle}


def _aseptic(name, box, legs, white, chrome, dark):
    """Front +y, back -y against the wall. Glassware: liquid-coloured lower part + clear upper part,
    so renderers without blending still show the liquid."""
    front = (.97, .97, .97, 1)
    if name in ASEPTIC_MODELS:
        ASEPTIC_MODELS[name](name, box, legs, white, chrome, dark, front)
