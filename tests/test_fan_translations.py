from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class SplitControlTranslationTests(unittest.TestCase):
    def test_manifest_version_marks_split_control_feature(self):
        manifest = json.loads(
            (REPO_ROOT / "custom_components" / "air352" / "manifest.json").read_text()
        )
        self.assertEqual(manifest["version"], "5.0.0")

    def test_all_translation_files_define_mode_and_manual_gear_selects(self):
        cases = {
            "strings.json": {
                "names": ("Work mode", "Manual level"),
                "modes": ["Manual", "Auto", "Sleep", "Skin", "Air drying"],
                "gears": [f"Level {level}" for level in range(1, 7)],
            },
            "translations/en.json": {
                "names": ("Work mode", "Manual level"),
                "modes": ["Manual", "Auto", "Sleep", "Skin", "Air drying"],
                "gears": [f"Level {level}" for level in range(1, 7)],
            },
            "translations/zh-Hans.json": {
                "names": ("运行模式", "手动档位"),
                "modes": ["手动", "自动", "睡眠", "Skin", "风干"],
                "gears": [f"{level}档" for level in range(1, 7)],
            },
        }

        for relative_path, expected in cases.items():
            with self.subTest(path=relative_path):
                data = json.loads(
                    (
                        REPO_ROOT
                        / "custom_components"
                        / "air352"
                        / relative_path
                    ).read_text()
                )
                selects = data["entity"]["select"]
                mode = selects["work_mode"]
                gear = selects["manual_gear"]
                self.assertEqual(
                    (mode["name"], gear["name"]), expected["names"]
                )
                self.assertEqual(
                    [
                        mode["state"][option]
                        for option in (
                            "manual",
                            "auto",
                            "sleep",
                            "skin",
                            "air_drying",
                        )
                    ],
                    expected["modes"],
                )
                self.assertEqual(
                    [gear["state"][f"gear_{level}"] for level in range(1, 7)],
                    expected["gears"],
                )

    def test_select_platform_is_forwarded(self):
        source = (
            REPO_ROOT / "custom_components" / "air352" / "__init__.py"
        ).read_text()
        self.assertIn("Platform.SELECT", source)


if __name__ == "__main__":
    unittest.main()
