import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from pawlib import config


def _sample_profile():
    return {
        "provider": "tencent",
        "region": "ap-guangzhou",
        "bucket": "imgs-1250000000",
        "public_base_url": "https://img.example.com",
    }


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        data = {"default_profile": None, "profiles": {}}
        config.set_profile(data, "main", _sample_profile())
        saved = config.save_config(data, self.path)
        loaded = config.load_config(saved)
        profile = config.get_profile(loaded)
        self.assertEqual(profile["bucket"], "imgs-1250000000")
        self.assertEqual(profile["_name"], "main")
        # 默认值合并
        self.assertEqual(profile["key_prefix"], "i/")
        self.assertEqual(profile["max_size_mb"], 25)

    def test_first_profile_becomes_default(self):
        data = {"default_profile": None, "profiles": {}}
        config.set_profile(data, "a", _sample_profile())
        self.assertEqual(data["default_profile"], "a")

    def test_unknown_profile_raises(self):
        data = {"default_profile": None, "profiles": {}}
        config.set_profile(data, "a", _sample_profile())
        with self.assertRaises(config.ConfigError):
            config.get_profile(data, "nope")

    def test_no_profile_raises(self):
        with self.assertRaises(config.ConfigError):
            config.get_profile({"default_profile": None, "profiles": {}})

    def test_missing_file_returns_empty(self):
        data = config.load_config(os.path.join(self.tmp.name, "absent.json"))
        self.assertEqual(data["profiles"], {})

    def test_broken_json_raises(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        with self.assertRaises(config.ConfigError):
            config.load_config(self.path)

    def test_file_permissions_tightened(self):
        if os.name == "nt":
            self.skipTest("Windows 无 POSIX 权限位")
        config.save_config({"profiles": {}}, self.path)
        mode = os.stat(self.path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_set_profile_strips_unknown_fields(self):
        data = {"default_profile": None, "profiles": {}}
        p = _sample_profile()
        p["access_key"] = "SHOULD_NOT_BE_WRITTEN_BY_WIZARD"
        p["evil"] = 1
        config.set_profile(data, "main", p)
        with open(self.path, "w") as f:
            json.dump(data, f)
        self.assertNotIn("access_key", data["profiles"]["main"])
        self.assertNotIn("evil", data["profiles"]["main"])


if __name__ == "__main__":
    unittest.main()
