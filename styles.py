"""Shared visual language; environment profiles are independent of layout/backends."""
import random


PROFILE = dict(id="apartment_office", version=2, units="metres",
               finish="restrained_semirealistic", radial_segments=12,
               wall_finish="monochrome_plaster", floor_finishes=["tile", "planks"])

# Albedo tints. Material images are neutral; only printed content has baked colour.
COLORS = dict(wall=[.86, .84, .79, 1], floor=[.67, .65, .60, 1],
              stairs=[.56, .56, .53, 1], trim=[.29, .30, .29, 1],
              glass=[.72, .79, .80, .32], wood=[.57, .43, .29, 1],
              metal=[.23, .25, .26, 1], fabric=[.43, .46, .45, 1],
              leaf=[.24, .34, .22, 1], ceramic=[.68, .65, .59, 1],
              screen=[1, 1, 1, 1], paper=[.88, .86, .80, 1],
              plastic=[.49, .50, .48, 1], cardboard=[.57, .46, .33, 1])
PALETTE = [(.38, .44, .47, 1), (.43, .46, .36, 1), (.56, .46, .39, 1),
           (.59, .56, .49, 1), (.29, .31, .32, 1), (.52, .52, .49, 1)]
MATERIAL_STYLES = dict(wood="grain", fabric="weave", cardboard="cardboard", screen="screen")


def material_spec(material, seed):
    return dict(style=MATERIAL_STYLES.get(material, "paint"), seed=seed, period=.6, label="")


def building_finishes(seed):
    """Seeded wall, tile and plank colours shared by one building."""
    rng = random.Random(f"{seed}:building_finishes")
    return dict(wall=[*rng.choice(((.88, .86, .81), (.85, .85, .82), (.86, .84, .80))), 1],
                tile=[.69, .68, .64, 1], planks=[.60, .46, .31, 1])
