#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北大就业中心宣讲会爬虫 + 飞书多维表格同步流水线 (GitHub Actions / 飞书 OpenAPI 版)

数据源: https://scc.pku.edu.cn/frontpage/pku/html/recruitmentFairList.html?fairType=1&
接口:   POST https://scc.pku.edu.cn/f/recruitmentFair/ajax_frontRecruitfair

仅依赖 Python 标准库; 飞书写入走 OpenAPI (HTTP), 不需要 lark-cli。

环境变量 (GitHub Secrets):
  FEISHU_APP_ID        飞书自建应用 app_id
  FEISHU_APP_SECRET    飞书自建应用 app_secret
  FEISHU_BASE_TOKEN    飞书多维表格 base_token (等同 app_token)
  FEISHU_TABLE_ID      目标 table_id
  SINCE_DATE           (可选) 过滤起始日期, 默认 2026-09-01

用法:  python3 pku_fairs_pipeline.py [--dry-run]
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ============ 配置区 ============
CONFIG = {
    "since_date": os.environ.get("SINCE_DATE", "2026-09-01"),
    "api_url": "https://scc.pku.edu.cn/f/recruitmentFair/ajax_frontRecruitfair",
    "page_size": 200,
    "base_url_prefix": "https://scc.pku.edu.cn",
    "workdir": Path(os.environ.get("WORKDIR", Path(__file__).resolve().parent)),
}

FEISHU = {
    "app_id": os.environ.get("FEISHU_APP_ID", ""),
    "app_secret": os.environ.get("FEISHU_APP_SECRET", ""),
    "base_token": os.environ.get("FEISHU_BASE_TOKEN", "WbtgbFhj5aULb0sWm9vcsTk1nlb"),
    "table_id": os.environ.get("FEISHU_TABLE_ID", "tbl8EIm0y8QrZeGC"),
    "host": "https://open.feishu.cn",
}

# ============ 用户偏好(推荐标注依据) ============
PREF = {
    "internet_ai": [
        "字节跳动", "字节", "抖音", "今日头条", "腾讯", "微信", "阿里巴巴", "阿里",
        "蚂蚁", "百度", "美团", "京东", "拼多多", "网易", "快手", "达佳", "嘀嘀",
        "华为", "荣耀", "小米", "维沃", "vivo", "OPPO", "哔哩哔哩", "B站", "Bilibili",
        "微软", "Microsoft", "谷歌", "Google", "苹果", "Apple", "英伟达", "NVIDIA",
        "亚马逊", "Amazon", "Meta", "OpenAI", "智谱", "月之暗面", "Moonshot",
        "MiniMax", "DeepSeek", "阶跃星辰", "百川智能", "商汤", "旷视", "科大讯飞",
        "360", "新浪", "携程", "滴滴", "贝壳找房", "小红书", "得物", "途虎", "联想",
        "浪潮", "米哈游", "地平线", "燧原", "沐曦", "比特大陆", "比亚迪", "宁德时代",
        "新能安",
    ],
    "soe": [
        "中信", "中金", "中银", "中债", "中投", "中保", "国家电网", "南方电网",
        "中石油", "中国石油", "中石化", "中国石化", "中海油", "中国海洋石油",
        "中核", "中航工业", "中国航空工业", "中电科", "中国电科", "中国电子",
        "航天科技", "航天科工", "中国航天", "中国兵器", "中船", "中国船舶",
        "国药", "华润", "招商局", "中远海运", "中国移动", "中国电信", "中国联通",
        "中兴通讯", "京东方", "中国人寿", "中国平安", "中国人保", "中国人民保险",
        "中国建筑", "中国中铁", "中国铁建", "中交", "中冶", "保利", "国家能源",
        "三峡", "中广核", "东方电气", "中国一汽", "一汽", "东风汽车", "长安汽车",
        "兵器工业", "中化", "中粮", "国投", "国机", "中国中车", "中铝", "五矿",
        "中煤", "神华",
    ],
    "bank": [
        "银行", "证券", "中金公司", "中信建投", "国泰君安", "华泰证券", "申万宏源",
        "交易所", "国开行", "国家开发银行", "进出口银行", "农发行", "基金管理",
        "中金所", "上交所", "深交所", "中国人民银行", "资产管理",
    ],
    "foreign": [
        "SEA", "Shopee", "Garena", "欧莱雅", "联合利华", "宝洁", "P&G", "辉瑞",
        "Pfizer", "雀巢", "西门子", "大众", "宝马", "奔驰", "戴姆勒", "丰田",
        "博世", "通用电气", "强生", "默沙东", "阿斯利康", "诺华", "罗氏", "陶氏",
        "巴斯夫", "三星", "索尼", "任天堂", "乐天", "WorldQuant", "IMC", "Optiver",
    ],
    "position_kw": ["产品经理", "产品", "管培", "管理培训", "培训生", "MT"],
}

PREF_LABEL = {
    "internet_ai": "互联网/AI头部公司",
    "soe": "央企/国企",
    "bank": "银行/金融机构",
    "foreign": "重点关注外企",
}

AGENCIES = {
    "前锦网络信息技术（上海）有限公司北京分公司": "前程无忧（前锦网络）",
    "北京网聘咨询有限公司": "智联招聘（北京网聘）",
    "北京领聘信息科技有限公司": "猎聘（北京领聘）",
}


def extract_real_company(title):
    """从标题中提取真实招聘公司名。失败返回 None。"""
    t = (title or "").strip()
    t = re.sub(r"^[“”\"'][^””\"']*[””\"']\s*", "", t)
    if "——" in t or "—" in t:
        parts = re.split(r"——|—", t)
        year_parts = [p for p in parts if re.search(r"20\d{2}", p)]
        if year_parts:
            t = year_parts[0]
    m = re.search(r"\s*20\d{2}", t)
    if m:
        t = t[: m.start()]
    t = t.strip(" \t、，,·-—")
    if not t or len(t) > 40 or re.search(r"20\d{2}", t):
        return None
    return t


# ============ 飞书 OpenAPI 客户端 ============
class FeishuAPI:
    def __init__(self):
        self.host = FEISHU["host"]
        self.base_token = FEISHU["base_token"]
        self.table_id = FEISHU["table_id"]
        self._token = None
        self._token_expires = 0

    def _get_token(self):
        """获取/刷新 tenant_access_token (2 小时有效, 提前 5 分钟刷新)。"""
        if self._token and time.time() < self._token_expires - 300:
            return self._token
        url = f"{self.host}/open-apis/auth/v3/tenant_access_token/internal"
        body = json.dumps({"app_id": FEISHU["app_id"], "app_secret": FEISHU["app_secret"]}).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
        self._token = data["tenant_access_token"]
        self._token_expires = time.time() + data.get("expire", 7200)
        return self._token

    def _request(self, method, path, payload=None, params=None, retry=True):
        url = f"{self.host}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", "ignore")
            # 401/99991: token 失效, 强制刷新后重试一次
            if retry and e.code in (401,):
                self._token = None
                return self._request(method, path, payload, params, retry=False)
            raise RuntimeError(f"飞书 API 失败 {method} {path}: HTTP {e.code} {body_text[:500]}")
        if body.get("code") not in (0, None):
            # 99991663 / 99991 鉴权类: 重试一次
            if retry and body.get("code") in (99991663, 99991668, 99991):
                self._token = None
                return self._request(method, path, payload, params, retry=False)
            raise RuntimeError(f"飞书 API 业务错误 {method} {path}: {body}")
        return body.get("data", {})

    def list_records(self, field_ids=None):
        """分页拉取表内全部记录, 投影到指定字段。"""
        path = f"/open-apis/bitable/v1/apps/{self.base_token}/tables/{self.table_id}/records"
        records, page_token = [], None
        while True:
            params = {"page_size": 500, "automatic_fields": "false"}
            if field_ids:
                params["field_names"] = ",".join(field_ids)
            if page_token:
                params["page_token"] = page_token
            data = self._request("GET", path, params=params)
            items = data.get("items") or []
            for it in items:
                fields = it.get("fields", {})
                # 文本字段若为列表(URL 类型), 拼接; 否则取字符串
                normalized = {}
                for k, v in fields.items():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        normalized[k] = "".join(seg.get("text", "") for seg in v)
                    elif isinstance(v, list):
                        normalized[k] = v  # select 类
                    else:
                        normalized[k] = v
                normalized["record_id"] = it["record_id"]
                records.append(normalized)
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return records

    def batch_create(self, records):
        """records: [{field_name: value, ...}, ...]  最多 1000/批。"""
        path = f"/open-apis/bitable/v1/apps/{self.base_token}/tables/{self.table_id}/records/batch_create"
        all_ids, BATCH = [], 1000
        for i in range(0, len(records), BATCH):
            chunk = records[i:i + BATCH]
            data = self._request("POST", path, payload={"records": [{"fields": r} for r in chunk]})
            all_ids.extend(r["record_id"] for r in data.get("records") or [])
        return all_ids

    def batch_update(self, updates):
        """updates: [(record_id, {field: value}), ...]  最多 1000/批。"""
        path = f"/open-apis/bitable/v1/apps/{self.base_token}/tables/{self.table_id}/records/batch_update"
        BATCH = 1000
        for i in range(0, len(updates), BATCH):
            chunk = updates[i:i + BATCH]
            payload_records = [{"record_id": rid, "fields": fields} for rid, fields in chunk]
            self._request("PUT", path, payload={"records": payload_records})


# ============ 爬取 ============
def fetch_all():
    """分页拉取全部宣讲会原始数据, 按宣讲会ID去重。"""
    all_items, page = [], 1
    while True:
        body = urllib.parse.urlencode(
            {"pageNo": page, "pageSize": CONFIG["page_size"], "fairType": 1, "title": ""}
        ).encode()
        req = urllib.request.Request(
            CONFIG["api_url"], data=body,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://scc.pku.edu.cn/frontpage/pku/html/recruitmentFairList.html?fairType=1&",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        if payload.get("state") != 1:
            raise RuntimeError(f"接口返回异常: {payload.get('msg')}")
        obj = payload["object"]
        all_items.extend(obj.get("list") or [])
        if page >= obj.get("totalPage", 1):
            break
        page += 1
    dedup = {}
    for it in all_items:
        dedup[it["id"]] = it
    return list(dedup.values())


# ============ 推荐计算 ============
def compute_recommendation(real_name, title):
    name = real_name or ""
    bucket, company_reason = None, None
    low = name.lower()
    for b in ("internet_ai", "bank", "soe", "foreign"):
        for kw in PREF[b]:
            if kw.lower() in low:
                bucket = b
                company_reason = f"{PREF_LABEL[b]}（匹配「{kw}」）"
                break
        if bucket:
            break
    pos_kw = next((kw for kw in PREF["position_kw"] if kw in title), None)
    pos_reason = f"标题含「{pos_kw}」，与目标岗位（产品经理/管培生）匹配" if pos_kw else ""
    if bucket and pos_kw:
        return "🔥强烈推荐", f"{company_reason}；{pos_reason}"
    if bucket:
        return "推荐", company_reason
    if pos_kw:
        return "推荐", pos_reason
    return "一般", ""


# ============ 时间范围 ============
def week_bounds(now):
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday, monday + timedelta(days=7), monday + timedelta(days=14)


def compute_period(start_dt, now):
    mon1, mon2, mon3 = week_bounds(now)
    if start_dt < now:
        return "已结束"
    if start_dt < mon2:
        return "当周"
    if start_dt < mon3:
        return "下周"
    return "未来"


# ============ 行构造 ============
def build_row(item, now):
    start = item.get("startTime", "") or ""
    end = item.get("endTime", "") or ""
    start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S") if start else now
    org_name = (item.get("corporationinfo") or {}).get("name", "") or item.get("title", "")
    title = item.get("title", "") or ""
    link = CONFIG["base_url_prefix"] + (item.get("url", "") or "")

    real_name, note = org_name, ""
    if org_name in AGENCIES:
        extracted = extract_real_company(title)
        if extracted:
            real_name = extracted
            note = f"本场由{AGENCIES[org_name]}代理发布，公司名从标题提取"
        else:
            note = f"本场由{AGENCIES[org_name]}代理发布，标题无法解析公司名，公司名称显示为代理机构"

    level, reason = compute_recommendation(real_name, title)
    return {
        "公司名称": real_name,
        "宣讲会标题": title,
        "举办时间": item.get("holdTimeExport", "") or "",
        "开始时间": start or None,
        "结束时间": end or None,
        "地点": item.get("fieldExport", "") or item.get("place", "") or "",
        "详情链接": f"[查看详情]({link})",
        "时间范围": [compute_period(start_dt, now)],
        "推荐等级": [level],
        "推荐理由": reason,
        "备注": note,
        "宣讲会ID": item["id"],
    }


# ============ 同步 ============
def sync_to_feishu(rows, api):
    """对比已有记录: 新增缺失的, 更新已有的。"""
    existing = api.list_records(field_ids=["宣讲会ID"])
    by_id = {}
    for rec in existing:
        fid = rec.get("宣讲会ID") or ""
        if isinstance(fid, str) and fid:
            by_id[fid] = rec["record_id"]
    to_create, to_update = [], []
    for row in rows:
        rid = by_id.get(row["宣讲会ID"])
        if rid:
            to_update.append((rid, dict(row)))
        else:
            to_create.append(row)
    created_ids = api.batch_create(to_create) if to_create else []
    if to_update:
        api.batch_update(to_update)
    return {"created": len(created_ids), "updated": len(to_update), "total_existing": len(by_id)}


# ============ 主流程 ============
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    now = datetime.now()
    print(f"[1/4] 爬取北大就业中心宣讲会... (now={now:%Y-%m-%d %H:%M})")
    raw = fetch_all()
    since = CONFIG["since_date"]
    future = [it for it in raw if (it.get("startTime") or "") >= since]
    print(f"      全量 {len(raw)} 条, {since} 之后 {len(future)} 条")

    rows = [build_row(it, now) for it in future]
    rows.sort(key=lambda r: r["开始时间"] or "")

    by_period, by_level = {}, {}
    for r in rows:
        by_period[r["时间范围"][0]] = by_period.get(r["时间范围"][0], 0) + 1
        by_level[r["推荐等级"][0]] = by_level.get(r["推荐等级"][0], 0) + 1
    print(f"[2/4] 时间范围分布: {by_period}")
    print(f"      推荐等级分布: {by_level}")

    if args.dry_run:
        print("[dry-run] 不写入飞书。前 5 行:")
        for r in rows[:5]:
            print(f"      {r['开始时间']} | {r['公司名称']} | {r['地点']} | {r['推荐等级'][0]}")
        return

    print(f"[3/4] 同步飞书多维表格...")
    if not FEISHU["app_id"] or not FEISHU["app_secret"]:
        raise SystemExit(
            "ERROR: 缺少 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量。\n"
            "请在 GitHub Secrets 配置(参考 README), 或在本地用 export 设置。"
        )
    api = FeishuAPI()
    stats = sync_to_feishu(rows, api)
    print(f"      新增 {stats['created']} 条, 更新 {stats['updated']} 条, 表内已有 {stats['total_existing']} 条")

    focus = [r for r in rows if r["时间范围"][0] in ("当周", "下周") and r["推荐等级"][0] in ("🔥强烈推荐", "推荐")]
    print("[4/4] 完成。")
    if focus:
        print(f"\n⭐ 当周/下周推荐场次 {len(focus)} 条:")
        for r in focus:
            print(f"   {r['时间范围'][0]} | {r['开始时间']} | {r['公司名称']} | {r['推荐等级'][0]} | {r['推荐理由']}")


if __name__ == "__main__":
    main()
