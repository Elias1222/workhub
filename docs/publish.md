# 发布到 GitHub

仓库已经在本地初始化好了：`main` 分支、首次提交、`v1.1.0` 标签、remote `origin` 都配过了
（`origin` 指向 `https://github.com/Elias1222/workhub.git`）。**只剩在 GitHub 上建一个空仓库然后 push**。

## 剩下这一步

1. 打开 <https://github.com/new>
   - Repository name：`workhub`
   - **不要**勾 "Add a README file" / "Add .gitignore" / "Choose a license"（仓库里都有了，勾了会冲突）
   - Public 或 Private 都行
2. 回到本机：

```powershell
cd "C:\Users\31721\OneDrive\文档\deepseek-harness\default-workspace\workhub"
& "C:\Program Files\Git\cmd\git.exe" push -u origin main
& "C:\Program Files\Git\cmd\git.exe" push origin v1.1.0
```

第一次 push 会弹浏览器让你登录 GitHub（Git Credential Manager 自动接管），登录一次之后就不用再管。

> `git` 不在 PATH 里（winget 装的，当前终端环境变量没刷新），所以上面用了完整路径。
> 新开一个终端就能直接敲 `git`。

## 想发版 / 发 PyPI

```powershell
& "C:\Program Files\Git\cmd\git.exe" tag -a v1.1.1 -m "v1.1.1"
& "C:\Program Files\Git\cmd\git.exe" push origin v1.1.1

python -m pip install --upgrade build twine
python -m build
python -m twine upload dist/*
```

包内已声明 `workhub = "workhub.cli:main"` 入口和 `web/*.html` 包数据，
`pip install workhub && workhub --open` 就能用（本地已验证 wheel 里带界面文件）。

## 发版前常改的三处

1. `workhub/__init__.py` 的 `__version__` —— 唯一版本来源，`pyproject.toml` 动态读取它。
2. `CHANGELOG.md` 加一节。
3. `docs/preview.png` 换一张更漂亮的截图。

## 不想公开的部分

`.git/info/exclude` 里排除了 `hand-bloom/`（同目录下的另一个小项目，不属于本仓库）。
如果你以后想把它也发出去，删掉那一行、`git add hand-bloom` 即可。
