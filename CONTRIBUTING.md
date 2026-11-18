# 贡献指南

欢迎提 Issue 和 Pull Request。先说三条项目原则，符合这三条的改动最容易被接受：

1. **零第三方依赖**：后端只用 Python 标准库。这保证了镜像构建永远不被包源卡住。确需引入依赖时，请在 PR 里说明理由和替代方案为何不行。
2. **凭证不出部署机**：任何设计都不能要求用户把网盘 Cookie、账号密码发到第三方服务或写进日志。
3. **不确定不删**：清洗/自动化逻辑宁可保留并标注，也不要自作主张丢弃用户文件。

## 本地开发

不需要 Docker 即可跑起来（Python 3.10+）：

```bash
git clone https://github.com/fjtraindriver/panharbor.git
cd panharbor
DATA_DIR=./data PORT=18090 APP_PASSWORD=dev python3 -m app.main
# 打开 http://127.0.0.1:18090
```

跑测试：

```bash
python3 tests/test_planner.py
```

## 提 Issue

- Bug 请用 Bug 模板，附版本（镜像标签或提交号）、部署环境、复现步骤和任务日志。
- **千万不要把 Cookie、密码、完整分享链接贴进 Issue**，公开仓库里所有人都看得见。日志先脱敏再贴。
- 功能建议先开 Issue 讨论方向，再写代码，避免白做。

## 提 Pull Request

- 一个 PR 只做一件事；改动 UI 或流程时附截图或录屏。
- 涉及网盘接口行为的改动，请注明实测环境与结果（哪个接口、是否真实账号验证过）。
- 提交信息用简短祈使句，如 `planner: keep subtitles when video is skipped`。
- 新增网盘支持时，按驱动方式实现：参考 `app/quark.py` 的接口面（列目录 / 解析分享 / 列分享 / 转存 / 改名）新增一个驱动模块，不要把网盘细节写进主流程。

## 版本与发布

- 版本号遵循语义化版本：不兼容变更升主版本，新增功能升次版本，修复升修订版本。
- 每次发布在 CHANGELOG.md 记录，并在 GitHub 打 `vX.Y.Z` 标签；标签会触发镜像构建，产生同名镜像标签。
- main 分支保持随时可部署；功能开发走分支 + PR 合入。
