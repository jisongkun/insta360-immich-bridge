# Insta360 Immich Bridge

将 Insta360 原片转换为带 360 元数据的成片，通过 Immich API 上传到内部图库。视频输出 MP4，原有 INSP 照片转换保留为 JPG。拼接、元数据注入和缩略图复用 [jagjordi/insta360-autostitcher](https://github.com/jagjordi/insta360-autostitcher)；新增代码负责发现、调度、持久化状态、验证和 Immich 交付，不另写拼接算法。保留 GPL-3.0、上游归属和 Git 历史；当前 GitHub 仓库仍是 fork。

开发源码已实现桥接；**尚未部署到 NAS，真实 GPU／相机样片验收未完成**。本机的模拟 SDK 测试与容器构建不能证明真实 INSV/INSP 兼容性。详见 [验证记录](docs/VALIDATION.md)。

## 工作流程

1. Immich 元数据 API 按 `createdAt`／`updatedAt` 增量发现 `.insv`／`.insp`，分页成功才推进服务器时间水位；默认重叠 300 秒。也可指定多个只读目录递归扫描。
2. 等文件稳定，按文件名、lens 00/10 和 segment 配对；单文件双视频流直接交给原转换器。不同 segment 分别导出，**不拼接录制分段时间轴**。同名但字节不同的镜头拒绝猜配。
3. 使用私有工作目录和私有 legacy DB 调用原转换 worker。按原有开关配置 MediaSDK 3.1.5，关闭 debug 假成功。
4. 验证原片未变、完整解码、2:1、指定尺寸、视频时长和音频、拍摄时间及 360 元数据。失败不上传。
5. SHA-1 检查 Immich 同字节资产，流式上传；下载服务器原文件流并计算 SHA-256。持久化核验凭据后删除本工具的本地成片，保留 INSV/INSP 原片和任务状态。

去重基于镜头字节 SHA-256 + segment、有效转换参数、SDK／模型身份、Immich 地址与账号。移动文件或删除本地已核验 MP4 不会重新转换；改扫描间隔不影响去重。默认自动运行关闭，手动发现与手动处理分开；也有“手动发现并处理”。首次发现要等稳定窗口，再次扫描后才排队。

[Immich 官方格式表](https://docs.immich.app/features/supported-formats/)包含 INSV 和 INSP。API 只能发现已经进入 Immich 索引且 API Key 可见的原片；还没入库的文件可用额外目录扫描。API 增量扫描复用本地资产索引，避免每次递归遍历整个图库；稳定性仍需读取已知路径的 stat，首次或变动后才重算内容哈希。

## 推荐配置

Linux AMD64 + NVIDIA GPU + NVIDIA Container Toolkit。用只读挂载映射原片，避免再次下载数百 GB 原始视频；不可共享挂载时启用 `download_sources`，原片临时缓存位于 `/work/sources`。默认一个拼接任务，先做真实样片验收再提高并发。

| 设置 | 默认 | 用途 |
|---|---:|---|
| automatic | false | 手动启用定时发现及处理 |
| api_source_enabled | true | API 原片发现，独立于上传地址 |
| automatic_photos | false | 自动照片处理需显式开启 |
| interval | 60 秒 | Immich 增量发现 |
| folder_interval | 600 秒 | 额外目录扫描 |
| stable_seconds | 60 秒 | 两次观察之间原片大小/时间等未变化 |
| full_interval | 86400 秒 | 全量资产核对及成片存在性检查 |
| overlap | 300 秒 | 水位重叠，处理索引延迟 |
| stitch_parallelism | 1 | 转换/交付并发；相同来源串行 |
| output_size | 5760x2880 | 原转换器固定 2:1 输出 |
| bitrate | 100000000 | 100 Mbps；可选择跟随原始码率 |
| stitch_type | dynamicstitch | 也支持原有 optflow/aistitch |

保留 H.265、FlowState、方向锁定、Stitch Fusion、CUDA 开关、自动尺寸、原始码率、预计大小比率、缩略图、排序／分页／多选、失败重试。方向锁定要求 FlowState。界面显示阶段、耗时和成片字节／容量估算，不把大小比例当作完成进度。自动尺寸只接受已确认的 2:1 等距柱状投影；未知原片须指定固定尺寸。转换前检查预计临时空间并保留 1 GiB 余量。拍摄日期优先读取原片元数据，文件名与配置时区仅作回退。

## 启动

以下是部署说明，本开发任务未执行 `compose up` 或连接你的 NAS／Immich。

将私人 SDK 安装包放入 `backend/vendor/MediaSDK-3.1.5-linux-amd64.deb`。本机已从用户下载包提取；文件不进入 Git。默认构建核验 SHA-256：

```text
444b4b0bc22aa5335e5cc2c3dd092b16207f3a7c19bb7fe97799e94eca69325e
```

```sh
cp .env.example .env
mkdir -p bridge-config bridge-state bridge-work
cp bridge-config.example.json bridge-config/bridge-config.json
# 编辑 .env 中的 IMMICH_API_KEY、BRIDGE_LOGIN_TOKEN、SOURCE_DIR
# 编辑配置中的 immich_url 和 mappings；使用工具所在网络可访问的地址
# 在 Linux GPU 主机完成驱动/运行时准备和样片验收后：
docker compose build
docker compose up -d
```

默认仅绑定本机 `127.0.0.1:3000`，前端代理内部 backend:8008。设置 `BRIDGE_BIND` 可以改变监听地址；外部访问应由现有 HTTPS 反向代理转发。后端 API 不单独暴露。`SOURCE_DIR` 只读映射 `/sources`，`/state` 和 `/work` 必须分开；配置目录可写以保存网页设置。不要直接写 Immich 管理目录或数据库。

`mappings.from` 对应 API 返回的 `originalPath` 前缀，`to` 对应本工具里的只读挂载前缀，例如服务器 `/usr/src/app/upload` → 本工具 `/sources`。按真实 API 返回路径配置，不能凭宿主机文件名猜测。额外目录填容器内路径，例如 `/sources/insta360`；会包含其子目录，跳过隐藏文件、符号链接和排除模式。原片不存在或映射不对时失败并保留状态，不把缺失来源当作已处理。

仅扫描指定目录时，设置 `api_source_enabled: false` 并填写 `folders`；上传仍使用同一个 Immich 地址和 Key，不会查询 API 原片列表。

只使用 API 下载原片时，设置 `download_sources: true`，`mappings: []`、`folders: []`；可不挂真实来源目录。缓存不自动删除远端原片，也不把缓存当作要替换的 Immich 资产。

## API Key 与登录

**允许使用 API Key。** Key 从环境变量 `IMMICH_API_KEY`（或 `api_key_env` 指定的名字）读取，也可使用 `api_key_file` 的只读文件；文件引用优先。Key 不写入 JSON、任务、manifest 或日志。文件方式需自己为 Compose 添加只读 secret 挂载。网页只配置引用名称／路径，实际 Key 在服务器 `.env` 或 secret 文件设置。

Key 应属于目标图库账号。需要 `user.read`、`server.about`、`asset.read`、`asset.upload`、`asset.download`；替换额外需要 `asset.copy`、`asset.delete`，以及所选关联复制所需权限。只有发现／上传时不必提供删除权限。401 或基础读取／上传的 403 会暂停自动运行；替换阶段缺少复制／删除权限的 403 只阻断该原片的版本切换，其他新片仍可正常入库。修复 Key 后测试连接并手动重试。当前客户端使用 Immich 3.2 的结构化搜索形状，以 [v3.2.4 源码](https://github.com/immich-app/immich/tree/v3.2.4/server/src)为依据；3.2+ 同大版本需在你的服务器验收，低于 3.2 或新大版本会拒绝。没有使用只允许 Session 的 sync stream。

`BRIDGE_LOGIN_TOKEN` 是本工具网页/API 的独立访问令牌，与 Immich Key 不同，必须设置。所有状态、日志、设置和缩略图接口都需要 Bearer 登录；缩略图通过认证 fetch 加载。旋转到同一账号的 Immich Key 不影响去重；换地址或账号会创建新的目标范围，不继承旧交付凭据。

## 改参数和替换

保存参数只改变新任务默认值；已有完成结果不会被定时任务重写。选择当前已完成、已核验且属于本工具的导出，点击“重新生成并替换所选导出”：新转换 → 上传新资产 → 服务器哈希核验 → 复制相册与收藏 → 旧成片软删除到 Immich 回收站 → 清理本地 MP4。

新旧 asset ID 不保持一致。默认不复制 shared links、stack、sidecar；JSON 可显式开启 `replace_shared_links`、`replace_stack`，sidecar 始终关闭。不删除来源 INSV/INSP。字节相同且 ID 相同则保留资产；遇到不属于本工具的重复资产，不能借此删除旧导出或修改重复资产。上传响应丢失时可找回同字节资产并核验，但不凭猜测授予所有权，因此需要替换的情况可能停下要求人工检查。

旧资产字节发生变化时停止替换。复制失败或回收失败保留新旧资产，可重试交付步骤而不用再次转换。同一原片未完成的版本持续占用交付顺序；新版本显示阻塞任务 ID，必须先恢复前一版本，避免重启后留下多个当前导出。旧成片已经被人永久删除时用显式恢复导出操作处理，自动检查仅显示缺失，不重置原片任务。

## 日志和恢复

- 网页全局日志显示扫描、连接、调度和失败摘要。点击任务时间查看有效参数、来源路径、目标账号、阶段事件和 SDK/转换日志。事件按序号补读，重连继续；可暂停、按事件级别筛选、下载已加载日志（SDK 文件末尾 64 KiB）。
- `/state/logs/bridge.log` 按大小轮转，默认每文件 10 MiB、5 个备份。
- `/work/jobs/<job-id>/<attempt-id>/` 保留 manifest、独立转换数据库、result、SDK 原生日志和控制器日志。每个 SDK/转换日志默认最多 10 MiB；超限停止转换，不上传。
- 默认成功日志保留 14 天，失败／未完成日志 30 天，每天清理。任务/交付凭据不会跟随日志删除。API 日志读取每文件末尾 64 KiB，最多 10 个文件。
- 阶段为 pending → converting → validating → upload_intent → verifying → replacing → cleanup → done。失败显示失败原因及可继续阶段。取消杀掉整个转换进程组；外部 API 操作在下一安全边界停下，已经发出的请求可能完成。
- 服务只允许一个进程持有同一个状态目录。重启释放旧 claims，只恢复曾手动／自动请求过的未完成任务。传输失败保留成片，网络／429／5xx 自动重试采用退避；参数、权限和源文件错误需要处理后手动重试。
- 备份 `/state/bridge.db`（SQLite 在线 backup 或停服务后复制，注意 WAL）和配置；正在交付时同时备份 `/work`。丢失状态可能丢失所有权记录和去重凭据，不能盲目接管旧成片。

## 开发与验证

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
python3 -c "import ast,pathlib; ast.parse(pathlib.Path('backend/auto-sticher.py').read_text())"
cd frontend && npm ci && npm run build
```

本地后端：`PYTHONPATH=backend BRIDGE_CONFIG=/absolute/config.json BRIDGE_LOGIN_TOKEN=... .venv/bin/python -m bridge`；配置中将 state/work 改为本机绝对路径。Vite 开发代理默认 `127.0.0.1:8008`，可用 `BRIDGE_DEV_API` 覆盖。实际 SDK 转换仅在 Linux AMD64 下验收。GitHub 仅用于源码，Actions 保持禁用；推送不代表部署授权。
