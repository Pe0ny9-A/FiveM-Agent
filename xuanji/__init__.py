"""玄玑 · FiveM 智能体内核包"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("xuanji-fivem")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"
