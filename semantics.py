"""COCO80 class hints for evaluating detectors; these are not detector predictions.

Taxonomy: github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/datasets/coco.yaml
Objects outside this taxonomy deliberately remain unmapped.
"""
from collections import Counter

CLASSES = {"backpack": (24, "backpack"), "suitcase": (28, "suitcase"), "bottle": (39, "bottle"),
    "mug": (41, "cup"), "bowl": (45, "bowl"), "chair": (56, "chair"), "armchair": (56, "chair"),
    "sofa": (57, "couch"), "plant": (58, "potted plant"), "small_plant": (58, "potted plant"),
    "bed": (59, "bed"), "table": (60, "dining table"), "toilet": (61, "toilet"),
    "laptop": (63, "laptop"), "microwave": (68, "microwave"), "oven": (69, "oven"),
    "sink": (71, "sink"), "refrigerator": (72, "refrigerator"), "book_stack": (73, "book"),
    "floor_book": (73, "book"), "magazine": (73, "book"), "wall_clock": (74, "clock"),
    "vase": (75, "vase"), "toothbrush": (79, "toothbrush"),
    # Lab D66 catalogue: a task chair is a COCO chair; desks, the pegboard, cabinets, drawers and
    # bins have no COCO class (COCO "dining table" is not a desk) and stay unmapped.
    "lab_chair": (56, "chair"),
    # Aseptic lab: task chair = chair, reagent bottle = bottle; benches, fume hoods, racks, beakers, flasks unmapped.
    "lab_task_chair": (56, "chair"), "reagent_bottle": (39, "bottle")}


def annotate(scene):
    """Add COCO-80 ids and class names to object items and a per-scene class count."""
    counts, unmapped = Counter(), set()
    for obj in scene.get("objects", ()):
        for item in obj["items"]:
            ident, name = CLASSES.get(item["kind"], (None, None))
            item.update(coco_id=ident, coco_class=name)
            if name:
                counts[name] += 1
            else:
                unmapped.add(item["kind"])
    scene["perception"] = dict(taxonomy="COCO80", source="semantic_ground_truth_only",
                               class_counts=dict(sorted(counts.items())), unmapped_models=sorted(unmapped))
