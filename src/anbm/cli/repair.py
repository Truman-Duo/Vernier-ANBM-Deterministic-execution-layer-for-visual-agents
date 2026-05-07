"""anbm repair — 交互式选择器修复向导。"""
import json
import os
import shutil
import httpx
import click

REPAIR_TEMP = {}


def _load_manifest(adapter_id: str) -> dict | None:
    """从本地文件系统加载 manifest。"""
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "adapters")
    )
    path = os.path.join(base, adapter_id, "manifest.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _patch_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) == 3:
        parts[2] = str(int(parts[2]) + 1)
    return ".".join(parts)


def _read_handler(adapter_id: str) -> str | None:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "adapters")
    )
    path = os.path.join(base, adapter_id, "handler.py")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_handler(adapter_id: str, content: str) -> None:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "adapters")
    )
    path = os.path.join(base, adapter_id, "handler.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _write_manifest(adapter_id: str, manifest: dict) -> None:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "adapters")
    )
    path = os.path.join(base, adapter_id, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _get_handler_path(adapter_id: str) -> str:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "adapters")
    )
    return os.path.join(base, adapter_id, "handler.py")


@click.command(name="repair")
@click.argument("adapter_id")
@click.option("--dry-run", is_flag=True, help="只展示诊断，不执行任何写入")
@click.option("--reason", default=None, help="修复原因描述")
@click.option("--base-url", "-u", default="http://localhost:8000", help="API 基础 URL")
def repair_command(adapter_id: str, dry_run: bool, reason: str | None, base_url: str):
    """对 adapter 执行交互式选择器修复。

    ADAPTER_ID: adapter 标识符，如 douban_movie。
    """
    # 阶段 0: 诊断摘要
    click.echo(f"\n=== 诊断: {adapter_id} ===")
    click.echo("正在执行健康检查...")

    url = f"{base_url}/health/adapter/{adapter_id}/check"
    try:
        resp = httpx.post(url, timeout=30)
        resp.raise_for_status()
        report = resp.json()
    except httpx.HTTPError as e:
        click.echo(f"健康检查失败: {e}")
        click.echo("请确保服务正在运行。")
        return

    status = report.get("status", "unknown")
    click.echo(f"  状态: {status}")
    click.echo(f"  原因: {report.get('reason', '无')}")
    click.echo(f"  检测状态: {report.get('detected_state', '?')}")

    failed_selectors = [
        sr for sr in report.get("selector_results", []) if not sr.get("found")
    ]

    if not failed_selectors:
        click.echo(click.style("\n没有需要修复的选择器。适配器状态正常。", fg="green"))
        return

    click.echo(f"\n  发现 {len(failed_selectors)} 个失效选择器:")
    for i, sr in enumerate(failed_selectors, 1):
        click.echo(f"    {i}. [{sr['state']}] {sr['selector']}")

    if dry_run:
        click.echo(click.style("\n[dry-run] 诊断完成，未执行任何写入。", fg="yellow"))
        return

    if not click.confirm("\n是否进入修复流程?", default=True):
        click.echo("已取消。")
        return

    global REPAIR_TEMP
    REPAIR_TEMP = {}

    # 阶段 1: 逐选择器修复
    click.echo("\n=== 阶段 1: 逐选择器修复 ===")
    replacements = {}

    for sr in failed_selectors:
        selector = sr["selector"]
        state = sr["state"]
        candidates = sr.get("candidates", [])

        click.echo(f"\n  选择器: [{state}] {selector}")

        if not candidates:
            click.echo("    无候选建议。")
            if click.confirm("    输入自定义选择器?", default=False):
                custom = click.prompt("    新选择器", default="")
                if custom.strip():
                    replacements[selector] = custom.strip()
            continue

        click.echo(f"    候选列表 ({len(candidates)} 个):")

        # 所有候选均为 SelectorCandidate dict 格式
        parsed_candidates = [
            {
                "selector": cand.get("selector", str(cand)),
                "source": cand.get("source", "css_similar"),
                "similarity": cand.get("similarity"),
            }
            for cand in candidates
        ]

        for i, pc in enumerate(parsed_candidates, 1):
            sim = pc["similarity"]
            sim_str = f"相似度 {sim:.2f}" if sim is not None else "—          "
            source_tag = pc["source"]
            if source_tag == "llm_suggested":
                source_display = click.style(f"[{source_tag} ⚠ 请仔细核实]", fg="red")
                color = "cyan"
            elif source_tag == "aria_candidate":
                source_display = click.style(f"[{source_tag}]", fg="blue")
                color = "green" if (sim is not None and sim >= 0.5) else "yellow"
            else:
                source_display = click.style(f"[{source_tag}]", fg="white")
                color = "green" if (sim is not None and sim >= 0.5) else "yellow"
            click.echo(
                f"      {i}. {click.style(pc['selector'], fg=color)}  {sim_str}  {source_display}"
            )

        max_sim = max(
            (pc["similarity"] for pc in parsed_candidates if pc["similarity"] is not None),
            default=0,
        )
        if len(candidates) > 5 or max_sim < 0.5:
            click.echo(
                click.style(
                    "    警告: 候选过多或相似度偏低，建议在浏览器中打开页面确认。",
                    fg="yellow",
                )
            )

        choice = click.prompt(
            "    选择序号 (输入 0 跳过, c 自定义)",
            default="0",
        )

        if choice == "0":
            click.echo("    跳过此选择器。")
        elif choice.lower() == "c":
            custom = click.prompt("    新选择器", default="")
            if custom.strip():
                replacements[selector] = custom.strip()
                click.echo(f"    已选择: {custom.strip()}")
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(parsed_candidates):
                    chosen = parsed_candidates[idx]["selector"]
                    replacements[selector] = chosen
                    click.echo(f"    已选择: {chosen}")
                else:
                    click.echo("    序号无效，跳过。")
            except ValueError:
                click.echo("    输入无效，跳过。")

    if not replacements:
        click.echo("\n未选择任何替换。不执行写入。")
        return

    # 阶段 2: 验证阶段 (mock 检测)
    click.echo("\n=== 阶段 2: 验证 ===")
    click.echo(f"  待替换: {len(replacements)} 个选择器")

    if not click.confirm("是否继续应用更改?", default=True):
        click.echo("已取消。")
        return

    REPAIR_TEMP["replacements"] = replacements

    # 阶段 3: 确认写入
    click.echo("\n=== 阶段 3: 确认写入 ===")

    manifest = _load_manifest(adapter_id)
    if manifest is None:
        click.echo(f"错误: 无法加载 {adapter_id} 的 manifest.json")
        return

    old_version = manifest.get("version", "0.0.0")
    new_version = _patch_version(old_version)

    click.echo(f"  manifest 版本: {old_version} → {new_version}")
    click.echo(f"  写入前备份: handler.py.bak")

    for old_sel, new_sel in replacements.items():
        click.echo(f"  handler.py: {old_sel} → {new_sel}")

    if not click.confirm("确认写入?", default=True):
        click.echo("已取消。")
        return

    # 执行写入
    handler_content = _read_handler(adapter_id)
    if handler_content is None:
        click.echo(f"错误: 无法加载 {adapter_id} 的 handler.py")
        return

    handler_path = _get_handler_path(adapter_id)
    try:
        shutil.copy2(handler_path, handler_path + ".bak")
    except OSError as e:
        click.echo(f"备份失败: {e}")
        return

    try:
        for old_sel, new_sel in replacements.items():
            # Replace both single and double quoted versions
            for quote in ('"', "'"):
                old_q = f"{quote}{old_sel}{quote}"
                new_q = f"{quote}{new_sel}{quote}"
                handler_content = handler_content.replace(old_q, new_q)

        _write_handler(adapter_id, handler_content)

        if manifest:
            manifest["version"] = new_version
            _write_manifest(adapter_id, manifest)

        click.echo(click.style("\n写入完成!", fg="green"))
        click.echo(f"  备份: {handler_path}.bak")
        click.echo(f"  handler.py: 已更新选择器")
        click.echo(f"  manifest.json: 版本已更新为 {new_version}")
        click.echo(click.style("\n建议运行对应集成测试验证: pytest tests/integration/test_*{adapter_id}* -v", fg="blue"))
    except Exception as e:
        click.echo(click.style(f"\n写入失败: {e}", fg="red"))
        click.echo("正在从备份恢复...")
        try:
            shutil.copy2(handler_path + ".bak", handler_path)
            click.echo("已恢复。")
        except OSError as restore_err:
            click.echo(f"恢复失败: {restore_err}")
            click.echo(f"请手动恢复: cp {handler_path}.bak {handler_path}")
