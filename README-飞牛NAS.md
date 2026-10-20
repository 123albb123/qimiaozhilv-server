# 飞牛 NAS 局域网部署

验收日期：2026-10-20。当前正式服务版本 R7，正式实现仅为 `server-mysql/`。

## 当前已部署实例

| 项目 | 实际值 |
| --- | --- |
| NAS | 192.168.1.22，i3-8100T / 16 GiB，Linux amd64 |
| 根目录 | `/vol1/1000/docker/qimiao` |
| 游戏 | TCP `192.168.1.22:7756` |
| GM | <http://192.168.1.22:8897> |
| 项目名 | `qimiao` |
| 应用镜像 | `qimiao-game:r7`、`qimiao-gm-api:r7`、`qimiao-gm-web:r7`、`qimiao-tools:r7` |
| 依赖 | MySQL 8.0.37、Redis 7.4-alpine；不发布宿主机端口 |
| 状态 | 五个常驻服务健康；一次性 init 正常退出 0 |

没有配置域名、公网穿透、Lucky 或 HTTPS。GM API 仅经同源 Web 代理访问。
只有 NAS 局域网 IP 的 7756、8897 对外绑定；API、MySQL、Redis 均在项目内部网络。

目录用途：`mysql/` 为存档和 GM 数据库，`redis/` 为 Redis AOF；`config/operations/` 为待发布 YAML，
`backups/` 保存经校验的备份；`build/r7/source/` 为本次镜像构建源，`source` 指向它。
`logs/` 保存部署和测试证据。MySQL 目录维持镜像所需 UID，不要递归改为用户 1000。

## 账号与启动

GM 初始用户名 `admin`。随机初始密码在 NAS 根目录私有 `.env` 的 `GM_ADMIN_PASSWORD` 中；
本机本次部署私有副本位于 `F:\codex\qimiao\task-records\deploy-r5\.env`。密码不写入本说明或 Git。
GM 管理员与游戏账号分开，游戏里自行注册普通账号。登录 GM 后可在“修改密码”页面改密。
改密后的有效密码在数据库；后续 init 不会用 `.env` 覆盖它。

以下命令在 NAS 终端执行，不需要在 Windows 安装 Docker。先定义固定项目函数：

```sh
root=/vol1/1000/docker/qimiao
qcompose() { docker compose --project-directory "$root" --env-file "$root/.env" -f "$root/compose.yaml" -p qimiao "$@"; }
qcompose ps
qcompose up -d --no-build --wait
qcompose logs --tail 100 game gm-api
```

临时停服：`qcompose stop`；再次启动：`qcompose up -d --no-build --wait`。
数据直接绑定到根目录，重建应用容器不会清空存档。不要删除 mysql/redis，不使用 `down -v` 或全局 prune。
健康检查失败先看对应服务日志和 `init` 退出状态，不能删除数据库来“修复初始化”。

## 在空目录首次安装（不要对现有实例重做）

需要 Docker Compose v2、足够磁盘空间，且 7756/8897 未占用。本次部署前已检查卷及现有服务。
仓库的构建流程不依赖预先存在的 Go 可执行文件或前端 dist。

在仓库根目录用 Python 生成两个上传包：

```sh
python server-mysql/deploy/fnos/package_source.py source-new.tar.gz
python server-mysql/deploy/fnos/prepare_deployment.py --output deploy-new --nas-ip 192.168.1.22 --tag new-version
```

`deploy-new/.env` 为本次新生成的私有凭据，应自行保管。使用 fnOS 文件工具将两个压缩包上传到
指定根目录的 `build/`。仅对确认为空的新实例执行：

```sh
root=/vol1/1000/docker/qimiao
cd "$root"
test ! -e .env && test ! -e compose.yaml && test ! -d mysql || exit 2
tar -xzf build/deploy-new.tar.gz -C "$root"
mkdir -p build/new-version
tar -xzf build/source-new.tar.gz -C build/new-version
ln -s build/new-version/source source
chmod 600 .env
chmod 755 ops/*.sh
qcompose() { docker compose --project-directory "$root" --env-file "$root/.env" -f "$root/compose.yaml" -p qimiao "$@"; }
qcompose config --quiet
qcompose build init game gm-api gm-web
qcompose up -d --no-build --wait
qcompose ps
```

启动顺序为 MySQL/Redis 健康 → init → game → GM API → Web。
init 从镜像中校验过的 YAML 原子导入 79 个配置（含真实 SkillLogicConfig），只在空配置库首次执行。
有数据但缺初始化标记时会拒绝覆盖；重复启动不会重置角色或管理员密码。
原始 JSON 仅在构建阶段离线转换，游戏运行时从 MySQL 读配置。

本次 NAS 的镜像加速站曾对 Node 返回 401，因此通过校验后的官方 Linux amd64 Node 镜像离线导入，
别名 `qimiao-node-builder:22.16.0`，由 `.env` 的 `MHQ_NODE_IMAGE` 选择。未修改 NAS 全局镜像源。
其他机器可以使用默认 Node 镜像；Go 构建代理可用 Docker build 参数 GOPROXY 调整。

## 客户端

运行 `F:\codex\qimiao\client-nas\梦幻奇遇记.exe`。原 ZIP 和 `client-original` 保留。
ZIP 标记 2026.1.3.2，Unity 2020.3.49f1c1，内置协议版本 2.5。
独立 NAS 副本改为 192.168.1.22:7756，并安装窄范围 HUD/弹道和商城同步兼容修复。
改动、原版哈希、恢复顺序和实际联调边界见《修复与测试报告》。不要把其他测试客户端的 DLL 覆盖到这个副本。

新角色需自行学习/配置技能；近处怪物使用右键交战。技能面板下方可拖入自动循环并保存，展开右上功能栏可切换自动战斗。
账号密码及客户端登录由玩家本人操作。

继续阅读：[GM 使用说明](GM-使用说明.md)、[备份与恢复](备份与恢复.md)、[修复与测试报告](修复与测试报告.md)。