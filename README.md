# 闲鱼卖家工作台（Xianyu Seller Console）

面向闲鱼卖家的本地可部署运营工作台，集中管理账号、商品、订单、消息、回复和发货。

[![Upstream](https://img.shields.io/badge/upstream-23Star%2Fxianyu--super--butler-blue)](https://github.com/23Star/xianyu-super-butler)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)](https://react.dev/)
[![License](https://img.shields.io/badge/License-AGPL--3.0-222222)](LICENSE)

> 这是一个独立项目，当前代码以 [23Star/xianyu-super-butler](https://github.com/23Star/xianyu-super-butler) 为直接上游基线，并保留其 AGPL-3.0 许可与原有来源声明。项目定位、功能融合状态和后续路线见 [项目蓝图](docs/PROJECT_BLUEPRINT.md)；尚未实现的规划不会标记为现有功能。

当前基线提供多账号、商品、订单、卡密库存、自动回复、AI 回复、买家互动、通知和运营看板。涉及闲鱼账号及对外消息的自动化请谨慎启用，并遵守平台规则。

- 🏪 **多账号管理** — 扫码即接入，一个后台管完所有小号，逐账号独立配置策略
- 📦 **自动发货** — 卡密自动发出，支持多规格、多数量，发货前风险拦截
- 💬 **自动回复** — 关键词精确命中 + AI 议价，可设最低价与议价轮数，绝不越线让价
- ⭐ **买家互动** — 确认收货后自动评价、自动求小红花、自动发送致谢文本
- 🤖 **商品自动化** — 商品同步、素材库、定时擦亮、自动上下架
- 📊 **经营看板** — 成交额、到账、退款、订单和库存一屏掌握，**历史订单可一次性拉回**

![卖家工作台运营概览](docs/screenshots/revenue-overview.png)

## 核心功能

| 模块 | 能力 |
| --- | --- |
| 总览 | 汇总营收、账号、订单、卡密库存和运行状态 |
| 账号 | 扫码、密码或 Cookie 登录，资料同步，监听任务状态，暂停和自动回复配置 |
| 商品 | 从闲鱼同步商品，维护本地详情、图片、规格、数量和商品回复 |
| 商品自动化 | 商品筛选、素材库、发布记录、定时删除、短链修复和补偿任务 |
| 订单 | 一键拉取闲鱼历史卖出订单，状态判定、详情补全、批量刷新、手动发货和异常保护 |
| 卡密 | 卡券分组、库存导入、状态管理、多规格和多数量发货 |
| 自动回复 | 账号关键词回复、默认回复和回复一次控制 |
| 人工智能回复 | 兼容 OpenAI 协议的大模型配置、上下文对话和测试 |
| 自动发货 | 全局、指定账号、指定商品三级发货规则及发货前风险拦截 |
| 消息管理 | 闲鱼会话列表、消息收发、搜索筛选、回复决策日志和过滤规则 |
| 通知与日志 | 通知渠道、账号绑定、风险日志和系统日志 |
| 设置 | 管理员账号与改密、注册与邮箱验证开关、服务、备份及系统配置 |
| 公告与更新 | 从自建地址拉取公告与版本信息，首页横幅提示，「关于」页手动检查更新 |

## 界面预览

### 账号管理：一个后台管完所有小号

扫码添加账号，实时显示监听状态。每个账号可独立设置自动确认、人工接入暂停时长、
是否启用 AI 回复，互不干扰。

![账号管理](docs/screenshots/accounts.png)

### 商品与发货：卡密自动发到买家手上

同步在售商品，逐个商品绑定发货内容，支持多规格和多数量。已下架的商品会被标记出来
并默认隐藏，不和在售的混在一起。

![商品与发货](docs/screenshots/items-delivery.png)

### 订单管理：接入前的历史订单也能一次拉回来

「拉取卖出订单」会把闲鱼上的历史订单整批同步进来，不只是接入之后的新单，
所以刚部署就能看到完整的经营数据。状态、买家、实付金额和发货情况一目了然，
支持按账号和状态筛选，也能手动发货或补发。

![订单管理](docs/screenshots/orders.png)

### 买家互动：确认收货后的动作全部自动完成

评价买家、索要小红花、发送收货致谢，三项都能逐账号开关。买家一确认收货，
致谢立即发出，评价和求花在订单状态就绪后自动执行。

![买家互动](docs/screenshots/buyer-interaction.png)

### 消息中心：所有账号的会话在一个页面里

跨账号会话列表，支持搜索和筛选，可以直接接管对话。自动回复的每一次决策都有日志，
能查到为什么回了、为什么没回。

![消息中心](docs/screenshots/message-center.png)

## 如何部署

> 建议部署在你控制的本地设备或服务器，并先阅读 [部署与排查](docs/deployment.md) 中的数据、安全和验证说明。

### Docker Compose（从本项目源码构建）

```bash
cp .env.example .env
# 修改 .env 中的管理员凭据后再启动
docker compose up -d --build
```

默认 Web UI 地址为 `http://127.0.0.1:8080`。管理员密码必须设置为非空强密码；
该工作副本不使用上游已发布的预构建镜像。部署前请阅读 [部署与排查](docs/deployment.md)。

国内网络用 CN 配置（apt、pip、npm、Chromium 全部走国内镜像）：

```bash
docker compose -f docker-compose-cn.yml up -d --build
```

可选 Nginx：`docker compose --profile with-nginx up -d --build`

### 源码运行（开发调试）

需要 Python 3.11+、Node.js 20+、npm。在项目目录中运行：

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
playwright install chromium

cd frontend && npm ci && npm run build && cd ..
python Start.py
```

### 访问

- 管理页面：`http://localhost:8080/`
- API 文档：`http://localhost:8080/docs`
- 健康检查：`http://localhost:8080/health`

首次启动管理员用户名和密码由 `.env` 中的 `ADMIN_USERNAME` 与 `ADMIN_PASSWORD` 设置。

数据持久化到 `./data`（数据库）、`./logs`（日志）、`./backups`（备份）。

### 更新

```bash
# 配置本项目自己的远程后，再从该远程获取更新并重新构建。
docker compose up -d --build
```

> 本项目远程与上游仓库分开维护；获取项目更新时使用本项目仓库，不要直接将 `upstream` 分支合并进来。部署失败排查、使用流程和数据安全说明见 [docs/deployment.md](docs/deployment.md)。

## 许可与声明

本项目当前直接基于 [23Star/xianyu-super-butler](https://github.com/23Star/xianyu-super-butler) 创建；该上游声明其基于 [zhinianboke/xianyu-auto-reply](https://github.com/zhinianboke/xianyu-auto-reply) 二次开发。保留上述来源与许可信息，感谢相关原作者和贡献者。

项目使用 [GNU Affero General Public License v3.0](LICENSE)。修改、部署或通过网络提供服务时，请遵守 AGPL-3.0 的源代码公开义务。

本项目仅供学习、研究和合法自动化使用。使用者应遵守法律法规及平台规则，并自行承担使用风险。
