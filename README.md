# 工程部能耗管理系统

基于 Flask 的工程部能耗管理系统，支持电/水/气能耗录入、空调/锅炉开关记录、交接班记录、月度报表导出，适配手机端访问。

## 功能概览

| 模块 | 功能 |
|------|------|
| 前台首页 | 天气预报、本月能耗汇总、能耗趋势图、开关记录曲线 |
| 录入数据 | 电/水/气表计读数、空调/锅炉开关、操作员选择、交接班记录 |
| 交接班记录 | 首页一键查看最新交接班内容 |
| 后台能耗记录 | 查看/编辑/删除每日能耗数据，实时刷新 |
| 后台空调/锅炉记录 | 开关日志，含设备/状态/操作人 |
| 后台交接班记录 | 多条记录支持，可逐条删除 |
| 月度报表导出 | 按时间段导出电/水/气报表，支持全部导出 |
| 系统设置 | 天气城市配置、操作员管理、账号权限管理 |

---

## 快速部署（Docker）

### 方式一：直接拉取镜像（推荐）

```bash
docker run -d \
  --name kami-energy-dashboard \
  --restart unless-stopped \
  -p 5000:5000 \
  -v energy_data:/data \
  ghcr.io/espkami/chuban-gongcheng:latest
```

访问 http://localhost:5000 即可使用。

---

### 方式二：docker-compose（推荐生产环境）

```bash
# 1. 克隆仓库
git clone https://github.com/espkami/chuban-gongcheng.git
cd kami-energy-dashboard

# 2. 配置（可选）
cp .env.example .env
# 编辑 .env 修改端口等配置

# 3. 启动
GITHUB_USERNAME=your-username docker-compose up -d

# 4. 查看日志
docker-compose logs -f
```

---

### 方式三：本地构建

```bash
# 构建并启动
docker-compose -f docker-compose.build.yml up -d --build
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `5000` | 对外暴露端口 |
| `DB_PATH` | `/data/dashboard.db` | 数据库路径（容器内） |

---

## 数据持久化

数据库文件存储在 Docker volume `energy_data` 中，容器重启/更新后数据不丢失。

```bash
# 备份数据
docker cp kami-energy-dashboard:/data/dashboard.db ./backup_$(date +%Y%m%d).db

# 恢复数据
docker cp ./backup_20260101.db kami-energy-dashboard:/data/dashboard.db
```

---

## GitHub Actions 自动构建

### 触发条件

| 事件 | 行为 |
|------|------|
| push `main` 分支 | 构建并推送 `latest` 标签到 GHCR |
| push `v*` tag | 推送语义化版本标签到 GHCR + Docker Hub |
| 手动触发 | `workflow_dispatch` 任意分支 |

### 配置 Secrets

在 GitHub 仓库 → Settings → Secrets and variables → Actions 中添加：

| Secret 名称 | 说明 | 必填 |
|-------------|------|------|
| `GITHUB_TOKEN` | 自动提供，无需手动添加 | ✅ 自动 |
| `DOCKERHUB_USERNAME` | Docker Hub 用户名 | 仅推 Docker Hub 时需要 |
| `DOCKERHUB_TOKEN` | Docker Hub Access Token | 仅推 Docker Hub 时需要 |

> Docker Hub Token 获取：https://hub.docker.com/settings/security → New Access Token

### 发布新版本

```bash
# 打 tag 触发完整发布流程
git tag v1.0.0
git push origin v1.0.0
```

构建完成后镜像地址：
- GHCR: `ghcr.io/espkami/chuban-gongcheng:v1.0.0`
- Docker Hub: `espkami/chuban-gongcheng:v1.0.0`

---

## 项目结构

```
.
├── app/
│   ├── server.py          # Flask 后端
│   ├── index.html         # 前端单页应用
│   └── requirements.txt   # Python 依赖
├── .github/
│   └── workflows/
│       └── docker.yml     # GitHub Actions CI/CD
├── Dockerfile             # 容器构建文件
├── docker-compose.yml     # 生产部署（拉取镜像）
├── docker-compose.build.yml # 本地构建部署
└── README.md
```

---

## 默认账号

| 账号 | 密码 | 角色 |
|------|------|------|
| admin | kami2024 | 超级管理员 |

> ⚠️ 首次部署后请立即修改默认密码（后台 → 系统设置 → 修改我的密码）

---

## 技术栈

- 后端：Python 3.11 + Flask + SQLite
- 前端：原生 HTML/CSS/JS + Chart.js
- 容器：Docker + docker-compose
- CI/CD：GitHub Actions -> GHCR

---

## License

MIT
