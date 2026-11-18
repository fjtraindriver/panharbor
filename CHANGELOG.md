# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.1] - 2026-11-18

### Fixed

- 部署在 CDN（如 Cloudflare 橙云）之后时，CDN 按扩展名默认缓存 `/app.js`、`/style.css` 且源站未声明缓存策略，升级后出现「新 HTML 配旧 JS」混版：设置页有「选择…」按钮但点击无反应。修复：静态文件响应统一带 `Cache-Control: no-cache`，且首页引用的 JS/CSS URL 带版本号参数，双保险防混版

## [0.3.0] - 2026-11-18

### Added

- 设置页目录浏览器：电影/电视剧目录可逐级进入子文件夹选择（面包屑导航），选中后保存文件夹 fid 与全路径名，不再限于根目录
- 站点图标 favicon：深蓝港湾底 + 船锚 + 波浪设计，提供 favicon.svg 与 favicon.ico（16/32/48 三尺寸）；生成器 `tools/make_favicon.py` 为纯标准库实现，可复现生成
- 新增 `tests/test_folders_api.py`：覆盖目录接口的子文件夹浏览与图标路由

### Changed

- 夸克验证按钮不再顺带填充根目录下拉，目录选择统一走目录浏览器

## [0.2.0] - 2026-11-18

### Added

- 夸克 Cookie 保活：客户端吸收每次响应 Set-Cookie 的轮换值（如 `__puus`）并自动写回持久化，Cookie 不再是存入后只会变旧的静态快照
- 后台保活线程：启动后 2~10 分钟首次执行，之后每 24 小时 + 0~3 小时随机抖动列一次根目录续期；状态页新增「夸克 Cookie 保活」一行，显示上次执行时间与结果
- 新增 `tests/test_quark_cookie.py`：覆盖 Cookie 合并、请求级吸收回写、保活记录与间隔范围

## [0.1.1] - 2026-11-18

### Changed

- 项目文档与注释通用化：只描述应用本身的要求，不绑定任何具体部署环境
- 仓库开源化整理：补齐 LICENSE、CONTRIBUTING、SECURITY、CHANGELOG、路线图与 Issue/PR 模板

## [0.1.0] - 2026-11-18

### Added

- 首个可用版本：输入片名经 pansou 搜索夸克资源，候选验活后生成带清洗规则的转存计划（杂文件剔除、同集多版本去重、字幕配对、缺集检查、规范命名），确认后转存到指定目录并改名验收
- Web 界面五页：搜索、计划预览、任务、设置、状态
- pansou 客户端（JWT 登录与令牌自动刷新）与夸克客户端（列目录、列分享、转存、改名）
- Docker 单容器部署（Python 标准库零第三方依赖）与 GHCR 预构建镜像
