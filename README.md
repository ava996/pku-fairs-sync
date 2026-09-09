# 北大宣讲会周更流水线 (GitHub Actions)

每**周日 08:00（北京时间）**自动拉取北京大学就业指导服务中心宣讲会数据，过滤 2026-09-01 及之后的场次，按真实公司名去重，基于用户偏好（互联网/AI 头部、央国企、银行金融、外企关注名单；岗位：产品经理/管培生）标注推荐等级，同步到飞书多维表格。

## 架构

```
GitHub Actions (cron 0 0 * * 0 UTC = 周日08:00 北京时间)
        │
        ▼
pku_fairs_pipeline.py (纯 Python 标准库)
        │  ① 拉取北大宣讲会接口
        │  ② 过滤 startTime >= SINCE_DATE
        │  ③ 代理场次从标题提取真实公司
        │  ④ 按偏好匹配推荐等级
        │  ⑤ 按"运行当天"重算当周/下周/未来/已结束
        ▼
飞书多维表格「北大宣讲会日程」(https://my.feishu.cn/wiki/RLgOwdgXkiEXGuktf6LczNnsn5f)
```

## 一次性配置（约 5 分钟）

### 1. 创建飞书自建应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app) → **创建企业自建应用**
2. 名称如 `pku-fairs-sync`，图标随意
3. 左侧 **权限管理** → 搜索并开通 `bitable:app` (含读+写)
4. 左侧 **版本管理与发布** → 创建版本 → 提交发布（管理员审批一次即可）
5. 回到 **应用详情**，记录：
   - **App ID**（形如 `cli_xxx`）
   - **App Secret**（点击"查看"获取）

### 2. 把应用加入 Base

1. 打开 [北大宣讲会日程 Base](https://my.feishu.cn/wiki/RLgOwdgXkiEXGuktf6LczNnsn5f)
2. 右上角 **分享** → **添加协作者**
3. 搜索刚创建的应用名 → 勾选 **可编辑** → 确认

### 3. 在 GitHub 仓库配 Secrets

1. 在本仓库页面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. 依次添加：
   | 名称 | 值 |
   |---|---|
   | `FEISHU_APP_ID` | 第 1 步拿到的 App ID |
   | `FEISHU_APP_SECRET` | 第 1 步拿到的 App Secret |
   | `FEISHU_BASE_TOKEN` | `WbtgbFhj5aULb0sWm9vcsTk1nlb`（移动到知识库后不变） |
   | `FEISHU_TABLE_ID` | `tbl8EIm0y8QrZeGC` |
3. （可选）**Variables** 标签下加 `SINCE_DATE` = `2026-09-01`

### 4. 推送代码

```bash
cd pku-fairs-repo
git remote add origin git@github.com:iamfine/pku-fairs-sync.git
git branch -M main
git add -A
git commit -m "init: 北大宣讲会周更流水线"
git push -u origin main
```

### 5. 触发测试

GitHub 仓库 → **Actions** 标签 → 左侧 **北大宣讲会周更** → **Run workflow** → 勾选 dry_run 测试，确认 OK 后再触发正式 run。

## 本地调试

```bash
export FEISHU_APP_ID="cli_xxx"
export FEISHU_APP_SECRET="xxx"
export FEISHU_BASE_TOKEN="WbtgbFhj5aULb0sWm9vcsTk1nlb"
export FEISHU_TABLE_ID="tbl8EIm0y8QrZeGC"
python3 pku_fairs_pipeline.py --dry-run
```

去掉 `--dry-run` 即可正式同步。

## 字段说明

| 飞书字段 | 类型 | 说明 |
|---|---|---|
| 公司名称 | 文本 | 真实招聘公司（代理场次从标题提取） |
| 宣讲会标题 | 文本 | 原始标题 |
| 举办时间 | 文本 | 原始时间字符串 |
| 开始时间 | 日期 | 排序字段 |
| 结束时间 | 日期 | |
| 地点 | 文本 | |
| 详情链接 | 文本 | Markdown 链接 |
| 时间范围 | 单选 | 当周 / 下周 / 未来 / 已结束 |
| 推荐等级 | 单选 | 🔥强烈推荐 / 推荐 / 一般 |
| 推荐理由 | 文本 | 命中依据 |
| 备注 | 文本 | 代理发布说明等 |
| 参加状态 | 单选 | **手动标记**：⭐想参加 / 📅已报名 / ✅已参加 / ❌不去了。脚本更新不覆盖 |
| 宣讲会ID | 文本 | 去重键 |

## 更新机制

- **全量爬取 + 按需写入**：每次运行拉取接口全部数据，按"宣讲会ID"与表内比对，新增缺失记录、部分更新已有记录
- **部分更新**：脚本只提交自己管理的字段（时间/地点/推荐等），**用户手动维护的字段（参加状态）永不被覆盖**
- **时间标签重算**：每次运行以当天为基准重算"当周/下周/未来/已结束"

## 视图

- **全部宣讲会**（默认，按开始时间升序）
- **📅当周宣讲会**（filter `时间范围=当周`）
- **📅下周宣讲会**（filter `时间范围=下周`）
- **⭐推荐场次**（filter `推荐等级=🔥强烈推荐/推荐`）

## 修改偏好

编辑 `pku_fairs_pipeline.py` 顶部 `PREF` 字典里的关键词（互联网/AI、央国企、银行、外企、岗位），commit & push 即可。

## 停用 / 删除

- 暂停：仓库 → Actions → 北大宣讲会周更 → 右上角 `...` → **Disable workflow**
- 彻底删除：删除 `.github/workflows/weekly-fairs.yml` 并清空 Secrets
