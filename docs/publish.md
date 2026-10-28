# 发布

仓库已经发布到 <https://github.com/Elias1222/workhub>：`main` 分支、`v1.1.0` → `v1.4.0` 的标签、
Release 都在，remote `origin` 指向 `https://github.com/Elias1222/workhub.git`。

## 发一个新版本

```powershell
cd "C:\Users\31721\OneDrive\文档\deepseek-harness\default-workspace\workhub"
$git = "C:\Program Files\Git\cmd\git.exe"   # git 不在 PATH 里，用完整路径

# 1. 改版本号（唯一来源）与 CHANGELOG
#    workhub/__init__.py -> __version__ = "1.5.0"
#    CHANGELOG.md        -> 新的一节

# 2. 本地先过一遍
python -m ruff check .
python -m unittest discover -s tests -t .

# 3. 提交、打标签、推送（tag 会触发 CI 与 PyPI 发布）
& $git add -A
& $git commit -F .git/msg150.txt          # 提交说明写文件里，PowerShell 不吃 heredoc
& $git tag -a v1.5.0 -m "WorkHub 1.5.0"
& $git push origin main
& $git push origin v1.5.0
```

推送后有两件事自动发生（见 `.github/workflows/`）：

| 工作流 | 触发 | 干什么 |
| --- | --- | --- |
| `ci.yml` | push / PR | 三平台 × Python 3.10–3.13 跑 ruff + unittest，另建一个 wheel |
| `publish.yml` | 打 `v*` 标签 | 建 sdist + wheel → 发 PyPI → 把文件挂到对应 Release |

## PyPI：还需要你在网页上点一次

## 现在怎么装（不需要 PyPI）

包已经挂在 GitHub Release 上，`pip` 直接能装：

```bash
pip install https://github.com/Elias1222/workhub/releases/download/v1.4.0/workhub-1.4.0-py3-none-any.whl
workhub --open
```

（在干净的 venv 里验证过：`workhub --version` → `WorkHub 1.4.0`，`web/index.html` 在 wheel 里。）

## PyPI：账号过不去 2FA 时先别管

`publish.yml` 的 `Publish to PyPI` job 默认**不跑**——它挂在仓库变量 `PYPI_ENABLED` 上。
所以现在打标签只会建包、挂 Release，不会因为 PyPI 没认领而变红。

等 PyPI 能登录了，二选一：

**A. Trusted Publishing（不用存密钥，推荐）**

1. 登录 <https://pypi.org/manage/account/publishing/> → **Add a pending publisher**
2. 填：

   | 字段 | 值 |
   | --- | --- |
   | PyPI Project Name | `workhub` |
   | Owner | `Elias1222` |
   | Repository name | `workhub` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

3. 仓库 Settings → Variables → Actions → 新建 `PYPI_ENABLED` = `true`
4. 打标签（或手动 Run workflow），包就上去了。

**B. API token**

1. <https://pypi.org/manage/account/token/> 建一个项目级 token
2. 仓库 Settings → Secrets and variables → Actions → `PYPI_API_TOKEN` = 那个 token
3. 同样把变量 `PYPI_ENABLED` 设成 `true`

两条路工作流都支持（`publish.yml` 里按有没有 `PYPI_API_TOKEN` 自动选）。

> PyPI 上 `workhub` 这个名字目前没人占；`pypi` environment 已经建好了。

> `id-token: write` + `pypa/gh-action-pypi-publish` 换成
> `with: password: ${{ secrets.PYPI_API_TOKEN }}`。

本地想先验证包没问题（不发布）：

```powershell
python -m build
python -m twine check dist/*
# 想真装一次看看界面在不在：
python -m pip install dist/workhub-1.4.0-py3-none-any.whl
workhub --version
```

## 发版前常改的三处

1. `workhub/__init__.py` 的 `__version__` —— 唯一版本来源，`pyproject.toml` 动态读取它。
2. `CHANGELOG.md` 加一节。
3. `docs/preview.png` 换一张截图（headless Edge 截图见下）。

```powershell
$ud = Join-Path $env:TEMP ("edgehub" + (Get-Random))
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new `
  --disable-gpu --no-first-run --user-data-dir=$ud --hide-scrollbars `
  --virtual-time-budget=7000 --window-size=1500,1450 `
  --screenshot="docs\preview.png" "http://127.0.0.1:8770/"
```

## 不想公开的部分

`.git/info/exclude` 里排除了 `hand-bloom/`（同目录下的另一个小项目，不属于本仓库）。
如果你以后想把它也发出去，删掉那一行、`git add hand-bloom` 即可。
