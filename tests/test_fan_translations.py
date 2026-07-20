from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class FanTranslationTests(unittest.TestCase):
    def test_manifest_version_marks_named_gear_feature(self):
        manifest = json.loads(
            (REPO_ROOT / "custom_components" / "air352" / "manifest.json").read_text()
        )
        self.assertEqual(manifest["version"], "3.0.0")

    def test_all_translation_files_define_named_gears(self):
        cases = {
            "strings.json": [f"Level {level}" for level in range(1, 7)],
            "translations/en.json": [f"Level {level}" for level in range(1, 7)],
            "translations/zh-Hans.json": [f"{level}档" for level in range(1, 7)],
        }

        for relative_path, expected_labels in cases.items():
            with self.subTest(path=relative_path):
                data = json.loads(
                    (
                        REPO_ROOT
                        / "custom_components"
                        / "air352"
                        / relative_path
                    ).read_text()
                )
                states = data["entity"]["fan"]["air_purifier"][
                    "state_attributes"
                ]["preset_mode"]["state"]
                actual_labels = [states[f"gear_{level}"] for level in range(1, 7)]
                self.assertEqual(actual_labels, expected_labels)


if __name__ == "__main__":
    unittest.main()
