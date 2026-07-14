#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并多个规则 JSON 文件（direct / proxy / adblock 三组），
只保留 domain / domain_suffix / domain_keyword 三个键，
对每个键内部做去重 + 排序，最终统一 "version": 3。

配置文件：根目录 rules.json，格式如下（自由增删每组链接）：
{
  "direct": ["https://.../a.json", "https://.../b.json"],
  "proxy": ["https://.../c.json"],
  "adblock": ["https://.../d.json"]
}

输出文件位置：rules/direct.json
             rules/proxy.json
             rules/reject.json   <-- 注意：adblock 组输出文件名为 reject.json
"""

import json
import os
import sys
import urllib.request
import urllib.error

# ---------- 基本配置 ----------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "rules.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "rules")

# 配置文件里的组名 -> 输出文件名
GROUP_OUTPUT_NAME = {
    "direct": "direct.json",
    "proxy": "proxy.json",
    "adblock": "reject.json",
}

# 只保留这三个键，其余键一律忽略
KEEP_KEYS = ("domain", "domain_suffix", "domain_keyword")

OUTPUT_VERSION = 3

REQUEST_TIMEOUT = 20  # 秒
USER_AGENT = "rules-merger/1.0 (+github-actions)"


# ---------- 工具函数 ----------

def fetch_json(url: str):
    """下载并解析一个 JSON 文件，失败时打印警告并返回 None（不中断整体流程）。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
        return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"  [警告] 下载失败，已跳过: {url}\n         原因: {e}", file=sys.stderr)
    except json.JSONDecodeError as e:
        print(f"  [警告] JSON 解析失败，已跳过: {url}\n         原因: {e}", file=sys.stderr)
    return None


def load_config():
    """读取根目录 rules.json 配置文件，返回 {组名: [urls...]} 字典。"""
    if not os.path.isfile(CONFIG_PATH):
        print(f"[错误] 未找到配置文件: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[错误] 配置文件解析失败: {CONFIG_PATH}\n       原因: {e}", file=sys.stderr)
            sys.exit(1)

    if not isinstance(data, dict):
        print(f"[错误] 配置文件格式不对，最外层必须是对象: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    result = {}
    for group_name in GROUP_OUTPUT_NAME:
        urls = data.get(group_name, [])
        if not isinstance(urls, list):
            print(f"  [警告] 分组 {group_name} 的值不是数组，已忽略", file=sys.stderr)
            urls = []
        # 去掉空字符串 / 重复项，保持原有顺序
        seen = set()
        cleaned = []
        for u in urls:
            if isinstance(u, str) and u.strip() and u not in seen:
                seen.add(u)
                cleaned.append(u.strip())
        result[group_name] = cleaned
    return result


def merge_rule_objects(rule_objects):
    """
    将多个规则对象（每个对象最多含 domain / domain_suffix / domain_keyword）
    合并为一个对象，每个键内部去重 + 排序。
    忽略示例三种键之外的其他键。
    """
    merged = {key: set() for key in KEEP_KEYS}

    for obj in rule_objects:
        if not isinstance(obj, dict):
            continue
        for key in KEEP_KEYS:
            values = obj.get(key)
            if not values:
                continue
            if not isinstance(values, list):
                continue
            for v in values:
                if isinstance(v, str) and v.strip():
                    merged[key].add(v.strip())

    result = {}
    for key in KEEP_KEYS:
        if merged[key]:
            result[key] = sorted(merged[key])
    return result


def collect_rule_objects_from_source(data):
    """
    从一个下载到的 JSON 文件里取出 "rules" 列表（如果存在且是 list）。
    非法结构直接忽略，不中断整体流程。
    """
    if not isinstance(data, dict):
        return []
    rules = data.get("rules")
    if not isinstance(rules, list):
        return []
    return rules


# ---------- 主流程 ----------

def process_group(group_name: str, urls, output_filename: str):
    print(f"\n处理分组: {group_name} -> rules/{output_filename}")

    if not urls:
        print(f"  该组没有配置链接，跳过生成 {output_filename}")
        return

    all_rule_objects = []
    for url in urls:
        print(f"  下载: {url}")
        data = fetch_json(url)
        if data is None:
            continue
        objs = collect_rule_objects_from_source(data)
        if not objs:
            print(f"  [提示] 该文件中没有找到有效的 rules 数组: {url}")
            continue
        all_rule_objects.extend(objs)

    merged_obj = merge_rule_objects(all_rule_objects)

    if not merged_obj:
        print(f"  [警告] 合并结果为空，仍会写出空规则文件: {output_filename}")

    output_data = {
        "version": OUTPUT_VERSION,
        "rules": [merged_obj] if merged_obj else [],
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    for key in KEEP_KEYS:
        count = len(merged_obj.get(key, []))
        print(f"  {key}: {count} 条")
    print(f"  已写出: {output_path}")


def main():
    print("=== 规则合并脚本开始运行 ===")
    config = load_config()
    for group_name, output_filename in GROUP_OUTPUT_NAME.items():
        process_group(group_name, config.get(group_name, []), output_filename)
    print("\n=== 全部完成 ===")


if __name__ == "__main__":
    main()
