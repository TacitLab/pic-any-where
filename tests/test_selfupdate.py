"""self-update 测试：用临时 git 仓库模拟 origin，验证拉取与安全约束。"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from pawlib import selfupdate


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args],
                   check=True, capture_output=True, text=True)


def commit_file(repo, name, content):
    with open(os.path.join(repo, name), "w") as f:
        f.write(content)
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-m", f"add {name}")


class SelfUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # origin：裸仓库；work：用户安装副本
        self.origin = os.path.join(self.tmp.name, "origin.git")
        self.work = os.path.join(self.tmp.name, "work")
        seed = os.path.join(self.tmp.name, "seed")
        git(self.tmp.name, "init", "--bare", self.origin)
        git(self.tmp.name, "clone", self.origin, seed)
        commit_file(seed, "SKILL.md", "v1\n")
        git(seed, "push", "origin", "HEAD")
        git(self.tmp.name, "clone", self.origin, self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def _push_new_commit(self):
        seed = os.path.join(self.tmp.name, "seed")
        commit_file(seed, "NEW.md", "v2\n")
        git(seed, "push", "origin", "HEAD")

    def test_pulls_latest_commit(self):
        self._push_new_commit()
        updated, summary = selfupdate.self_update(self.work)
        self.assertTrue(updated)
        self.assertIn("NEW.md", summary)
        self.assertTrue(os.path.exists(os.path.join(self.work, "NEW.md")))

    def test_already_up_to_date(self):
        updated, summary = selfupdate.self_update(self.work)
        self.assertFalse(updated)
        self.assertIn("已是最新", summary)

    def test_dirty_tree_rejected(self):
        with open(os.path.join(self.work, "LOCAL.md"), "w") as f:
            f.write("local edit\n")
        self._push_new_commit()
        with self.assertRaises(selfupdate.UpdateError) as ctx:
            selfupdate.self_update(self.work)
        self.assertIn("本地改动", str(ctx.exception))
        # 未拉到新提交
        self.assertFalse(os.path.exists(os.path.join(self.work, "NEW.md")))

    def test_not_a_git_repo(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        with self.assertRaises(selfupdate.UpdateError) as ctx:
            selfupdate.self_update(plain)
        self.assertIn("git clone", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
