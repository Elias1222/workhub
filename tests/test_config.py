"""配置层：数据目录、合并逻辑、模板完整性。"""
import unittest

from workhub import config

VALID_TARGETS = {"codex", "workbuddy", "dsh", "kimi", "muse", "kimiweb"}


class TestConfig(unittest.TestCase):
    def test_data_dir_exists_and_is_overridable(self):
        self.assertTrue(config.DATA_DIR.exists())
        self.assertTrue(config.LOG_DIR.exists())
        self.assertIn("workhub-test-data-", str(config.DATA_DIR))

    def test_deep_merge_keeps_untouched_keys(self):
        base = {"a": 1, "nested": {"x": 1, "y": 2}}
        merged = config._deep_merge(base, {"nested": {"y": 9}})
        self.assertEqual(merged["a"], 1)
        self.assertEqual(merged["nested"], {"x": 1, "y": 9})
        self.assertEqual(base["nested"]["y"], 2, "不能改到原字典")

    def test_defaults_cover_every_target(self):
        for key in ("codex", "workbuddy", "kimi", "muse", "dsh", "out"):
            self.assertIn(key, config.CFG)
        self.assertIsInstance(config.CFG["port"], int)

    def test_templates_are_wellformed(self):
        ids = set()
        for tpl in config.TEMPLATES:
            self.assertTrue(tpl.get("targets"), f"{tpl.get('id')} 至少要有目标")
            self.assertNotIn(tpl["id"], ids, "模板 id 不能重复")
            ids.add(tpl["id"])
            for target in tpl["targets"]:
                self.assertIn(target, VALID_TARGETS)

    def test_out_root_inside_data_dir(self):
        self.assertTrue(str(config.OUT_ROOT).startswith(str(config.DATA_DIR)))


if __name__ == "__main__":
    unittest.main()
