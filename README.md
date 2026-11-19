# PanHarbor

[![docker-publish](https://github.com/fjtraindriver/panharbor/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/fjtraindriver/panharbor/actions/workflows/docker-publish.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

输入片名 → 自动搜夸克资源 → 挑版本 → 生成清洗后的转存计划 → 确认 → 转存到夸克指定目录并规范命名 → 验收回报。

> English summary: PanHarbor is a self-hosted, single-container web app that searches a pansou service for Quark Drive shares, builds a cleaned-up transfer plan (junk filtering, per-episode dedupe, subtitle pairing, standardized renaming), and saves the files into your own Quark Drive folders after your confirmation. Zero third-party Python dependencies.

单容器 Web 应用（Python 标准库零第三方依赖，docker build 不需要装任何包），可部署在任意支持 Docker 的机器上。搜索走 pansou 服务，转存用本地配置的夸克 Cookie 调夸克接口，运行时不经任何第三方服务器中转数据。

设计文档见 `docs/蓝图.md`。

## 用预构建镜像部署（推荐，免源码免构建）

镜像由 GitHub Actions 在每次推送 main 后自动构建并发布到 GHCR：`ghcr.io/fjtraindriver/panharbor`（标签：`latest`、短提交号；打 v* 标签时另有版本标签）。公开镜像，拉取无需登录：

```bash
mkdir panharbor && cd panharbor
# 只需两个文件：docker-compose.image.yml 改名为 docker-compose.yml，再建 .env（内容同 .env.example）
docker compose pull
docker compose up -d
# 浏览器打开 http://服务器地址:18090 ，后续配置同下文「快速开始」第 4 步起
```

更新：`docker compose pull && docker compose up -d`；回滚：把 compose 里镜像标签改成某个短提交号或版本标签再 pull。

运行要求只有三样：出站能访问 pansou 服务地址与夸克接口、给 /data 一个持久卷、一个可映射的端口。注意夸克 Cookie 有使用地点的连续性，部署位置不要频繁搬家。

## 快速开始（源码构建）

前置：已装 Docker；部署机能访问 pansou 服务；手边有夸克 Cookie（浏览器登录夸克网盘后取得，或从已在用的工具配置里复制同一份）。

```bash
# 1. 把本仓库放到部署机上一个目录（git clone，或下载源码包上传解压）
cd panharbor

# 2. 准备配置（只填访问密码一项，其余都在页面设置里办）
cp .env.example .env
# 编辑 .env，把 APP_PASSWORD 改掉

# 3. 启动
docker compose up -d --build

# 4. 浏览器打开 http://服务器地址:18090 ，用 .env 里的密码登录
```

首次登录后到「设置」页依次完成：

1. 填 pansou 服务地址、账号、密码 → 点「验证 pansou」
2. 填夸克 Cookie → 点「验证夸克」→ 点「选择…」用目录浏览器逐级进入子文件夹，选好电影目录、电视剧目录 → 保存设置
3. 「状态」页两项全绿，即可回「搜索」页开始找片

## 日常使用

输片名点「查影片」→ 先出条目卡片（海报、规范片名、年份、评分，来自 TMDB 与豆瓣）→ 选中条目点「找资源」→ 资源候选卡片（带有效/失效标记）选一张 → 生成转存计划（片名与电影/电视剧类型由条目自动带入）→ 在计划页核对「将存 / 将跳过」清单（可增减勾选）→ 确认转存 → 「任务」页看进度与验收结果（缺集会明确报出）。不想走条目这一步，点「直接搜资源」即按原关键词搜。

清洗规则（计划生成器）：杂文件（txt/图片/exe 等）不进网盘；同集多版本按清晰度与体积留最佳一份；预告/样片（体积过小）跳过；字幕按集保留；落盘统一改名为 `片名.S01E05.mkv` / `片名 (年份).mkv`；解析不了的默认保留并标黄，绝不自作主张删。细则见蓝图第 5 节。

## 更新与回滚

```bash
git pull                       # 或替换为新版源码包
docker compose up -d --build   # 数据在 ./data 卷里，不受影响
```

回滚：切回上一个版本标签（git checkout vX.Y.Z）后同样命令重建。

## 配置说明

| 配置 | 在哪配 | 说明 |
|---|---|---|
| PANHARBOR_PORT | .env | 对外端口，默认 18090 |
| APP_PASSWORD | .env | 初始密码；设置页改密后以库内哈希为准 |
| pansou 地址/账号/密码 | 设置页 | 填部署机能实际访问到的地址（直连后端或经反向代理中转均可） |
| TMDB API Key | 设置页 | themoviedb.org 免费申请；填了「查影片」才有评分与简介，不填仅查豆瓣。豆瓣源对机房网络常不可用（403/超时），以 TMDB 为准 |
| 夸克 Cookie | 设置页 | 只存部署机数据卷，不进仓库、不进日志；服务端轮换值（Set-Cookie）会自动回写续期，后台约每 24 小时低频保活一次，上次保活结果见状态页 |
| 电影/电视剧目录 | 设置页 | 目录浏览器逐级进入子文件夹选择（存 fid 与全路径名） |
| 小文件阈值/验链上限 | 设置页 | 默认 30MB / 20 条 |

## 安全

- 本应用握有夸克网盘写权限：不要把端口裸奔公网。对外访问应置于带 HTTPS 的反向代理之后并启用本应用密码，或只在可信内网中使用。
- Cookie、密码、数据库只存在部署机的 `./data` 目录；仓库 `.gitignore` 已排除 `.env` 与 `data/`，提交前仍请自查不要带入真实值。

## 排障

看日志：`docker compose logs -f panharbor`（应用本身少打日志，主要看「任务」页里的任务日志）。

| 现象 | 处理 |
|---|---|
| 状态页夸克红 | 先看状态页「夸克 Cookie 保活」的上次结果与时间；确认 Cookie 已失效时，从浏览器重新取一份，在设置页更新 |
| 状态页 pansou 红 | 检查 pansou 地址与账号密码，确认部署机能访问该地址且 pansou 服务在运行 |
| 搜索超时 | pansou 首搜较慢属正常；贴近 60 秒时精简 pansou 后端的慢源/插件 |
| 任务 partial | 看任务日志：多为某个嵌套目录组直存被拒（蓝图验证项 V2），其余文件不受影响 |
| 端口被占 | 改 .env 的 PANHARBOR_PORT 后重建 |

## 已知待验证项（不影响主流程）

- V2：分享深层子目录里的文件按 fid 直存到指定文件夹（顶层已实测通过）；若被拒，任务会标 partial 并在日志里写明是哪一组。
- V3：建文件夹/改名接口已按开源实现同族接口编写，若夸克侧返回异常，任务日志会带原始信息，据此修正即可。

验证脚本在 `tools/`（quark_save_test.py 已实测通过转存五步）。

## 结构

```
app/            后端与前端（main.py 服务与接口，pansou.py / quark.py 客户端，
                planner.py 计划生成器，executor.py 任务执行，store.py 存储，
                static/ 页面）
tools/          一次性验证脚本与图标生成器（make_favicon.py，纯标准库）
tests/          单元测试（python3 tests/test_planner.py、tests/test_quark_cookie.py、tests/test_folders_api.py）
docs/           蓝图与设计文档
```

后续扩展：搜索源与网盘都是独立模块（app/pansou.py、app/quark.py），新增网盘（如百度/阿里）时新增一个同接口的驱动文件并在设置页登记，不动主流程。

## 参与贡献

欢迎 Issue 与 PR，先读 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题请按 [SECURITY.md](SECURITY.md) 的方式私下报告，不要贴到公开 Issue。版本变更见 [CHANGELOG.md](CHANGELOG.md)，后续规划见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 许可证

[MIT](LICENSE)
