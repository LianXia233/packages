# tools — luci-app-homeproxy 翻译维护与部署工具

维护本仓库 LuCI 翻译（`*/po/zh_Hans/*.po` → 路由器 `.lmo`）的辅助脚本，纯 Python、无 OpenWrt 构建依赖。

## po2lmo.py — po → lmo 转换器

LuCI 运行时读取的翻译目录是 `.lmo` 格式（`/usr/lib/lua/luci/i18n/<app>.zh-cn.lmo`），构建期由官方 `po2lmo` 生成。本脚本是官方 `po2lmo.c` / `lmo.c` 的忠实移植，已在 luci-app-homeproxy 全量 po 上验证与官方工具输出**逐字节一致**（473 条条目 + blob 长度 + 索引全部吻合）。

```bash
py -I tools/po2lmo.py luci-app-homeproxy/po/zh_Hans/homeproxy.po homeproxy.zh-cn.lmo
py -I tools/po2lmo.py --verify homeproxy.zh-cn.lmo   # 解析回读，校验结构与排序
```

实现要点（与官方 C 语义一一对应）：

- key 哈希 = `sfh_hash(原始 msgid 字节, init=len)`；`val_id` = 复数形式数（普通条目为 1），不是值的哈希
- `key_id == val_id` 的条目跳过（即 msgstr 与 msgid 相同的原样翻译不入库）
- 空 msgstr（未翻译条目）跳过
- PO 反转义与 `extract_string()` 一致：只有 `\"` 和 `\\` 去掉反斜杠，`\n` 等序列保持字面量
- blob 按 4 字节对齐补零；索引 16 字节/条（key/val/offset/length 均大端）按 key 升序；文件尾 4 字节大端 = blob 长度

部署到路由器（ImmortalWrt/官方 OpenWrt 通用）：

```bash
SSHX_HOST=192.168.x.x SSHX_PASSWORD=... py -I tools/sshx.py \
    put homeproxy.zh-cn.lmo /usr/lib/lua/luci/i18n/homeproxy.zh-cn.lmo
```

替换后浏览器 Ctrl+F5 强刷（翻译目录 JS 有浏览器缓存）。

## scan_po.py — po 与源码一致性扫描

扫描 po 中全部 msgid 是否与源码 `_()` 字符串严格匹配，用于发现**翻译写了却永远不生效**的条目（典型成因：po 手工换行丢失行尾空格——PO 续行是直接拼接的，`"the provider then"` + `"controls"` 会拼成 `thencontrols`）。

```bash
py -I tools/scan_po.py luci-app-homeproxy
```

输出三类结果：

1. msgid 在源码中找不到的条目（疑似损坏/过期，附最接近的源码串与相似度）
2. fuzzy 标记的条目
3. 源码中存在但 po 缺条目的字符串（未翻译）

注意两类已知误报，命中后需人工复核：

- JS 源码里 `\'` 转义（po 中是真实撇号），相似度 1.0 但子串匹配失败
- 单个 `_()` 调用内部的 JS 字符串拼接（`'...' + '...'`），提取器只取第一个字面量

## sshx.py — 路由器 SSH 辅助

paramiko 封装，凭据全部走环境变量（Windows 下 sshpass/plink 均不可用，paramiko 最可靠）：

```bash
SSHX_HOST=192.168.x.x SSHX_USER=root SSHX_PASSWORD=... \
    py -I tools/sshx.py run "md5sum /usr/lib/lua/luci/i18n/homeproxy.zh-cn.lmo"
SSHX_HOST=... SSHX_PASSWORD=... py -I tools/sshx.py put local remote
SSHX_HOST=... SSHX_PASSWORD=... py -I tools/sshx.py get remote local
```

Git Bash 下注意：以 `/` 开头的参数会被 MSYS 改写成本地路径，命令前加 `MSYS_NO_PATHCONV=1`。

## 验证翻译是否生效

登录 LuCI 后拉取翻译目录接口，直接 grep 中文文案：

```bash
curl -s -c cj.txt -d 'luci_username=root&luci_password=***' http://路由IP/cgi-bin/luci/
curl -s -b cj.txt http://路由IP/cgi-bin/luci/admin/translations/zh-cn/homeproxy | grep 覆盖用于解析
```
