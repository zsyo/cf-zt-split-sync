import os

import requests

# ----------------- 环境变量与配置 -----------------
CF_API_TOKEN        = os.getenv("CF_API_TOKEN")
ACCOUNT_ID          = os.getenv("CF_ACCOUNT_ID")
PROFILE_IDS         = [pid.strip() for pid in os.getenv("CF_PROFILE_ID", "").split(",") if pid.strip()]
MODE                = os.getenv("MODE", "include")  # 支持设定为 include 或 exclude
ALLOWED_MODES       = {"exclude", "include"}
FALLBACK_DNS        = os.getenv("FALLBACK_DNS", "119.29.29.29").strip() # 本地域名回退默认 DNS
USE_REMOTE_RULES    = os.getenv("USE_REMOTE_RULES", "false").strip().lower() == "true" # 是否启用远程文件规则（设置为 "true" 时走网络拉取）

if not all([CF_API_TOKEN, ACCOUNT_ID]):
    raise ValueError("缺少环境变量！请设置 CF_API_TOKEN 和 CF_ACCOUNT_ID")

if MODE not in ALLOWED_MODES:
    raise ValueError(f"非法 MODE: {MODE}，只允许 {'/'.join(sorted(ALLOWED_MODES))}")

HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

# ----------------- 💾 本地固定的文件名配置 -----------------
# 默认脚本会严格顺着这个字典查找 rules/ 下的文件, 当开启 USE_REMOTE_RULES 时，会从远程 URL 加载
LOCAL_FILES = {
    "PROXY_DOMAIN": "proxy_domains.txt", # 代理域名列表
    "PROXY_IP": "proxy_ips.txt", # 代理 IP 列表
    "EXCLUDE_LOCAL_IP": "local_ips.txt", # 本地 IP 段列表（如 192.168.0.0/16 等）
    "EXCLUDE_DOMAIN": "exclude_domains.txt", # 排除域名列表（国内直连域名，如 baidu.com 等）
    "EXCLUDE_PUBLIC_IP": "exclude_ips.txt", # 排除公网 IP 段列表（国内直连公网 IP 段段，如 GeoIP 提取的段）
    "FALLBACK_LOCAL": "fallback_local.txt" # 本地回退规则
}

# ----------------- 📡 远程数据源配置 -----------------
PROXY_DOMAIN_URL        = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/rules/proxy_domains.txt"  # 代理域名列表
PROXY_IP_URL            = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/rules/proxy_ips.txt"  # 代理 IP 列表
EXCLUDE_LOCAL_IP_URL    = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/rules/local_ips.txt"  # 本地 IP 段列表（如 192.168.0.0/16 等）
EXCLUDE_DOMAIN_URL      = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/rules/exclude_domains.txt"  # 排除域名列表（国内直连域名，如 baidu.com 等）
EXCLUDE_PUBLIC_IP_URL   = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/rules/exclude_ips.txt"  # 排除公网 IP 段列表（国内直连公网 IP 段段，如 GeoIP 提取的段）
FALLBACK_LOCAL_URL      = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/rules/fallback_local.txt"  # 本地回退规则


def load_rules_data(file_key, remote_url, is_domain=False):
    """
    解耦规则加载器：
    - 当 USE_REMOTE_RULES 为 true，请求传入的完整远程绝对路径 remote_url
    - 否则，直接读取 rules/<LOCAL_FILES[file_key]>
    """
    lines = []

    # ─── 方案 A：默认走远程完整绝对 URL 下载 ───
    if USE_REMOTE_RULES:
        lines = _load_from_remote(remote_url)

    # ─── 方案 B：直接读取本地 rules 目录下的文件 ───
    else:
        local_name = LOCAL_FILES.get(file_key)
        local_path = os.path.join("rules", local_name) if local_name else None

        if not local_path or not os.path.exists(local_path):
            print(f"⚠️  未找到本地文件: {local_path}，尝试降级切换为网络读取远程 URL...")
            lines = _load_from_remote(remote_url)
        else:
            print(f"📖 [本地读取] 正在加载: {local_path}")
            with open(local_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

    # 统一清洗、过滤注释和去重
    results = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if is_domain:
            line = line.lstrip('.')  # 去除可能误写的前导点
        results.append(line)

    return list(set(results))


def _load_from_remote(url):
    """内部私有远程拉取函数"""
    if not url:
        return []
    print(f"📡 [网络读取] 正在拉取: {url}")
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.text.splitlines()
    except Exception as e:
        print(f"⚠️  从远程读取数据失败: {url} | 错误: {e}")
        return []


def extract_root_domain_with_desc(raw_line, default_tag):
    """
    清洗并提取纯净根域名，同时保留原始行的自定义描述。
    返回: (纯根域名, 干净的描述)
    """
    # 1. 拆分描述
    if "," in raw_line:
        raw_domain, custom_desc = raw_line.split(",", 1)
        raw_domain = raw_domain.strip()
        desc = custom_desc.strip()
    else:
        raw_domain = raw_line.strip()
        desc = f"{default_tag} for {raw_domain}"

    # 2. 剥离通配符和前导点
    raw_domain = raw_domain.lstrip("*.").strip()

    # 3. 提取根域名
    parts = raw_domain.split('.')
    if len(parts) > 2:
        if parts[-2] in ["com", "net", "org", "gov", "edu"] and parts[-1] == "cn":
            return ".".join(parts[-3:]), desc
        return ".".join(parts[-2:]), desc
    return raw_domain, desc


def build_domain_entries(domains, description_tag):
    """通用的域名规则组装逻辑，自动生成双通配形式（根域名 + *.子域名）
    支持 `域名,自定义描述` 格式：逗号前为域名，逗号后为自定义 description
    """
    entries = []
    for raw in domains:
        # 解析可选的自定义描述（以逗号分隔）
        if "," in raw:
            domain, custom_desc = raw.split(",", 1)
            domain = domain.strip()
            custom_desc = custom_desc.strip()
        else:
            domain = raw
            custom_desc = None

        if domain.startswith("*."):
            desc = custom_desc if custom_desc else f"{description_tag} Sub"
            entries.append({"host": domain, "description": desc})
        else:
            root_desc = custom_desc if custom_desc else description_tag
            sub_desc = f"{custom_desc} Sub" if custom_desc else f"{description_tag} Sub"
            entries.append({"host": domain, "description": root_desc})
            entries.append({"host": f"*.{domain}", "description": sub_desc})
    return entries


def _parse_entry(raw, default_tag):
    """解析单条规则条目，支持 `值,自定义描述` 格式
    返回 (值, 描述) 元组；无逗号时使用默认描述
    """
    if "," in raw:
        value, custom_desc = raw.split(",", 1)
        return value.strip(), custom_desc.strip()
    return raw, default_tag


def remove_duplicate_routes(routes):
    """
    对最终组装出来的路由规则列表进行深度去重
    通过判断 host 或 address 的唯一性，确保相同的路由目标不会被重复提交
    返回 (去重后的路由列表, 去重后的重复条目集合)
    """
    seen = set()
    unique_routes = []
    duplicates = set()
    for route in routes:
        # 提取路由核心特征：如果是域名则提取 host，如果是 IP 则提取 address
        route_key = route.get("host") or route.get("address")
        if route_key and route_key not in seen:
            seen.add(route_key)
            unique_routes.append(route)
        elif route_key:
            duplicates.add(route_key)
    return unique_routes, duplicates


def sync_to_cloudflare():
    print(f"🔄 当前运行模式 Mode: [{MODE}] | 使用远程规则: [{USE_REMOTE_RULES}]")
    final_routes = []

    # 无论何种模式，都读取排除列表用于回退配置
    print("📡 正在拉取 [exclude_domains.txt] 用于生成本地域名回退...")
    exclude_domains_raw = load_rules_data("EXCLUDE_DOMAIN", EXCLUDE_DOMAIN_URL, is_domain=True)

    # ----------------- 逻辑分流：Include 模式 -----------------
    if MODE == "include":
        print("📡 开始拉取 [Include 模式] 对应的自用代理源...")
        custom_domains = load_rules_data("PROXY_DOMAIN", PROXY_DOMAIN_URL, is_domain=True)
        custom_ips = load_rules_data("PROXY_IP", PROXY_IP_URL, is_domain=False)

        print(f"   └─ 已获取代理域名: {len(custom_domains)} 个 | 代理 IP 段: {len(custom_ips)} 条")
        final_routes.extend(build_domain_entries(custom_domains, "Custom Proxy Domain"))
        for raw in custom_ips:
            ip, desc = _parse_entry(raw, "Custom Proxy IP")
            final_routes.append({"address": ip, "description": desc})

    # ----------------- 逻辑分流：Exclude 模式 -----------------
    elif MODE == "exclude":
        print("📡 开始拉取 [Exclude 模式] 对应的自用排除源...")
        local_ips = load_rules_data("EXCLUDE_LOCAL_IP", EXCLUDE_LOCAL_IP_URL, is_domain=False)
        exclude_public_ips = load_rules_data("EXCLUDE_PUBLIC_IP", EXCLUDE_PUBLIC_IP_URL, is_domain=False)

        print(f"   └─ 已获取本地 IP 段: {len(local_ips)} 条")
        print(f"   └─ 已获取排除域名: {len(exclude_domains_raw)} 个")
        print(f"   └─ 已获取排除公网 IP 段: {len(exclude_public_ips)} 条")

        # 按顺序组装：本地 IP -> 排除域名（双通配）-> 排除公网 IP
        for raw in local_ips:
            ip, desc = _parse_entry(raw, "Local IP Block")
            final_routes.append({"address": ip, "description": desc})

        final_routes.extend(build_domain_entries(exclude_domains_raw, "Exclude Domain"))

        for raw in exclude_public_ips:
            ip, desc = _parse_entry(raw, "Exclude Public IP")
            final_routes.append({"address": ip, "description": desc})

    # ----------------- 🌟 核心增量改动：全量去重 -----------------
    raw_count = len(final_routes)
    final_routes, duplicates = remove_duplicate_routes(final_routes)
    duplicated_count = raw_count - len(final_routes)

    if duplicated_count > 0:
        print(f"🧹 规则去重器：已自动清洗并过滤了 {duplicated_count} 条重复的冲突路由条目。")
        print("   重复条目列表（已去重）：")
        for dup in sorted(duplicates):
            print(f"     • {dup}")

    # ----------------- 配额校验与上传 -----------------
    total_rules = len(final_routes)
    print(f"📊 规则流水组装完毕，最终生成的独立规则总计: {total_rules} 条")

    if total_rules > 4000:
        print(f"⚠️  警告: 当前纯净规则数 ({total_rules}) 已超出 Cloudflare 4000 条的硬性限制，将进行截断！")
        final_routes = final_routes[:4000]

    execute_upload(final_routes)

    # ----------------- 🌟 同步 Local Domain Fallback -----------------
    sync_local_domain_fallback(exclude_domains_raw)


def execute_upload(routes):
    # 如果未指定策略 ID，则使用默认策略（单次上传）
    if not PROFILE_IDS:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{MODE}"
        print(f"🚀 正在上传至 Cloudflare (默认策略 | Mode: {MODE})...")
        resp = requests.put(url, json=routes, headers=HEADERS)
        if resp.status_code in (200, 204):
            print("✅ 同步成功！默认策略已完全覆盖。")
        else:
            print(f"❌ 失败 {resp.status_code}: Cloudflare API 错误")
            print(resp.text)
            resp.raise_for_status()
        return

    # 多策略逐个同步
    total = len(PROFILE_IDS)
    for idx, pid in enumerate(PROFILE_IDS, 1):
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{pid}/{MODE}"
        print(f"🚀 [{idx}/{total}] 正在上传至 Cloudflare (策略 ID: {pid} | Mode: {MODE})...")
        resp = requests.put(url, json=routes, headers=HEADERS)
        if resp.status_code in (200, 204):
            print(f"   ✅ 策略 {pid} 同步成功！")
        else:
            print(f"   ❌ 策略 {pid} 失败 {resp.status_code}: {resp.text.strip()}")
            resp.raise_for_status()


def sync_local_domain_fallback(exclude_domains_raw):
    """
    合并 fallback_local.txt 与精简后的根域名，并上传至 Fallback 策略中。
    """
    print(f"⚙️  开始处理域名回退（Fallback），指定上游 DNS: [{FALLBACK_DNS}]")

    fallback_payload = []
    seen_suffixes = set()

    # 1. 首先加载高优先级的本地默认回退文件 fallback_local.txt
    print("📡 正在拉取高优先级 [fallback_local.txt] 默认本地回退规则...")
    local_fallback_raw = load_rules_data("FALLBACK_LOCAL", FALLBACK_LOCAL_URL, is_domain=False)

    for raw in local_fallback_raw:
        # 该文件可能包含原版自定义配置，同样支持“值,描述”或“值”，但不对其进行根域名精简切碎
        suffix_val, desc_val = _parse_entry(raw, "Default Local Fallback")
        suffix_val = suffix_val.lstrip('.').strip()

        if suffix_val and suffix_val not in seen_suffixes:
            seen_suffixes.add(suffix_val)
            fallback_payload.append({
                "suffix": suffix_val,
                "dns_server": [FALLBACK_DNS],
                "description": desc_val
            })

    print(f"   └─ 已载入置顶核心回退规则: {len(fallback_payload)} 条")

    # 2. 清洗并追加 exclude_domains.txt 中的根域名（低优先级，不覆盖高优先级的定义）
    domain_fallback_count = 0
    for raw in exclude_domains_raw:
        root_domain, custom_desc = extract_root_domain_with_desc(raw, "Local Fallback")

        if root_domain and root_domain not in seen_suffixes:
            seen_suffixes.add(root_domain)
            fallback_payload.append({
                "suffix": root_domain,
                "dns_server": [FALLBACK_DNS],
                "description": custom_desc  # 完美保留原先规则中逗号后的描述
            })
            domain_fallback_count += 1

    print(f"   └─ 已追加清洗后的独立排除主域: {domain_fallback_count} 个")
    print(f"📊 最终组装的 Fallback 规则总计: {len(fallback_payload)} 条")

    # 3. 通过 API 执行全量覆盖同步
    if not PROFILE_IDS:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/fallback_domains"
        print("🚀 正在上传 Fallback 规则至 Cloudflare (默认策略)...")
        resp = requests.put(url, json=fallback_payload, headers=HEADERS)
        if resp.status_code in (200, 204):
            print("✅ 本地域名回退 (Fallback) 全量同步成功！")
        else:
            print(f"❌ Fallback 同步失败: {resp.text}")
    else:
        total = len(PROFILE_IDS)
        for idx, pid in enumerate(PROFILE_IDS, 1):
            url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{pid}/fallback_domains"
            print(f"🚀 [{idx}/{total}] 正在上传 Fallback 规则至 Cloudflare (策略 ID: {pid})...")
            resp = requests.put(url, json=fallback_payload, headers=HEADERS)
            if resp.status_code in (200, 204):
                print(f"   ✅ 策略 {pid} Fallback 同步成功！")
            else:
                print(f"   ❌ 策略 {pid} Fallback 失败: {resp.text}")


if __name__ == "__main__":
    sync_to_cloudflare()
