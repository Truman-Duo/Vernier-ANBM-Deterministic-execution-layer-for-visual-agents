"""anbm check — 健康检查命令。"""
import httpx
import click


@click.command(name="check")
@click.argument("adapter_id", required=False, default=None)
@click.option("--all", "-a", "check_all", is_flag=True, help="检查所有 adapter")
@click.option("--base-url", "-u", default="http://localhost:8000", help="API 基础 URL")
def check_command(adapter_id: str | None, check_all: bool, base_url: str):
    """对指定 adapter 执行健康检查。

    ADAPTER_ID: adapter 标识符，如 douban_movie。不指定时配合 --all 使用。
    """
    if check_all:
        _check_all(base_url)
    elif adapter_id:
        _check_one(base_url, adapter_id)
    else:
        click.echo("请指定 adapter_id 或使用 --all 检查全部。")
        raise click.Exit(1)


def _check_one(base_url: str, adapter_id: str):
    url = f"{base_url}/health/adapter/{adapter_id}/check"
    try:
        resp = httpx.post(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        click.echo(f"请求失败: {e}")
        return

    click.echo(f"\n=== {data.get('adapter_id', adapter_id)} 健康检查 ===")
    click.echo(f"  状态:        {_format_status(data.get('status', 'unknown'))}")
    click.echo(f"  版本:        {data.get('adapter_version', '?')}")
    click.echo(f"  检测状态:    {data.get('detected_state', '?')}")
    click.echo(f"  页面 URL:    {data.get('final_url', '?')}")
    click.echo(f"  耗时:        {data.get('response_time_ms', '?')}ms")

    reason = data.get("reason")
    if reason:
        click.echo(f"  原因:        {reason}")

    selectors = data.get("selector_results", [])
    if selectors:
        click.echo(f"\n  选择器检查 ({len(selectors)} 个):")
        for sr in selectors:
            icon = "✓" if sr.get("found") else "✗"
            click.echo(f"    {icon} [{sr.get('state', '?')}] {sr.get('selector', '?')}")
            if not sr.get("found") and sr.get("candidates"):
                click.echo(f"        候选: {', '.join(sr['candidates'][:3])}")

    error = data.get("raw_error")
    if error:
        click.echo(f"\n  错误: {error}")


def _check_all(base_url: str):
    url = f"{base_url}/health/adapters"
    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        click.echo(f"请求失败: {e}")
        return

    adapters = data.get("adapters", [])
    if not adapters:
        click.echo("未发现 adapter。")
        return

    click.echo(f"\n{'Adapter':<25} {'状态':<15} {'原因':<20} {'最近检查':<30}")
    click.echo("-" * 90)
    for a in adapters:
        status = _format_status(a.get("status", "unknown"))
        reason = a.get("reason") or ""
        checked = a.get("checked_at", "")[:19] if a.get("checked_at") else ""
        click.echo(f"{a.get('adapter_id', '?'):<25} {status:<15} {reason:<20} {checked:<30}")


def _format_status(status: str) -> str:
    colors = {
        "healthy": "green",
        "degraded": "yellow",
        "broken": "red",
        "unreachable": "red",
        "unknown": "blue",
    }
    color = colors.get(status, "white")
    return click.style(status, fg=color)
