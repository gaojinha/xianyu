# 闲鱼卖家工作台移交文档

更新日期：2026-10-10

## 项目定位

- 项目名：闲鱼卖家工作台（Xianyu Seller Console）
- 本地路径：`/home/gao/xianyu-seller-console`
- 目标：基于现有闲鱼卖家管理系统建立可自托管的运营工作台。
- 当前代码基线：[`23Star/xianyu-super-butler`](https://github.com/23Star/xianyu-super-butler)，本地初始提交 `c73d755`。
- 许可证：AGPL-3.0。根目录 `LICENSE` 和上游来源声明已保留；分发或通过网络提供修改后的服务时，须履行相应源码与声明义务。

## 当前仓库状态

- 当前分支为 `main`。`origin` 指向本项目 GitHub 仓库 `https://github.com/gaojinha/xianyu.git`（公开仓库）；`upstream` 指向 `https://github.com/23Star/xianyu-super-butler.git`。
- 本项目品牌、部署配置、文档和前端元数据已在本地维护；不要将 `upstream/main` 误当作本项目发布分支。
- 原工作区 `/home/gao/shift-browser-tauri` 不属于本项目；此前其既有修改未被用于或覆盖。

## 已完成的项目化工作

- README、登录与侧栏品牌、关于页面、HTML 标题和 metadata 已调整为本项目身份。
- 前端包名和锁文件包名已同步更名。
- 新增 [项目蓝图](PROJECT_BLUEPRINT.md)，标注现有能力与后续规划的边界。Goofish CLI/MCP 和只读市场价格监控仍是规划，尚未接入。
- Compose 镜像与容器使用 `xianyu-seller-console` 命名；标准和 NAS 配置均要求设置非空 `ADMIN_PASSWORD`。NAS 配置从本项目 `Dockerfile-cn` 构建，不再使用上游预构建镜像。
- `.env.example` 中管理员密码留空。密码只在首次创建数据库时生效；数据库已存在时，须在应用设置中修改。
- [部署说明](deployment.md) 已与上述配置对齐，并说明平台人机验证应由账号所有者通过官方页面完成，不应绕过。
- GitHub Actions CI 已新增后端测试/编译及前端类型检查/构建任务，在 `main` 推送和面向 `main` 的 PR 上运行。

## 验证记录与限制

本轮在本地虚拟环境安装 `requirements.txt` 依赖，并安装 Playwright Chromium 后完成以下检查：

- 后端 `unittest discover -s tests -p "test_*.py" -v`：374 项通过。
- Python `compileall`：通过。
- 前端 TypeScript `tsc --noEmit` 与 `npm run build`：通过。
- 标准和 NAS Compose 配置检查：通过；使用临时 `ADMIN_PASSWORD` 满足必填插值，没有写入 `.env`。
- `git diff --check`：通过。

前端当前没有声明 Vitest、lint 脚本；这些检查尚未配置，不能视为已通过。上述检查不替代真实部署和账号功能验证。

## 后续建议

1. 在 GitHub 仓库设置中启用 `main` 分支保护，并将 CI 的 `Backend tests`、`Frontend checks` 设为必需检查；确认自动更新统计数据的 workflow 与保护规则兼容。
2. 继续区分本项目 `origin` 与上游 `upstream`；前端 Vitest 和 lint 尚未配置。
3. 按 [项目蓝图](PROJECT_BLUEPRINT.md) 先审视账号隔离、写操作幂等、权限、速率限制、审计和敏感数据处理，再增加 CLI/MCP 或市场监控功能。
4. 任何真实账号写操作先用测试账号验证；遇到平台人机验证时由账号所有者按官方流程处理。

## 新接手者注意

- 提交前先检查 `git status`、`git diff` 和 `git diff --check`，不要提交 `.env`、数据库、日志、Cookie、Token、卡密或其他账号数据。
- 不要把尚未实现的蓝图项目描述成当前功能。
- 若复制或引入其他项目代码，先核对许可证兼容性，并保留要求的版权、许可和来源信息。
