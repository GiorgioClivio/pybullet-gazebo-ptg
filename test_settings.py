"""config/ settings: defaults, partial overrides, validation and their effect on generated scenes."""
import os
import tempfile
import unittest
from pathlib import Path

import settings
from indoor import Config, generate


WRITTEN = []


def override(text):
    """A one-file override written to a temporary .toml; returns its path."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
    handle.write(text)
    handle.close()
    WRITTEN.append(handle.name)
    return handle.name


class SettingsTests(unittest.TestCase):
    def tearDown(self):
        settings.use(None)
        while WRITTEN:
            os.remove(WRITTEN.pop())

    def test_defaults_are_valid_and_unrecorded(self):
        s = settings.use(None)
        self.assertEqual(Config().seed, s["building"]["seed"])
        self.assertNotIn("settings", generate(Config(seed=7, furnished=False, details=False)))

    def test_partial_override_merges(self):
        s = settings.use(override('[furniture.groups]\noffice = [["desk"]]\n[building]\nrooms = 8\n'))
        self.assertEqual(s["furniture"]["groups"]["office"], [["desk"]])
        self.assertIn("living", s["furniture"]["groups"])  # the other purposes are kept
        self.assertEqual(Config().rooms, 8)
        self.assertEqual(Config(rooms=10).rooms, 10)  # explicit arguments win

    def test_errors_name_the_culprit(self):
        with self.assertRaisesRegex(ValueError, "did you mean density"):
            settings.load(override("[furniture]\ndensty = 2\n"))
        with self.assertRaisesRegex(ValueError, "unknown object kind 'sofaa'"):
            settings.load(override('[furniture.groups]\nliving = [["sofaa"]]\n'))
        with self.assertRaisesRegex(ValueError, "has no \\[furniture.groups\\]"):
            settings.load(override('[rooms]\npurposes = ["gym"]\n'))
        with self.assertRaisesRegex(ValueError, "not a list of"):
            settings.load(override('[furniture.groups]\nliving = [[["sofa"]]]\n'))

    def test_disabled_density_and_signature(self):
        base = generate(Config(seed=3, floors=2))
        settings.use(override('[furniture]\ndisabled = ["plant", "small_plant"]\ndensity = 2.0\n'))
        scene = generate(Config(seed=3, floors=2))
        kinds = {b.get("label") for b in scene["boxes"]}
        self.assertFalse(kinds & {"plant", "small_plant"})
        self.assertGreater(len(scene["objects"]), len(base["objects"]))
        self.assertEqual(len(scene["settings"]["sha256"]), 64)
        self.assertEqual([s["rect"] for s in scene["spaces"]], [s["rect"] for s in base["spaces"]])  # same layout

    def test_folder_override(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "rooms.toml").write_text('[rooms.labs]\nprobability = 0.0\n')
            settings.use(folder)
            for seed in range(5):
                self.assertFalse(any(s.get("purpose") == "lab" for s in generate(Config(seed=seed, floors=3))["spaces"]))


if __name__ == "__main__":
    unittest.main()
