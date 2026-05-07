# BF-20260507-2：验证脚本及基准工具的边界情况崩溃

**报告日期**：2026-05-07

**修复版本**：v0.10.0-alpha.2

**严重程度**：Low（仅影响验证脚本，不影响核心引擎）

**状态**：已修复

---

## 现象

三个边缘情况导致验证脚本崩溃：

### 1. recorder.py ZeroDivisionError

当验证脚本在记录任何步骤前提前返回（如网络错误），`print_summary()` 中计算百分比时除零：

```
ZeroDivisionError: division by zero
    print(f"  成功步骤:     {succeeded} / {total}  ({succeeded/total*100:.0f}%)")
```

### 2. httpx 客户端超时过短

`verify_github.py` 的 httpx 客户端超时设为 30s，但服务端处理时间（包含浏览器导航 90s）远超此值，导致 `httpx.ReadTimeout`。

### 3. Reddit 默认测试 subreddit 不存在

`verify_reddit.py` 默认使用 `r/test` 测试，该 subreddit 可能已被 Reddit 移除或限制访问，导致 `net::ERR_CONNECTION_RESET`。

---

## 根因

1. **ZeroDivisionError**：`total` 为 0 时未做保护判断
2. **httpx 超时**：客户端超时与服务端实际处理时间不匹配
3. **r/test**：硬编码的默认值选择了不再可用的 subreddit

---

## 解决方案

| 问题 | 修复 |
|------|------|
| ZeroDivisionError | `succeeded/total` 前检查 `total` 是否为 0 |
| httpx 超时 | 30s → 120s |
| r/test 不存在 | 默认改为 `r/python` |
| 空响应 JSONDecodeError | 两个 verify 脚本均增加 HTTP 状态码检查 |

### 具体改动

`scripts/benchmark/recorder.py`：
```python
pct = f"{succeeded/total*100:.0f}%" if total else "N/A"
```

`scripts/verify_github.py`：
```python
async with httpx.AsyncClient(base_url=API_BASE, timeout=120, trust_env=False) as client:
# 增加: if resp.status_code != 200: print(...) + return False
```

`scripts/verify_reddit.py`：
```python
TEST_SUBREDDIT = os.environ.get("REDDIT_TEST_SUBREDDIT", "python")
# 增加 HTTP 状态码检查
```

---

## 涉及文件

- `scripts/benchmark/recorder.py` — 除零保护
- `scripts/verify_github.py` — httpx 超时 30→120s，状态码检查
- `scripts/verify_reddit.py` — 默认 subreddit 改为 python，状态码检查
