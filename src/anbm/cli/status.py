"""anbm status — 状态摘要命令。"""
import httpx
import click


@click.command(name="status")
@click.option("--base-url", "-u", default="http://localhost:8000", help="API 基础 URL")
def status_command(base_url: str):
    """显示所有 adapter 的当前状态摘要。"""
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

    all_ok = all(a.get("status") == "healthy" for a in adapters)
    for a in adapters:
        status = a.get("status", "unknown")
        icon = "✓" if status == "healthy" else "✗"
        colored = click.style(status, fg="green" if status == "healthy" else "red")
        click.echo(f"  {icon} {a.get('adapter_id', '?'):<25} {colored}")

    if all_ok:
        click.echo(click.style("\n所有 adapter 运行正常。", fg="green"))
