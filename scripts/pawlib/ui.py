"""终端输出美化：ANSI 颜色 + 状态符号。

只在输出到 TTY 时上色；管道/重定向/NO_COLOR 环境下自动降级为纯文本，保证脚本与 Agent 可解析。
尊重 NO_COLOR 环境变量（https://no-color.org）。
"""

import os
import sys

_CODES = {
    "bold": "1", "dim": "2",
    "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36",
}


def _color_enabled(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return stream.isatty()
    except Exception:
        return False


def enable_windows_ansi():
    """Windows 上启用虚拟终端处理（Win10+ 支持 ANSI 颜色）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)  # STDOUT
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-12), 7)  # STDERR
    except Exception:
        pass


def _wrap(code, text, stream):
    return f"\033[{code}m{text}\033[0m" if _color_enabled(stream) else text


def _emit(msg, stream, code=None, symbol=None):
    text = f"{symbol} {msg}" if symbol else msg
    if code:
        text = _wrap(code, text, stream)
    print(text, file=stream)


def ok(msg, stream=sys.stderr):
    _emit(msg, stream, "32", "✓")


def fail(msg, stream=sys.stderr):
    _emit(msg, stream, "31", "✗")


def warn(msg, stream=sys.stderr):
    _emit(msg, stream, "33", "!")


def info(msg, stream=sys.stderr):
    _emit(msg, stream, "36", "→")


def dim(msg, stream=sys.stderr):
    _emit(msg, stream, "2")


def bold(msg, stream=sys.stderr):
    _emit(msg, stream, "1")


def header(title, stream=sys.stderr):
    """打印分节标题，如「== 标题 ==」。"""
    _emit(f"== {title} ==", stream, "1")


def paint(code, text, stream=sys.stderr):
    """对子串着色（仅 TTY 生效），用于行内强调。"""
    return _wrap(_CODES.get(code, code), text, stream)


def url_out(msg):
    """结果输出走 stdout 且永远不着色，保证管道/重定向时可解析。"""
    print(msg)
