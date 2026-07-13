// ==UserScript==
// @name         Host Extractor UI (可视化域名抓取)
// @namespace    https://github.com/zsyo/cf-zt-split-sync
// @version      1.0.0
// @description  点击右下角按钮展开深色半透明浮窗，可视化查看、去重、排序所有请求域名（含 WSS），支持单项带序号显示、单项复制与一键全选复制。
// @author       Zephyr
// @license      MIT
// @match        *://*/*
// @grant        GM_setClipboard
// @grant        GM_notification
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    if (window.self !== window.top) return;

    // 顶部加一个调试开关，默认关闭。如果你想看日志，手动改成 true
    const DEBUG_MODE = false;

    // 存储被劫持拦截的特殊域名（如WebSocket）
    const hijackedHosts = new Set();

    // ================= 【核心拦截：WebSocket】 =================
    const NativeWebSocket = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        try {
            if (url) {
                const wsUrl = url.startsWith('ws') ? url : new URL(url, window.location.href).href;
                const cleanUrl = wsUrl.replace(/^ws/, 'http');
                const urlObj = new URL(cleanUrl);
                if (urlObj.host) hijackedHosts.add(urlObj.host);
            }
        } catch (e) {
            // 只有开启 DEBUG 且带上明确标识，才输出到控制台
            if (DEBUG_MODE) {
                console.warn(`[HostExtractor] 拦截 WebSocket 域名失败. 传入的 URL 为:`, url, e);
            }
        }
        return protocols ? new NativeWebSocket(url, protocols) : new NativeWebSocket(url);
    };
    window.WebSocket.prototype = NativeWebSocket.prototype;

    // ================= 【核心逻辑：获取最终去重域名列表】 =================
    function getSortedHosts() {
        const finalHosts = new Set();
        finalHosts.add(window.location.host); // 注入当前页面 Host

        hijackedHosts.forEach(h => finalHosts.add(h)); // 注入 WSS 拦截 Host

        const resources = performance.getEntriesByType('resource'); // 注入静态资源 Host
        resources.forEach(entry => {
            try {
                if (entry.name && entry.name.startsWith('http')) {
                    const urlObj = new URL(entry.name);
                    if (urlObj.host) finalHosts.add(urlObj.host);
                }
            } catch (e) {
                if (DEBUG_MODE) {
                    console.warn(`[HostExtractor] 解析 performance 资源域名失败. 资源名:`, entry.name, e);
                }
            }
        });

        return Array.from(finalHosts).sort();
    }

    // ================= 【UI 组件构建】 =================
    function initUI() {
        // 1. 创建右下角的常驻悬浮触发按钮
        const triggerBtn = document.createElement('button');
        triggerBtn.id = 'he-trigger-btn';
        triggerBtn.innerText = '📋';
        triggerBtn.title = '展开域名分流面板';
        Object.assign(triggerBtn.style, {
            position: 'fixed', bottom: '20px', right: '20px', zIndex: '999998',
            width: '42px', height: '42px', borderRadius: '50%',
            backgroundColor: '#10B981', color: '#FFFFFF', border: 'none',
            boxShadow: '0 4px 10px rgba(0,0,0,0.3)', cursor: 'pointer', fontSize: '18px',
            display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s ease'
        });

        // 2. 创建主展示浮窗面板（默认隐藏）
        const panel = document.createElement('div');
        panel.id = 'he-main-panel';
        Object.assign(panel.style, {
            position: 'fixed', bottom: '75px', right: '20px', zIndex: '999999',
            width: '390px', maxHeight: '450px', borderRadius: '12px',
            backgroundColor: 'rgba(23, 23, 23, 0.8)', // 80%透明度的深色（Tailwind Zinc-900）
            backdropFilter: 'blur(8px)', // 毛玻璃模糊滤镜
            border: '1px solid rgba(255, 255, 255, 0.15)', // 浅色边界描边
            boxShadow: '0 20px 25px -5px rgba(0,0,0,0.5), 0 10px 10px -5px rgba(0,0,0,0.4)',
            display: 'none', flexDirection: 'column', overflow: 'hidden',
            fontFamily: 'system-ui, -apple-system, sans-serif', color: '#E4E4E7'
        });

        // 3. 面板头部 Header
        const header = document.createElement('div');
        Object.assign(header.style, {
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.1)',
            fontWeight: '600', fontSize: '14px', letterSpacing: '0.5px'
        });
        header.innerHTML = `<span>🌐 Host 捕获控制台</span>`;

        // 头部按钮组
        const headerBtnGroup = document.createElement('div');
        headerBtnGroup.style.display = 'flex';
        headerBtnGroup.style.gap = '8px';

        // 「一键复制全部」按钮
        const copyAllBtn = document.createElement('button');
        copyAllBtn.innerText = '复制全部';
        Object.assign(copyAllBtn.style, {
            backgroundColor: '#10B981', color: '#FFF', border: 'none', padding: '4px 8px',
            borderRadius: '4px', fontSize: '11px', cursor: 'pointer', fontWeight: '500'
        });

        // 「关闭」按钮
        const closeBtn = document.createElement('button');
        closeBtn.innerText = '✕';
        Object.assign(closeBtn.style, {
            background: 'none', color: '#A1A1AA', border: 'none', fontSize: '14px',
            cursor: 'pointer', padding: '0 4px'
        });

        headerBtnGroup.appendChild(copyAllBtn);
        headerBtnGroup.appendChild(closeBtn);
        header.appendChild(headerBtnGroup);
        panel.appendChild(header);

        // 4. 面板内容区（滚动列表）
        const listContainer = document.createElement('div');
        Object.assign(listContainer.style, {
            flex: '1', overflowY: 'auto', padding: '8px 12px', fontSize: '12px'
        });
        panel.appendChild(listContainer);

        // ================= 【交互事件绑定】 =================

        triggerBtn.addEventListener('mouseenter', () => { triggerBtn.style.backgroundColor = '#059669'; triggerBtn.style.transform = 'scale(1.05)'; });
        triggerBtn.addEventListener('mouseleave', () => { triggerBtn.style.backgroundColor = '#10B981'; triggerBtn.style.transform = 'scale(1)'; });

        triggerBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (panel.style.display === 'none') {
                renderList();
                panel.style.display = 'flex';
                triggerBtn.innerText = '❌';
            } else {
                panel.style.display = 'none';
                triggerBtn.innerText = '📋';
            }
        });

        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            panel.style.display = 'none';
            triggerBtn.innerText = '📋';
        });

        copyAllBtn.addEventListener('click', () => {
            const list = getSortedHosts();
            if (list.length === 0) return;
            GM_setClipboard(list.join('\n'), 'text');
            GM_notification({ text: `已成功复制全部 ${list.length} 个域名！`, title: 'Host Extractor', timeout: 2000 });
        });

        // 动态渲染列表函数
        function renderList() {
            listContainer.innerHTML = '';
            const hosts = getSortedHosts();

            if (hosts.length === 0) {
                listContainer.innerHTML = `<div style="text-align:center;color:#71717A;padding:20px;">未捕获到有效域名</div>`;
                return;
            }

            hosts.forEach((host, index) => {
                const item = document.createElement('div');
                Object.assign(item.style, {
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '6px 8px', borderRadius: '6px', marginBottom: '4px',
                    transition: 'background-color 0.15s ease', backgroundColor: 'rgba(255,255,255,0.02)'
                });

                item.addEventListener('mouseenter', () => { item.style.backgroundColor = 'rgba(255,255,255,0.08)'; });
                item.addEventListener('mouseleave', () => { item.style.backgroundColor = 'rgba(255,255,255,0.02)'; });

                // 新增：容器包裹左侧序号和文本，方便进行对齐管理
                const leftContainer = document.createElement('div');
                Object.assign(leftContainer.style, {
                    display: 'flex', alignItems: 'center', overflow: 'hidden', marginRight: '12px'
                });

                // 新增：美化的自增序号数字
                const numSpan = document.createElement('span');
                numSpan.innerText = String(index + 1).padStart(2, '0'); // 自动补零对齐
                Object.assign(numSpan.style, {
                    fontFamily: 'monospace', fontWeight: '700', color: '#71717A', // 优雅的暗灰色数字
                    marginRight: '10px', minWidth: '20px', textAlign: 'right', flexShrink: '0',
                    fontSize: '11px'
                });

                // 域名文本显示
                const textSpan = document.createElement('span');
                textSpan.innerText = host;
                Object.assign(textSpan.style, {
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    wordBreak: 'break-all', fontFamily: 'monospace', color: '#D4D4D8'
                });

                leftContainer.appendChild(numSpan);
                leftContainer.appendChild(textSpan);

                // 单项复制按钮
                const singleCopyBtn = document.createElement('button');
                singleCopyBtn.innerText = '复制';
                Object.assign(singleCopyBtn.style, {
                    backgroundColor: 'rgba(255,255,255,0.1)', color: '#E4E4E7', border: 'none',
                    padding: '2px 6px', borderRadius: '4px', fontSize: '10px', cursor: 'pointer',
                    flexShrink: '0', transition: 'all 0.15s'
                });

                singleCopyBtn.addEventListener('mouseenter', () => { singleCopyBtn.style.backgroundColor = '#10B981'; });
                singleCopyBtn.addEventListener('mouseleave', () => { singleCopyBtn.style.backgroundColor = 'rgba(255,255,255,0.1)'; });

                singleCopyBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    GM_setClipboard(host, 'text');
                    singleCopyBtn.innerText = '已复制';
                    singleCopyBtn.style.backgroundColor = '#059669';
                    setTimeout(() => {
                        singleCopyBtn.innerText = '复制';
                        singleCopyBtn.style.backgroundColor = 'rgba(255,255,255,0.1)';
                    }, 1000);
                });

                item.appendChild(leftContainer);
                item.appendChild(singleCopyBtn);
                listContainer.appendChild(item);
            });
        }

        // 确保挂载到页面上
        const interval = setInterval(() => {
            if (document.body) {
                clearInterval(interval);
                document.body.appendChild(triggerBtn);
                document.body.appendChild(panel);
            }
        }, 100);
    }

    initUI();
})();
