"""Self-check: dependencies import, a building and a metro station generate, PyBullet loads them.

    python3 selfcheck.py        # about a minute; prints one line per check and exits non-zero on failure
"""
import sys
import time
import unittest


def main():
    """Run the installation checks; return 0 when every check passes."""
    start = time.perf_counter()
    import PIL
    import pybullet as p
    print(f"Python {sys.version.split()[0]}, Pillow {PIL.__version__}, PyBullet API {p.getAPIVersion()}")
    from indoor import Config, generate
    from metro import MetroConfig, generate_metro
    from fastload import load_pybullet_merged
    for name, scene in (("building seed 7, 2 storeys", generate(Config(seed=7, floors=2))),
                        ("metro seed 7", generate_metro(MetroConfig(seed=7)))):
        client = p.connect(p.DIRECT)
        try:
            ids = load_pybullet_merged(scene, client)
            assert len(ids) == len(scene["boxes"])
        finally:
            p.disconnect(client)
        print(f"ok  {name}: {len(scene['boxes'])} parts, {len(ids.visuals)} merged meshes")
    suite = unittest.defaultTestLoader.loadTestsFromNames(["test_zfight", "test_minimap", "test_settings"])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    print(f"{'ok' if result.wasSuccessful() else 'FAILED'}  self-check in {time.perf_counter() - start:.0f} s")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
