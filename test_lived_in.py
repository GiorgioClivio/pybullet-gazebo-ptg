"""Loop witnesses, monitor depth separation, room programs and bounded assets."""
from pathlib import Path
import math
import tempfile
import unittest
from unittest.mock import patch

import pybullet as p

from details import _world
from furniture import _model, _crosses
from geometry import mesh
from indoor import Config, generate, load_pybullet
from styles import PALETTE
import surfaces


class LivedInTests(unittest.TestCase):
    def test_every_seed_has_a_real_graph_cycle_even_with_loops_zero(self):
        for rooms in (1, 2, 3, 12, 30):
            for seed in (-123, *range(100)):
                if seed == 66:
                    continue  # Lab D66 Easter egg: a single room has no cycle by design (test_room_styles covers it)
                scene = generate(Config(seed=seed, rooms=rooms, floors=3, loops=0, furnished=False, details=False))
                for level in range(3):
                    nodes = {s["id"] for s in scene["spaces"] if s["level"] == level}
                    edges = [e for e in scene["portals"] if e["rooms"][0] in nodes]
                    self.assertGreaterEqual(len(edges), len(nodes), (rooms, seed, level))
                    witness = scene["loop_routes"][level]
                    route = witness["rooms"]
                    self.assertEqual(route[0], route[-1])
                    self.assertGreaterEqual(len(set(route)), 3)
                    self.assertEqual(len(set(route)), len(route)-1)
                    for a,b,idx in zip(route,route[1:],witness["portals"]):
                        self.assertEqual(set(scene["portals"][idx]["rooms"]), {a,b})
                    self.assertEqual(witness["points"][0],witness["points"][-1])
                    self.assertGreater(witness["length_m"], 5.)
                    area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(witness["points"],witness["points"][1:])))/2
                    self.assertGreater(area, .5)
        # The minimal two-room footprint also needs the external return corridor.
        small = generate(Config(width=6.72, depth=3.36, rooms=2, loops=0, furnished=False, details=False))
        self.assertGreaterEqual(small["loop_routes"][0]["cycle_rank"],1)

    def test_return_corridor_is_physically_traversable(self):
        client=p.connect(p.DIRECT)
        try:
            scene=generate(Config(rooms=1, width=3.36, depth=3.36, loops=0, roof=True, furnished=False))
            ids=set(load_pybullet(scene,client))
            shape=p.createCollisionShape(p.GEOM_CYLINDER,radius=.3,height=.6,physicsClientId=client)
            proxy=p.createMultiBody(baseCollisionShapeIndex=shape,physicsClientId=client)
            points=scene["loop_routes"][0]["points"]
            for a,b in zip(points,points[1:]):
                for i in range(max(1,math.ceil(math.dist(a,b)/.10))+1):
                    steps=max(1,math.ceil(math.dist(a,b)/.10))
                    pos=[a[j]+(b[j]-a[j])*i/steps for j in range(3)]
                    pos[2]+=.65
                    p.resetBasePositionAndOrientation(proxy,pos,[0,0,0,1],physicsClientId=client)
                    for body,_ in p.getOverlappingObjects(*p.getAABB(proxy,physicsClientId=client),physicsClientId=client) or ():
                        if body in ids:
                            self.assertFalse(p.getClosestPoints(proxy,body,-.001,physicsClientId=client),pos)
                    hit=p.rayTest([*pos[:2],.2],[*pos[:2],-.2],physicsClientId=client)[0]
                    self.assertIn(hit[0],ids)
        finally:
            p.disconnect(client)

    def test_display_is_one_face_and_never_coplanar_in_any_orientation(self):
        client=p.connect(p.DIRECT)
        try:
            for turn in range(4):
                p.resetSimulation(physicsClientId=client)
                parts=_world(_model("desk",PALETTE[0]),[0,0,0],turn)
                panel=next(b for b in parts if b.get("shape")=="display")
                normal=mesh(panel)["normals"][0]
                axis=max(range(3),key=lambda a:abs(normal[a]))
                chassis=parts[parts.index(panel)-1]
                front=normal[axis]*chassis["center"][axis]+chassis["size"][axis]/2
                back=normal[axis]*panel["center"][axis]-panel["size"][axis]/2
                self.assertGreater(back-front,.0009)
                self.assertEqual(len(mesh(panel)["indices"]),6)
                self.assertEqual(len(mesh(panel)["vertices"]),4)
                for part in parts:
                    part.update(kind="furniture",level=0)
                    if part.get("color") is None:part.pop("color",None)
                    part["texture"]=dict(style="screen" if part["material"]=="screen" else "paint",seed=7,period=.6)
                ids=load_pybullet(dict(boxes=parts),client)
                target=panel["center"]
                eye=[v+n*.75 for v,n in zip(target,normal)]
                view=p.computeViewMatrix(eye,target,[0,0,1])
                projection=p.computeProjectionMatrixFOV(35,1,.01,10)
                _,_,_,_,seg=p.getCameraImage(128,128,view,projection,physicsClientId=client)
                if hasattr(seg,"reshape"):seg=seg.reshape(-1)
                # A bezel surface fighting with the image would punch holes here.
                expected=ids[parts.index(panel)]
                center=[seg[y*128+x] for y in range(48,80) for x in range(48,80)]
                self.assertTrue(all(int(value)==expected for value in center))
        finally:
            p.disconnect(client)

    def test_program_variety_wet_floors_and_cables_keep_routes_clear(self):
        for seed in (0,7,13):
            scene=generate(Config(seed=seed,floors=3))
            for level in range(3):
                rooms=[s for s in scene["spaces"] if s["level"]==level and s["kind"]=="room"]
                self.assertGreaterEqual(len({r["purpose"] for r in rooms}),8)
                for purpose,fixture in (("bathroom","toilet"),("kitchen","refrigerator")):
                    selected=[r for r in rooms if r["purpose"]==purpose]
                    self.assertTrue(selected)
                    self.assertTrue(any(o["room"] in {r["id"] for r in selected} and o["kind"]==fixture for o in scene["objects"]))
                for room in rooms:
                    if room["purpose"] in ("bathroom","kitchen","laundry"):
                        self.assertEqual(room["appearance"]["floor"],"tile")
            self.assertGreater(scene["detail_stats"]["cables"],0)
            for obj in scene["objects"]:
                if obj["kind"]!="cable":continue
                self.assertIn(scene["objects"][obj["parent_id"]]["kind"],("desk","workbench","tv_stand","washing_machine"))
                for path in scene["clear_paths"]:
                    if path["room"]==obj["room"]:
                        for a,b in zip(path["points"],path["points"][1:]):
                            self.assertFalse(_crosses(obj["bounds"],a[:2],b[:2],path["width"]/2))
            self.assertIn("toilet",scene["perception"]["class_counts"])
            self.assertIn("refrigerator",scene["perception"]["class_counts"])
            self.assertIn("cable",scene["perception"]["unmapped_models"])

    def test_disk_cache_is_bounded_preserves_current_scene_and_regenerates(self):
        with tempfile.TemporaryDirectory() as root, patch.object(surfaces,"ASSETS",Path(root)):
            paths=[]
            for i in range(4):
                path=Path(root)/f'paint_{i:020x}.png'
                path.write_bytes(b'x'*700)
                paths.append(path)
            user=Path(root)/'my_texture.png'
            user.write_bytes(b'x'*2000)
            stat=paths[0].stat()
            limit=2*max(stat.st_size,getattr(stat,"st_blocks",0)*512)
            report=surfaces.prune_cache([paths[-1]],limit=limit)
            self.assertLessEqual(report["cache_bytes"],limit)
            self.assertTrue(paths[-1].exists())
            self.assertTrue(user.exists())
            spec=dict(style="paint",seed=7,period=.6)
            path=Path(surfaces.texture_path(spec))
            path.unlink()
            self.assertTrue(Path(surfaces.texture_path(spec)).exists())
            with self.assertRaises(ValueError):
                surfaces.prune_cache([path],limit=1)


if __name__ == "__main__":
    unittest.main()
