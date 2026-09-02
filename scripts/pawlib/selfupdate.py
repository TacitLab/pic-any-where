"""自我更新：从安装来源的 git 仓库拉取最新提交（--ff-only）。"""

import os
import subprocess


class UpdateError(Exception):
    pass


def find_repo_root() -> str:
    """Skill 仓库根目录（pawlib -> scripts -> 根）。"""
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))


def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} 失败：{r.stderr.strip()}")
    return r.stdout.strip()


def self_update(repo=None):
    """执行更新，返回 (是否拉到了新提交, 摘要信息)。

    安全约束：
    - 仅当安装目录是 git 工作副本时可用（否则提示用 git clone 重装）
    - 工作区存在本地改动时拒绝执行，避免覆盖用户修改
    - 只接受 fast-forward（--ff-only），不产生合并提交
    """
    repo = repo or find_repo_root()
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise UpdateError(
            f"{repo} 不是 git 工作副本，无法自动更新。\n"
            "请改用 git clone 方式安装本 Skill 后再试。")

    dirty = _git(repo, "status", "--porcelain")
    if dirty:
        raise UpdateError(
            "安装目录存在未提交的本地改动，已中止更新：\n"
            + "\n".join("  " + line for line in dirty.splitlines()[:10])
            + "\n请先处理这些改动（提交或还原）后重试。")

    before = _git(repo, "rev-parse", "HEAD")
    _git(repo, "pull", "--ff-only")
    after = _git(repo, "rev-parse", "HEAD")

    if before == after:
        return False, f"已是最新（{after[:8]}）"
    log = _git(repo, "log", "--oneline", f"{before}..{after}")
    return True, f"已更新 {before[:8]} → {after[:8]}：\n{log}"
