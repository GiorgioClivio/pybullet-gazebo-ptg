"""Visual-only X-ray for every body PTG loaded; any host simulator can reuse it.

Only visual RGBA changes: collision shapes, filters and ray results stay the same. Bodies not
in body_ids (a robot, sensors) keep their colours, so they are the only opaque objects left.
"""
import pybullet as p

from styles import COLORS

TINTS = ((.28, .60, .95), (.30, .80, .48), (.95, .57, .25))  # Storey 0 / 1 / 2+ (roof uses the last).
# Translucent alpha per box kind; furniture, landmarks and props are see-through too.
ALPHA = {"wall": .12, "ceiling": .08, "floor": .20, "glass": .08, "trim": .25, "stairs": .35,
         "furniture": .22, "landmark": .15, "prop": .22, "other": .25,
         # room_styles finishes: skins read like the wall they cover, frames like trim.
         "wall_finish": .12, "frame": .25, "fixture": .22}


def loaded_color(box):
    """The RGBA load_pybullet assigns to a box (before any cutaway)."""
    return list(box.get("color", COLORS[box["material"]]))


def xray_color(box, alpha=None):
    """X-ray RGBA of one scene box.

    alpha: None for ALPHA, a float for every kind, or a {kind: alpha} dict; kinds missing from
    the dict use its "other" entry, else 0 (hidden).
    Renderers without blending (e.g. alpha<1 drawn opaque, alpha 0 discarded) should pass
    alpha 0 for what must vanish and 1 for what stays, e.g. {"floor": 1, "stairs": 1} hides
    walls, ceilings, glass, trim and every object.
    """
    alpha = ALPHA if alpha is None else alpha
    tint = TINTS[min(box["level"], 2)]
    # Architecture takes the storey tint; objects blend it with their own colour to stay legible.
    rgb = tint if "object_id" not in box else [(a + b) / 2 for a, b in zip(tint, loaded_color(box))]
    return [*rgb, alpha if isinstance(alpha, (int, float)) else alpha.get(box["kind"], alpha.get("other", 0.))]


class XRay:
    """Toggle see-through colours on scene["boxes"]-aligned body_ids and restore the loaded ones."""

    def __init__(self, scene, body_ids, client=0, alpha=None, on=False):
        self.boxes, self.bodies, self.client, self.alpha = scene["boxes"], list(body_ids), client, alpha
        visuals = getattr(body_ids, "visuals", None)  # fastload ids: recolour the merged meshes
        if visuals:
            # A group shares storey, kind and colour, so its first part stands for all of them.
            self.boxes = [scene["boxes"][v["boxes"][0]] for v in visuals]
            self.bodies = [v["body"] for v in visuals]
        self.on = on
        if on:
            self.apply()

    def colors(self):
        """Target RGBA per body for the current state, without applying them."""
        return [xray_color(b, self.alpha) if self.on else loaded_color(b) for b in self.boxes]

    def apply(self, colors=None):
        """Push colors (default: self.colors()) with rendering paused, as one visual update."""
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 0, physicsClientId=self.client)
        for body, color in zip(self.bodies, colors or self.colors()):
            p.changeVisualShape(body, -1, rgbaColor=color, physicsClientId=self.client)
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 1, physicsClientId=self.client)

    def toggle(self):
        self.on = not self.on
        self.apply()
        return self.on

    def restore(self):
        """Exact colours from load_pybullet (without its view_floor cutaway)."""
        self.on = False
        self.apply()
