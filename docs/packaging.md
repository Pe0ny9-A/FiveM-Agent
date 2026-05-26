# 玄玑 · 发布与分发指南

把玄玑作为 Python 包分发的两种路线：**公开 PyPI**（推荐，0.8.0 起已上线）
与**私有源**（GitHub Packages / devpi / Nexus / Artifactory，团队内网用）。

> 包名是 **`xuanji-fivem`**——`xuanji` 已被别人占了。所有用户侧命令以这个名字为准，
> 但安装后命令行入口仍叫 `xuanji`。

## 0. 前置

每次发布前的固定流水线：

```bash
# 1. 升 version：只动 pyproject.toml 的 version 字段
#    （xuanji/__init__.py::__version__ 已经从 importlib.metadata 动态读，无需手改）

# 2. 三件套全绿
uv run ruff check xuanji/ tests/
uv run mypy xuanji/
uv run pytest

# 3. 出包
rm -rf dist/
uv build
# 产物：dist/xuanji_fivem-<version>-py3-none-any.whl
#       dist/xuanji_fivem-<version>.tar.gz

# 4. 包合规检查
uvx twine check dist/*
```

`uv build` 用 hatchling 后端，wheel 自动打包整个 `xuanji/` 目录——种子知识
（seeds.py 内联）、6 套 builtin 预设（presets.py 内联）、3 个示范 skill / 3 个
示范 hook（resources/）都是 Python 模块或随包资源，天然进 wheel。

## 1. 用户安装路径

无论选哪种源，**用户侧**统一这样装：

```bash
# 方式 A：单独 venv（核心包）
python -m venv ~/.xuanji-venv
~/.xuanji-venv/bin/pip install xuanji-fivem  # Windows: ~/.xuanji-venv/Scripts/pip
~/.xuanji-venv/bin/xuanji init               # 首次配置

# 方式 B：uv tool（推荐，独立环境免冲突）
uv tool install xuanji-fivem
xuanji init

# 方式 C：pipx
pipx install xuanji-fivem
xuanji init

# 启用 LanceDB 向量后端（可选）
pip install 'xuanji-fivem[vector]'
```

首次跑 `xuanji init` 会引导小宝填 API Key、导入 FiveM 种子知识、
做一次连通性测试。装好之后 `xuanji doctor` 应当全绿。

VS Code 插件不再依赖仓库 cwd，python 解释器随便选——只要那个解释器装了
`xuanji-fivem`。

---

## 2. 发布路径

### 选项 A · 公开 PyPI（0.8.0 起在用）

适合：项目对外开源、希望全网用户 `pip install` 即得。

**首次发布**

1. 在 https://pypi.org/manage/account/token/ 创建 token
   - 第一次必须选 **Entire account scope**（包还没存在，无法选窄 scope）
   - 复制 `pypi-AgEI...` 完整 token
2. **包发布后立刻撤销 entire-account token，新建一个仅作用于 `xuanji-fivem` 的窄 token**
   留作以后自动化用

**配置 `~/.pypirc`**（推荐，twine 默认读，零环境变量）

```ini
[distutils]
index-servers = pypi

[pypi]
username = __token__
password = pypi-AgEI...你的窄token...
```

文件权限设 `600`；**绝对不要** commit。

**上传**

```bash
# 已配 .pypirc：
uvx twine upload --disable-progress-bar dist/*

# 或环境变量临时模式：
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-AgEI... \
  uvx twine upload --non-interactive --disable-progress-bar dist/*
```

> **Windows 坑**：twine 在默认 GBK 终端输出 unicode 进度符号会
> `UnicodeEncodeError`。加 `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`
> + `--disable-progress-bar` 双保险。

### 选项 B · GitHub Packages（团队私有）

适合：团队代码已在 GitHub Organization。零运维，按 GitHub 账号鉴权。

**发布**

```bash
# 1. 在 GitHub Org 上创建 Personal Access Token (classic)，
#    勾选 write:packages + read:packages
# 2. 上传（用 twine）
uv pip install twine
TWINE_USERNAME=__token__ TWINE_PASSWORD=ghp_xxx \
  twine upload --repository-url https://maven.pkg.github.com/<ORG>/_/ \
  dist/xuanji-*.whl dist/xuanji-*.tar.gz
```

> GitHub Packages 的 Python registry 仍在预览。如果遇到 endpoint 不稳，
> 退到选项 B 或 C。

**用户安装**

```bash
pip install --extra-index-url \
  https://<USER>:<TOKEN>@pypi.pkg.github.com/<ORG>/simple/ \
  xuanji
```

### 选项 C · devpi（团队自建轻量镜像）

适合：希望自建轻量镜像，能镜像公开 PyPI 当兜底。

**部署 server**

```bash
pip install devpi-server devpi-web
devpi-init
devpi-server --host 0.0.0.0 --port 3141 &
```

**发布**

```bash
pip install devpi-client
devpi use http://devpi.internal:3141
devpi login admin --password=<PASS>
devpi index -c team/dev bases=root/pypi      # 第一次
devpi use team/dev
devpi upload dist/xuanji-*
```

**用户安装**

```bash
pip install --index-url http://devpi.internal:3141/team/dev/+simple/ \
  --trusted-host devpi.internal xuanji
```

### 选项 D · Sonatype Nexus / JFrog Artifactory（已有制品库时）

适合：团队已经在用 Nexus / Artifactory 管 Maven / Docker 制品。直接加一个
PyPI 类型的 hosted repo 即可。

```bash
# pyproject.toml 里配置
# 或 ~/.pypirc：
# [team-pypi]
# repository = https://nexus.internal/repository/pypi-internal/
# username = ...
# password = ...

twine upload -r team-pypi dist/xuanji-*
```

**用户安装**

```bash
pip install --index-url https://nexus.internal/repository/pypi-internal/simple/ \
  xuanji
```

---

## 3. CI 自动化（GitHub Actions 示例）

放 `.github/workflows/release.yml`，tag 触发：

```yaml
name: release
on:
  push:
    tags: ['v*']

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install uv
      - run: uv sync --extra dev
      - run: uv run ruff check xuanji/ tests/
      - run: uv run mypy xuanji/
      - run: uv run pytest
      - run: uv build
      - name: Publish to private index
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_INTERNAL_TOKEN }}
        run: |
          uv pip install twine
          twine upload --repository-url ${{ secrets.PYPI_INTERNAL_URL }} dist/*
```

发布命令：

```bash
git tag v0.5.0
git push origin v0.5.0
```

---

## 4. 排错速查

| 现象 | 检查 |
|---|---|
| 用户装完 `xuanji --help` 提示找不到命令 | venv 没激活，或 `pipx` / `uv tool` 没在 PATH |
| `xuanji ipc` 启动报 `ModuleNotFoundError: xuanji.xxx` | wheel 不全（hatch packages 配置问题）。重新 `uv build` 检查 `python -m zipfile -l dist/xuanji-*.whl` |
| `xuanji doctor` 提示 jieba 缺失 | `pip install xuanji` 没拉齐依赖。换 `pipx install xuanji` 或重建 venv |
| 国内用户装包慢 | 私有源后面挂一个 PyPI 镜像 base（devpi 自带 root/pypi 镜像）|
| `xuanji init` 测连卡住 | profile 配错或 API 端点不通；先 `--skip-test` 落盘，再 `xuanji config test` 单独排查 |

---

## 5. 版本节奏

- **0.x**：每个里程碑后发一版。当前已发版本：
  - 0.1（M0+M1+M2 闭环）/ 0.2（自演化）/ 0.3（M3 全家桶）/ 0.4（FiveM 专精层）
  - 0.5（IPC + VS Code 插件）/ 0.6（异构路由 + MCP 客户端）
  - 0.7（互通四件套）/ 0.8（真 LanceDB + 公开 PyPI 首发）
- **1.0**：M4 完结（工具工厂闭环 + 议会式群英会）才升 1.0
- 版本号只动 `pyproject.toml` 的 `version` 一处——`xuanji/__init__.py::__version__`
  自动从 `importlib.metadata` 读
- breaking change 只在 minor 跳跃发生（0.5 → 0.6）。patch（0.5.1）只修 bug
