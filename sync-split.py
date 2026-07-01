import os

import requests

# ----------------- 环境变量与配置 -----------------
CF_API_TOKEN = os.getenv("CF_API_TOKEN")
ACCOUNT_ID   = os.getenv("CF_ACCOUNT_ID")
PROFILE_ID   = os.getenv("CF_PROFILE_ID", "")
MODE         = os.getenv("MODE", "include")  # 支持设定为 include 或 exclude
ALLOWED_MODES = {"exclude", "include"}

if not all([CF_API_TOKEN, ACCOUNT_ID]):
    raise ValueError("缺少环境变量！请设置 CF_API_TOKEN 和 CF_ACCOUNT_ID")

if MODE not in ALLOWED_MODES:
    raise ValueError(f"非法 MODE: {MODE}，只允许 {'/'.join(sorted(ALLOWED_MODES))}")

HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

# ----------------- 📡 远程数据源配置 -----------------

# 【A 组：Include 模式使用的自用代理文件】
PROXY_DOMAIN_URL = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/proxy_domains.txt"
PROXY_IP_URL     = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/proxy_ips.txt"

# 【B 组：Exclude 模式使用的自用排除文件】
# 1. 本地内网 IP 段（如 192.168.0.0/16 等）
EXCLUDE_LOCAL_IP_URL   = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/local_ips.txt"
# 2. 排除域名（国内直连域名，如 baidu.com 等）
EXCLUDE_DOMAIN_URL     = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/exclude_domains.txt"
# 3. 排除 IP 段（国内直连公网 IP 段段，如 GeoIP 提取的段）
EXCLUDE_PUBLIC_IP_URL   = "https://raw.githubusercontent.com/zsyo/cf-zt-split-sync/main/exclude_ips.txt"


def load_remote_file(url, is_domain=False):
    """通用远程文件加载，支持过滤注释、空行和去重"""
    if not url:
        return []
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"⚠️  从远程读取数据失败: {url} | 错误: {e}")
        return []

    results = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if is_domain:
            line = line.lstrip('.')  # 去除可能误写的前导点
        results.append(line)
    return list(set(results))


def build_domain_entries(domains, description_tag):
    """通用的域名规则组装逻辑，自动生成双通配形式（根域名 + *.子域名）"""
    entries = []
    for domain in domains:
        if domain.startswith("*."):
            entries.append({"host": domain, "description": f"{description_tag} Sub"})
        else:
            entries.append({"host": domain, "description": description_tag})
            entries.append({"host": f"*.{domain}", "description": f"{description_tag} Sub"})
    return entries


def sync_to_cloudflare():
    print(f"🔄 当前运行模式 Mode: [{MODE}]")
    final_routes = []

    # ----------------- 逻辑分流：Include 模式 -----------------
    if MODE == "include":
        print("📡 开始拉取 [Include 模式] 对应的自用代理源...")
        custom_domains = load_remote_file(PROXY_DOMAIN_URL, is_domain=True)
        custom_ips = load_remote_file(PROXY_IP_URL, is_domain=False)

        print(f"   └─ 已获取代理域名: {len(custom_domains)} 个 | 代理 IP 段: {len(custom_ips)} 条")

        # 组装域名与 IP
        final_routes.extend(build_domain_entries(custom_domains, "Custom Proxy Domain"))
        for ip in custom_ips:
            final_routes.append({"address": ip, "description": "Custom Proxy IP"})

    # ----------------- 逻辑分流：Exclude 模式 -----------------
    elif MODE == "exclude":
        print("📡 开始拉取 [Exclude 模式] 对应的自用排除源...")
        local_ips = load_remote_file(EXCLUDE_LOCAL_IP_URL, is_domain=False)
        exclude_domains = load_remote_file(EXCLUDE_DOMAIN_URL, is_domain=True)
        exclude_public_ips = load_remote_file(EXCLUDE_PUBLIC_IP_URL, is_domain=False)

        print(f"   └─ 已获取本地 IP 段: {len(local_ips)} 条")
        print(f"   └─ 已获取排除域名: {len(exclude_domains)} 个")
        print(f"   └─ 已获取排除公网 IP 段: {len(exclude_public_ips)} 条")

        # 按顺序组装：本地 IP -> 排除域名（双通配）-> 排除公网 IP
        for ip in local_ips:
            final_routes.append({"address": ip, "description": "Local IP Block"})

        final_routes.extend(build_domain_entries(exclude_domains, "Exclude Domain"))

        for ip in exclude_public_ips:
            final_routes.append({"address": ip, "description": "Exclude Public IP"})

    # ----------------- 配额校验与上传 -----------------
    total_rules = len(final_routes)
    print(f"📊 规则流水组装完毕，最终生成的规则总计: {total_rules} 条")

    if total_rules > 4000:
        print(f"⚠️  警告: 当前规则数 ({total_rules}) 已超出 Cloudflare 4000 条的硬性限制，将进行截断！")
        final_routes = final_routes[:4000]

    execute_upload(final_routes)


def execute_upload(routes):
    if PROFILE_ID:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{PROFILE_ID}/{MODE}"
    else:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{MODE}"

    print(f"🚀 正在上传至 Cloudflare (路由目标配置 Mode: {MODE})...")
    resp = requests.put(url, json=routes, headers=HEADERS)

    if resp.status_code in (200, 204):
        print(f"✅ 同步成功！策略已完全覆盖。")
    else:
        print(f"❌ 失败 {resp.status_code}: Cloudflare API 错误")
        print(resp.text)
        resp.raise_for_status()


if __name__ == "__main__":
    sync_to_cloudflare()
