# cf-zt-split-sync

自动同步自定义分流规则到 Cloudflare Zero Trust 分流隧道（Split Tunnels），实现指定服务走 WARP 代理、其余流量直连的灵活分流策略。

> 本项目改写自 [cf-zt-cn-split](https://github.com/upbeat-backbone-bose/cf-zt-cn-split)，将原项目"CN 流量直连"的反向策略改为更通用的自定义分流模式，并增加了去重等增强功能。

---

## 功能简介

- 从仓库自维护的数据文件中读取代理/排除域名与 IP 段（也支持远程 URL 拉取）
- 自动生成双通配域名规则（根域名 + `*.` 子域名），减少遗漏
- 内置规则去重，避免重复提交导致 API 报错
- 支持 **Include**（指定服务走 WARP）和 **Exclude**（指定服务直连）两种模式
- 自动同步**本地域名回退规则**（Local Domain Fallback），将排除域名合并至回退策略，解决 CF DNS 解析的域名在国内访问缓慢的问题
- 通过 Cloudflare Zero Trust API 全量更新设备策略的 Split Tunnels 与 Fallback Domains 规则
- 通过 GitHub Actions 每周自动运行，也可手动触发

---

## 工作原理

```text
┌─ 规则加载（按 USE_REMOTE_RULES 切换）────────────────────────────┐
│  false（默认）: rules/*.txt 本地文件                              │
│  true         : raw.githubusercontent.com 远程 URL                │
│  本地文件不存在时自动降级为远程拉取                                │
└──────────────────────────────────────────────────────────────────┘
        ↓
rules/proxy_domains.txt / rules/proxy_ips.txt    rules/local_ips.txt / rules/exclude_domains.txt / rules/exclude_ips.txt
        ↓ Include 模式                              ↓ Exclude 模式
                        ↓ 加载规则文件 → 组装路由规则 ↓
                      sync-split.py
                        ↓ 去重 + 4000 条限制检查
                        ↓ Cloudflare Zero Trust API（PUT）
              设备策略 Split Tunnels 规则（include / exclude）
                        ↓
         Include: 指定服务走 WARP，其余直连
         Exclude: 指定服务直连，其余走 WARP

                        ↓ 并行流程：本地域名回退同步 ↓
              rules/fallback_local.txt（高优先级）
              + rules/exclude_domains.txt（精简根域名）
                        ↓ 合并去重
                        ↓ Cloudflare Zero Trust API（PUT）
              设备策略 Local Domain Fallback 规则
                        ↓
         排除域名使用指定 DNS（FALLBACK_DNS）解析，避免 CF DNS 减速
```

### 两种模式对比

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `include`（默认） | 列表中的域名/IP **走 WARP 代理**，其余直连 | 只代理特定境外服务（如 Google、OpenAI、GitHub），最小化代理范围 |
| `exclude` | 列表中的域名/IP **直连**，其余走 WARP | 类似传统 VPN 分流，大部分流量走 WARP，仅排除本地/国内服务 |

> **默认预配置**：本项目默认使用 `include` 模式，预置了常用境外服务域名（AI 服务、开发者工具、社交媒体、流媒体等），开箱即用。

---

## 前置要求

- Cloudflare Zero Trust 账户（免费版即可）
- 已在设备上部署 Cloudflare WARP 客户端
- Cloudflare API Token（需具备 Zero Trust 写权限）

---

## 快速开始

### 1. Fork 本仓库

点击右上角 **Fork** 按钮，将仓库复制到你的 GitHub 账户。

> **重要**：Fork 后需修改 `sync-split.py` 中所有 `raw.githubusercontent.com` URL，将 `zsyo/cf-zt-split-sync` 替换为你的 `用户名/仓库名`，否则脚本会读取上游仓库的数据。

### 2. 按需编辑规则文件

根据你的需求编辑以下文件：

| 文件 | 用途 | 适用模式 |
|------|------|----------|
| `rules/proxy_domains.txt` | 需要走代理的域名 | `include` |
| `rules/proxy_ips.txt` | 需要走代理的 IP 段 | `include` |
| `rules/exclude_domains.txt` | 需要直连的域名 | `exclude` |
| `rules/exclude_ips.txt` | 需要直连的公网 IP 段 | `exclude` |
| `rules/local_ips.txt` | 本地内网 IP 段 | `exclude` |
| `rules/fallback_local.txt` | 高优先级本地回退域名（如 `local`、`localhost`、`internal` 等） | 通用（始终生效） |

- 每行一条记录，支持 `#` 开头的注释
- 域名无需带前导点或协议前缀
- IP 段使用 CIDR 格式（如 `192.168.0.0/16`）
- 支持 `值,自定义描述` 格式：逗号前为域名/IP 段，逗号后为自定义描述（可选）
  - 示例：`169.254.0.0/16,DHCP Unspecified` → 描述为 "DHCP Unspecified"
  - 示例：`google.com,Google Search` → 生成两条规则，描述分别为 "Google Search" 和 "Google Search Sub"
  - 无逗号时使用默认描述，行为不变

### 3. 配置 GitHub Secrets

进入仓库 **Settings → Secrets and variables → Actions**，添加以下 Secrets：

| Secret 名称 | 说明 | 是否必填 |
|-------------|------|----------|
| `CF_API_TOKEN` | Cloudflare API Token，需具备 Zero Trust 写权限 | ✅ 必填 |
| `CF_ACCOUNT_ID` | Cloudflare 账户 ID，可在控制台右侧边栏找到 | ✅ 必填 |
| `CF_PROFILE_ID` | 设备策略 ID，支持逗号分隔多个 ID（如 `id1,id2`），留空则使用默认策略 | ❌ 可选 |
| `MODE` | 分流模式：`include` 或 `exclude`，默认 `include` | ❌ 可选 |
| `USE_REMOTE_RULES` | 是否从远程 URL 拉取规则文件，默认 `false`（使用本地 `rules/` 目录） | ❌ 可选 |
| `FALLBACK_DNS` | 本地域名回退使用的上游 DNS 服务器，默认 `119.29.29.29` | ❌ 可选 |

#### 如何获取 API Token

1. 前往 [Cloudflare Dashboard → API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. 点击 **Create Token**
3. 选择 **Edit Cloudflare Zero Trust** 模板，或手动添加 `Zero Trust: Edit` 权限
4. 复制生成的 Token

### 4. 启用 GitHub Actions

进入仓库 **Actions** 标签页，启用 Workflow。默认每周一北京时间 5:00 自动运行，也可在 Actions 页面点击 **Run workflow** 手动触发。

---

## 数据文件说明

### 规则加载方式

脚本支持两种规则加载方式，由 `USE_REMOTE_RULES` 环境变量控制：

| 方式 | `USE_REMOTE_RULES` | 行为 |
|------|-------------------|------|
| 本地文件（默认） | `false` | 从仓库 `rules/` 目录读取规则文件；若本地文件不存在，自动降级为远程拉取 |
| 远程 URL | `true` | 直接从 `raw.githubusercontent.com` 拉取规则文件 |

> **注意**：Fork 后若使用远程模式，需修改 `sync-split.py` 中的 `raw.githubusercontent.com` URL，将 `zsyo/cf-zt-split-sync` 替换为你的 `用户名/仓库名`。

### Include 模式（默认）

| 文件 | 预置内容 | 条目数 |
|------|----------|--------|
| `rules/proxy_domains.txt` | Google、OpenAI、Anthropic、GitHub、YouTube、Discord、Docker 等常用境外服务 | ~73 个域名 |
| `rules/proxy_ips.txt` | 暂无（可按需添加 IP 段） | 0 |

每个域名会自动生成两条规则：`example.com` 和 `*.example.com`，确保子域名也被正确代理。

> **自定义描述**：所有数据文件均支持 `值,自定义描述` 格式（逗号分隔）。自定义描述会替代默认描述标签显示在 Cloudflare 管理界面中，便于识别每条规则的用途。

### Exclude 模式

| 文件 | 用途 |
|------|------|
| `rules/local_ips.txt` | 本地内网 IP 段（如 `192.168.0.0/16`、`10.0.0.0/8`） |
| `rules/exclude_domains.txt` | 需要直连的域名（如国内网站） |
| `rules/exclude_ips.txt` | 需要直连的公网 IP 段 |

### 本地域名回退（Local Domain Fallback）

无论使用哪种模式，脚本都会自动同步**本地域名回退规则**到 Cloudflare Zero Trust 的 Fallback Domains 策略。该功能解决了一个常见问题：Cloudflare DNS 解析的域名 IP 在国内访问时可能路由到速度缓慢的节点。

**工作原理**：
1. 首先加载 `rules/fallback_local.txt` 中的高优先级回退域名
2. 然后将 `rules/exclude_domains.txt` 中的域名精简为根域名后追加（低优先级，不覆盖前者）
3. 合并去重后，通过 API 全量覆盖 Fallback Domains 策略
4. 所有回退域名使用 `FALLBACK_DNS` 指定的上游 DNS 服务器进行解析

| 文件 | 用途 | 优先级 |
|------|------|--------|
| `rules/fallback_local.txt` | 高优先级回退域名（如 `local`、`localhost`、`corp`、`internal` 等保留域名） | 高 |
| `rules/exclude_domains.txt` | 排除域名自动精简为根域名后作为补充回退规则 | 低 |

---

## 规则配额说明

Cloudflare Zero Trust Split Tunnels 单策略最多支持 **4000 条**规则。脚本会自动检查并截断超出部分，同时输出去重统计信息。

```text
域名规则（host）   → 每个域名 × 2（根域名 + *.子域名）
IP 规则（address） → 每条 CIDR 占 1 条规则
合计上限          → 4000 条
```

---

## 本地运行

```bash
# 安装依赖
pip install requests

# 设置环境变量
export CF_API_TOKEN="your_api_token"
export CF_ACCOUNT_ID="your_account_id"
export CF_PROFILE_ID=""         # 留空使用默认策略，多个 ID 用逗号分隔如 "id1,id2"
export MODE="include"           # include 或 exclude
export USE_REMOTE_RULES="false" # 默认 false：使用本地 rules/ 目录；true：从远程 URL 拉取
export FALLBACK_DNS="119.29.29.29"  # 本地域名回退使用的上游 DNS

# 运行脚本
python sync-split.py
```

正常输出示例：

```
🔄 当前运行模式 Mode: [include] | 使用远程规则: [False]
📖 [本地读取] 正在加载: rules/exclude_domains.txt
📡 开始拉取 [Include 模式] 对应的自用代理源...
📖 [本地读取] 正在加载: rules/proxy_domains.txt
📖 [本地读取] 正在加载: rules/proxy_ips.txt
   └─ 已获取代理域名: 73 个 | 代理 IP 段: 0 条
🧹 规则去重器：已自动清洗并过滤了 0 条重复的冲突路由条目。
📊 规则流水组装完毕，最终生成的独立规则总计: 146 条
🚀 正在上传至 Cloudflare (默认策略 | Mode: include)...
✅ 同步成功！默认策略已完全覆盖。
⚙️  开始处理域名回退（Fallback），指定上游 DNS: [119.29.29.29]
📡 正在拉取高优先级 [fallback_local.txt] 默认本地回退规则...
   └─ 已载入置顶核心回退规则: 18 条
   └─ 已追加清洗后的独立排除主域: 50 个
📊 最终组装的 Fallback 规则总计: 68 条
🚀 正在上传 Fallback 规则至 Cloudflare (默认策略)...
✅ 本地域名回退 (Fallback) 全量同步成功！
```

---

## GitHub Actions 定时任务

默认配置为每周一北京时间 5:00（UTC 周日 21:00）自动运行，也可在 Actions 页面点击 **Run workflow** 手动触发。

如需修改定时频率，编辑 `.github/workflows/split-sync.yml` 中的 `cron` 表达式。

---

## 与原项目的区别

| 特性 | cf-zt-cn-split（原项目） | cf-zt-split-sync（本项目） |
|------|--------------------------|---------------------------|
| 默认模式 | `exclude`（CN 直连） | `include`（指定服务代理） |
| 数据来源 | 外部数据源（GeoIP2-CN、surge-rules） | 自维护规则文件（支持本地/远程双模式） |
| 规则内容 | CN IP 段 + CN 域名 | 常用境外服务域名 |
| 去重逻辑 | 无 | ✅ 内置深度去重 |
| 域名规则生成 | 单一匹配 | 双通配（根域名 + `*.`子域名） |
| 本地域名回退 | 无 | ✅ 自动同步 Fallback Domains，解决 CF DNS 国内减速问题 |
| 规则加载方式 | 远程拉取 | 本地文件优先（默认），支持远程 URL 模式 |
| 使用场景 | CN 流量分流 | 通用自定义分流 |

---

## 常见问题

**Q：同步成功后 WARP 客户端需要重启吗？**  
A：不需要，Cloudflare Zero Trust 策略更新后会自动下发到已连接的 WARP 客户端。

**Q：本地域名回退（Fallback Domains）是什么？**  
A：当 WARP 客户端需要解析域名时，默认使用 Cloudflare 的 DNS。但某些域名（尤其是国内网站）经 CF DNS 解析后可能路由到访问缓慢的 IP。Fallback Domains 策略让指定域名改用 `FALLBACK_DNS`（默认 `119.29.29.29`）进行解析，从而获得更快的访问速度。脚本会自动将 `fallback_local.txt` 和 `exclude_domains.txt` 中的域名同步到该策略。

**Q：`USE_REMOTE_RULES` 什么时候应该设为 `true`？**  
A：当你想使用上游仓库或其他远程源的规则文件而非本地 `rules/` 目录中的文件时。默认为 `false`，即优先读取本地文件。若本地文件不存在，脚本会自动降级为远程拉取。

**Q：报错 `invalid number of rules, number of rules cannot be greater than 4000`？**  
A：数据文件条目过多超出上限，脚本已内置截断逻辑。如需更多规则请精简数据文件。

**Q：报错 `invalid exclude value` 或 `invalid domain name`？**  
A：请检查数据文件中是否包含非法字符或格式错误的条目。域名不应包含协议前缀（`http://`）或前导点。

**Q：Fork 后同步未生效？**  
A：请检查 `sync-split.py` 中的 `raw.githubusercontent.com` URL 是否已更新为你 Fork 仓库的地址（仅在使用远程模式时需要）。

**Q：如何确认规则已生效？**  
A：前往 Cloudflare Zero Trust Dashboard → **Settings → WARP Client → Device settings → 对应策略 → Split Tunnels** 查看分流规则，以及 **Fallback Domains** 查看回退域名规则。

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE) 文件。
