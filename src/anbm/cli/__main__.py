"""ANBM CLI — 健康监控和修复工具。"""

import click

from anbm.cli.check import check_command
from anbm.cli.status import status_command
from anbm.cli.repair import repair_command


@click.group()
def cli():
    """ANBM — Agent-Native Browser Middleware CLI"""


cli.add_command(check_command)
cli.add_command(status_command)
cli.add_command(repair_command)


if __name__ == "__main__":
    cli()
