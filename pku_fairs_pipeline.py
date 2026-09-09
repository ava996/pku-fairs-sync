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

权限要求 (飞书自建应用需开通):
  base:record:read / base:record:write     记录读写(数据同步必需)
  base:view:read / base:view:write_only    视图读写(自动按自然周建视图必需, 缺失时只警告不中断)

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
        """分页拉取表内全部记录。field_ids 当前未使用(Feishu OpenAPI 字段投影规则复杂, 全量拉数据更稳)。"""
        path = f"/open-apis/bitable/v1/apps/{self.base_token}/tables/{self.table_id}/records"
        records, page_token = [], None
        while True:
            params = {"page_size": 500, "automatic_fields": "false"}
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
        """updates: [(record_id, {field: value}), ...]  单条 update 循环 (批量接口不稳定)。
        使用线程池并发以提升速度。"""
        import concurrent.futures
        path = lambda rid: f"/open-apis/bitable/v1/apps/{self.base_token}/tables/{self.table_id}/records/{rid}"
        def _do(item):
            rid, fields = item
            try:
                self._request("PUT", path(rid), payload={"fields": fields})
                return None
            except RuntimeError as e:
                return f"{rid}: {e}"

        errors = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            for err in ex.map(_do, updates):
                if err:
                    errors.append(err)
        if errors:
            raise RuntimeError(f"{len(errors)}/{len(updates)} 条更新失败:\n" + "\n".join(errors[:5]))


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


# ============ 时间范围(自然周标签) ============
def week_label(dt):
    """返回该日期所在自然周的标签, 形如 '9/14-9/20' (周一到周日)。

    取代旧的「当周/下周/未来/已结束」四段式, 改为按自然周(周一起始)标注,
    每一场宣讲会都归入其举办日期所在的那个自然周。
    """
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.month}/{monday.day}-{sunday.month}/{sunday.day}"


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
    # Feishu OpenAPI datetime 字段要求 Unix 毫秒时间戳(非字符串)
    start_ms = int(start_dt.timestamp() * 1000) if start else None
    end_ms = int(datetime.strptime(end, "%Y-%m-%d %H:%M:%S").timestamp() * 1000) if end else None
    return {
        "公司名称": real_name,
        "宣讲会标题": title,
        "举办时间": item.get("holdTimeExport", "") or "",
        "开始时间": start_ms,
        "结束时间": end_ms,
        "地点": item.get("fieldExport", "") or item.get("place", "") or "",
        "详情链接": f"[查看详情]({link})",
        "时间范围": week_label(start_dt),
        "推荐等级": level,
        "推荐理由": reason,
        "备注": note,
        "宣讲会ID": item["id"],
    }


# ============ 同步 ============
# ⚠️ 重要设计约束：部分更新机制
# 脚本更新记录时只提交 build_row() 返回的字段（公司名称/时间/地点/推荐等）。
# 「参加状态」等用户手动维护的字段不在 build_row 中，因此永不被脚本覆盖。
# 若未来新增用户手动字段，同样不要加进 build_row，否则每周更新会清掉用户标记。
def sync_to_feishu(rows, api):
    """对比已有记录: 新增缺失的, 更新已有的(部分更新, 不触碰手动标记字段)。"""
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


# ============ 自然周视图管理 ============
# 为每一个自然周标签自动维护一张视图, 视图按「时间范围 = 该周」筛选、按「开始时间」升序排序。
# 视图操作走 base/v3 OpenAPI, 需要应用具备 base:view:read / base:view:write_only 权限。
# 若权限缺失, 这里只打印警告、绝不中断流水线(数据同步仍然成功)。
# 视图字段显示顺序(与飞书 UI 手动调整一致: 参加状态紧跟举办时间)。
FIELD_ORDER = [
    "公司名称", "宣讲会标题", "举办时间", "参加状态", "开始时间", "结束时间",
    "地点", "详情链接", "时间范围", "推荐等级", "推荐理由", "宣讲会ID", "备注",
]


def _vid(v):
    """兼容 base/v3 与 bitable/v1 两种字段命名。"""
    return (v or {}).get("view_id") or (v or {}).get("id") or ""


def _vname(v):
    return (v or {}).get("view_name") or (v or {}).get("name") or ""


def list_views(api):
    """返回 {视图名: view_id}。"""
    path = f"/open-apis/base/v3/bases/{api.base_token}/tables/{api.table_id}/views"
    data = api._request("GET", path)
    views = data.get("views") or data.get("items") or []
    return {_vname(v): _vid(v) for v in views if _vname(v) and _vid(v)}


def create_view(api, name):
    path = f"/open-apis/base/v3/bases/{api.base_token}/tables/{api.table_id}/views"
    data = api._request("POST", path, payload={"name": name, "type": "grid"})
    # 兼容多种响应结构: data.view 对象 / data.views 数组 / data 本身即视图
    if isinstance(data.get("view"), dict) and _vid(data["view"]):
        return _vid(data["view"])
    if isinstance(data.get("views"), list) and data["views"] and _vid(data["views"][0]):
        return _vid(data["views"][0])
    return _vid(data)


def set_view_filter(api, view_id, week):
    """视图筛选: 时间范围 == 指定自然周(单选, 用 intersects + 选项名数组)。"""
    path = f"/open-apis/base/v3/bases/{api.base_token}/tables/{api.table_id}/views/{view_id}/filter"
    api._request("PUT", path, payload={
        "logic": "and",
        "conditions": [["时间范围", "intersects", [week]]],
    })


def set_view_sort(api, view_id):
    path = f"/open-apis/base/v3/bases/{api.base_token}/tables/{api.table_id}/views/{view_id}/sort"
    api._request("PUT", path, payload={"sort_config": [{"field": "开始时间", "desc": False}]})


def set_view_visible_fields(api, view_id):
    """设置视图字段显示顺序(参加状态紧跟举办时间), 同时控制可见字段。"""
    path = f"/open-apis/base/v3/bases/{api.base_token}/tables/{api.table_id}/views/{view_id}/visible_fields"
    api._request("PUT", path, payload={"visible_fields": FIELD_ORDER})


def ensure_week_views(api, week_labels):
    """确保每个自然周都有一张同名视图, 并配置好筛选/排序/字段顺序。

    week_labels: 去重后的自然周标签集合(如 {'9/14-9/20', '9/21-9/27'})。
    """
    try:
        existing = list_views(api)
    except RuntimeError as e:
        print(f"      ⚠️ 读取视图列表失败(缺少 base:view:read 权限?): {e}")
        return
    created = 0
    for week in sorted(week_labels):
        name = f"📅 {week}"
        view_id = existing.get(name)
        if not view_id:
            try:
                view_id = create_view(api, name)
                if not view_id:
                    raise RuntimeError("创建视图返回的 view_id 为空")
                created += 1
                print(f"      + 新建视图: {name}")
            except RuntimeError as e:
                print(f"      ⚠️ 新建视图 {name} 失败(缺少 base:view:write_only 权限?): {e}")
                continue
        try:
            set_view_filter(api, view_id, week)
            set_view_sort(api, view_id)
            set_view_visible_fields(api, view_id)
        except RuntimeError as e:
            print(f"      ⚠️ 配置视图 {name} 筛选/排序失败: {e}")
    print(f"      周视图就绪: 新建 {created} 张, 覆盖 {len(week_labels)} 个自然周")


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
        by_period[r["时间范围"]] = by_period.get(r["时间范围"], 0) + 1
        by_level[r["推荐等级"]] = by_level.get(r["推荐等级"], 0) + 1
    print(f"[2/4] 时间范围分布: {by_period}")
    print(f"      推荐等级分布: {by_level}")

    if args.dry_run:
        print("[dry-run] 不写入飞书。前 5 行:")
        for r in rows[:5]:
            print(f"      {r['开始时间']} | {r['公司名称']} | {r['地点']} | {r['推荐等级']}")
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

    week_labels = sorted({r["时间范围"] for r in rows})
    print(f"[4/4] 自然周视图管理 ({len(week_labels)} 个自然周: {', '.join(week_labels)})...")
    ensure_week_views(api, week_labels)

    # 本周与下周推荐场次(基于自然周标签)
    this_label = week_label(now)
    next_label = week_label(now + timedelta(days=7))
    focus = [r for r in rows if r["时间范围"] in (this_label, next_label) and r["推荐等级"] in ("🔥强烈推荐", "推荐")]
    if focus:
        print(f"\n⭐ 本周/下周({this_label} / {next_label})推荐场次 {len(focus)} 条:")
        for r in focus:
            start_str = datetime.fromtimestamp(r["开始时间"] / 1000).strftime("%Y-%m-%d %H:%M") if r["开始时间"] else "?"
            print(f"   {r['时间范围']} | {start_str} | {r['公司名称']} | {r['推荐等级']} | {r['推荐理由']}")


if __name__ == "__main__":
    main()
