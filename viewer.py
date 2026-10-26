"""Orbit/X-ray inspection and a gravity-driven, colliding first-person camera.

T toggles X-ray (xray.py). X and Z stay free: host simulators often bind them to camera zoom, and PyBullet's
default shortcuts own a c d g i j k l o p s v w (disabled here, but maybe not in a host simulation).
"""
import math
import atexit
import ctypes
import os
import sys
from functools import cache

import pybullet as p

from xray import XRay

XRAY_KEY = ord("t")  # "translucent"; hosts can bind the same key.


@cache
def _x11_keyboard():
    """PyBullet's X11 backend reports Tab as -1; identify the actual native key."""
    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        return None
    try:
        x = ctypes.CDLL("libX11.so.6")
        x.XOpenDisplay.argtypes, x.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        display = x.XOpenDisplay(None)
        if display:
            atexit.register(x.XCloseDisplay, display)
            return x, display, x.XKeysymToKeycode(display, 0xFF09), ctypes.create_string_buffer(32)
    except OSError:
        pass
    return None


def tab_pressed(keys):
    """True when Tab was pressed since the last poll (PyBullet keys, else the X11 keyboard)."""
    if keys.get(9, 0) & p.KEY_WAS_TRIGGERED:
        return True
    if keys.get(-1, 0) & p.KEY_WAS_TRIGGERED:
        native = _x11_keyboard()
        if native:
            x, display, key, state = native
            x.XQueryKeymap(display, state)
            return bool(state.raw[key // 8] & (1 << (key % 8)))
    return False


class Walker:
    radius, height, eye_height, step_height = .22, 1.75, 1.60, .18

    def __init__(self, client, feet):
        self.client, self.feet, self.velocity_z = client, list(feet), 0.
        shape = p.createCollisionShape(p.GEOM_CAPSULE, radius=self.radius,
            height=self.height - 2 * self.radius, physicsClientId=client)
        self.body = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=shape,
            basePosition=[*feet[:2], feet[2] + self.height / 2], physicsClientId=client)
        p.changeVisualShape(self.body, -1, rgbaColor=[0, 0, 0, 0], physicsClientId=client)
        # Query-only capsule: do not alter the building, robots or sensor ray results.
        p.setCollisionFilterGroupMask(self.body, -1, 0, 0, physicsClientId=client)

    def _clear(self, feet):
        center = [*feet[:2], feet[2] + self.height / 2]
        p.resetBasePositionAndOrientation(self.body, center, [0, 0, 0, 1], physicsClientId=self.client)
        aabb = p.getAABB(self.body, physicsClientId=self.client)
        for body, link in p.getOverlappingObjects(*aabb, physicsClientId=self.client) or ():
            if body != self.body and p.getClosestPoints(self.body, body, -.001,
                    linkIndexB=link, physicsClientId=self.client):
                return False
        return True

    def _support(self, xy, low, high):
        # Sample the capsule footprint, not just its centre, at tread/landing edges.
        r = self.radius
        points = [(xy[0] + dx, xy[1] + dy) for dx, dy in
                  ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r))]
        hits = p.rayTestBatch([[x, y, high] for x, y in points],
                             [[x, y, low] for x, y in points], physicsClientId=self.client)
        return max((h[3][2] for h in hits if h[0] >= 0 and h[4][2] > .5), default=None)

    def move(self, dx, dy, dt):
        # Short sweeps prevent tunnelling through thin walls, even with a slow GUI.
        count = max(1, math.ceil(math.hypot(dx, dy) / .035), math.ceil(dt / (1 / 120)))
        for _ in range(count):
            grounded = self._support(self.feet, self.feet[2] - .015, self.feet[2] + .015) is not None
            for axis, delta in enumerate((dx / count, dy / count)):
                if not delta:
                    continue
                candidate = self.feet[:]
                candidate[axis] += delta
                floor = self._support(candidate, self.feet[2] - .015,
                                      self.feet[2] + self.step_height + .005) if grounded else None
                if floor is not None and floor > candidate[2] + .001:
                    raised = [*self.feet[:2], floor + .002]
                    candidate[2] = floor + .002
                    if not self._clear(raised):
                        continue
                if self._clear(candidate):
                    self.feet = candidate
            duration = dt / count
            self.velocity_z -= 9.81 * duration
            next_z = self.feet[2] + self.velocity_z * duration
            floor = self._support(self.feet, next_z - .005, self.feet[2] + .005)
            if floor is not None and self.velocity_z <= 0:
                self.feet[2], self.velocity_z = floor + .002, 0.
            elif self._clear([*self.feet[:2], next_z]):
                self.feet[2] = next_z
            else:
                self.velocity_z = 0.
        self._clear(self.feet)


class Viewer:
    def __init__(self, scene, bodies, client=0, view_floor=None, xray=False, minimap=None):
        """minimap: optional minimap.Minimap; it receives the walker pose in walk mode only
        (an orbit camera target floats between storeys, so the arrow keeps the last walk pose)."""
        self.scene, self.bodies, self.client, self.minimap = scene, bodies, client, minimap
        self.view_floor, self.xray, self.walker = view_floor, XRay(scene, bodies, client), None
        self.xray.on = xray  # Applied once by _visibility below, together with the cutaway.
        self.walking, self.yaw, self.pitch = False, 0., 0.
        self.mouse, self.dragging, self.orbit = None, False, None
        if p.getConnectionInfo(physicsClientId=client)["connectionMethod"] == p.GUI:
            _x11_keyboard()
        # Reserve Tab/T/WASD instead of the debug GUI's built-in shortcuts.
        p.configureDebugVisualizer(p.COV_ENABLE_KEYBOARD_SHORTCUTS, 0, physicsClientId=client)
        self._visibility()

    def _visibility(self):
        colors = self.xray.colors()
        if not self.walking and self.view_floor is not None:
            for color, box in zip(colors, self.scene["boxes"]):
                if box["level"] > self.view_floor:
                    color[3] = 0.
        self.xray.apply(colors)

    def toggle_walk(self):
        if not self.walking:
            camera = p.getDebugVisualizerCamera(physicsClientId=self.client)
            self.orbit = camera[10], camera[8], camera[9], camera[11]
            if self.walker is None:
                self.walker = Walker(self.client, [*self.scene["spawn"][:2], .002])
                exits = [e["center"] for e in self.scene["portals"] if 0 in e["rooms"]]
                if exits:
                    target = min(exits, key=lambda v: math.dist(v[:2], self.walker.feet[:2]))
                    dx, dy = (target[i] - self.walker.feet[i] for i in (0, 1))
                    self.yaw = math.degrees(math.atan2(-dx, dy))
                self.pitch = -8.
            self.walking = True
        else:
            self.walking = False
            p.resetDebugVisualizerCamera(*self.orbit, physicsClientId=self.client)
        self.mouse, self.dragging = None, False
        p.configureDebugVisualizer(p.COV_ENABLE_MOUSE_PICKING, int(not self.walking), physicsClientId=self.client)
        self._visibility()
        if self.walking:
            self._camera()

    def _camera(self):
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        direction = [-math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)]
        eye = [*self.walker.feet[:2], self.walker.feet[2] + self.walker.eye_height]
        target = [v + .1 * d for v, d in zip(eye, direction)]
        p.resetDebugVisualizerCamera(.1, self.yaw, self.pitch, target, physicsClientId=self.client)

    def update(self, dt, keys=None, mouse=None):
        keys = p.getKeyboardEvents(physicsClientId=self.client) if keys is None else keys
        mouse = p.getMouseEvents(physicsClientId=self.client) if mouse is None else mouse
        if tab_pressed(keys):
            self.toggle_walk()
        if keys.get(XRAY_KEY, 0) & p.KEY_WAS_TRIGGERED:
            self.xray.on = not self.xray.on
            self._visibility()
        for key in range(4):
            if keys.get(ord(str(key)), 0) & p.KEY_WAS_TRIGGERED and key <= self.scene["config"]["floors"]:
                self.view_floor = key - 1 if key else None
                self._visibility()
        if not self.walking:
            return
        down = lambda key: bool(keys.get(key, 0) & p.KEY_IS_DOWN)
        self.yaw += (down(p.B3G_LEFT_ARROW) - down(p.B3G_RIGHT_ARROW)) * 90 * dt
        self.pitch += (down(p.B3G_UP_ARROW) - down(p.B3G_DOWN_ARROW)) * 75 * dt
        for event, x, y, button, state in mouse:
            if event == 2 and button == 2:
                self.dragging = bool(state & p.KEY_IS_DOWN)
            if self.dragging and self.mouse is not None and event == 1:
                self.yaw -= (x - self.mouse[0]) * .18
                self.pitch -= (y - self.mouse[1]) * .18
            self.mouse = x, y
        self.pitch = max(-80., min(80., self.pitch))
        forward, right = down(ord("w")) - down(ord("s")), down(ord("d")) - down(ord("a"))
        magnitude = max(1., math.hypot(forward, right))
        yaw, speed = math.radians(self.yaw), 1.4 * dt / magnitude
        self.walker.move((-math.sin(yaw) * forward + math.cos(yaw) * right) * speed,
                         (math.cos(yaw) * forward + math.sin(yaw) * right) * speed, dt)
        self._camera()
        if self.minimap:
            # Camera yaw 0 looks along +y; the minimap takes the usual heading (0 = +x, CCW).
            self.minimap.update(*self.walker.feet, math.radians(self.yaw + 90))
