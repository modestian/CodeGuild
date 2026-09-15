"""CLI：MVP 阶段以 CLI / API 验证完整流程（FR-UI-01 交付节奏）。

命令：
  codeguild serve               启动后端服务
  codeguild project-add         注册项目（本地 Git 仓库）
  codeguild run                 发起一次开发运行（可 --watch 实时观察）
  codeguild watch               观察运行事件流（SSE）
  codeguild status              查看运行状态与指标
  codeguild tasks               查看任务 DAG 状态
  codeguild diff                查看代码变更
  codeguild approve             提交人工审批（approve/reject/continue）
  codeguild sandbox-build       构建推荐沙箱镜像（含 pytest）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="CodeGuild CLI", no_args_is_help=True)
console = Console()

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def _client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=60)


def _fail(resp: httpx.Response) -> None:
    console.print(f"[red]HTTP {resp.status_code}[/red]: {escape(resp.text[:800])}")
    raise typer.Exit(code=1)


# =========================================================
# serve
# =========================================================


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """启动后端服务（FastAPI + SSE）。"""
    import uvicorn

    console.print(f"[green]启动服务[/green] http://{host}:{port}")
    uvicorn.run("app.main:create_app", factory=True, host=host, port=port, log_level="info")


# =========================================================
# project-add
# =========================================================


@app.command("project-add")
def project_add(
    name: str = typer.Option(..., help="项目名称"),
    repo: str = typer.Option(..., help="本地 Git 仓库路径"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="后端地址"),
):
    """注册项目。"""
    with _client(base_url) as client:
        resp = client.post("/projects", json={"name": name, "repo_path": str(Path(repo).resolve())})
        if resp.status_code != 200:
            _fail(resp)
        data = resp.json()
    console.print(Panel.fit(f"项目 ID: [bold cyan]{data['id']}[/bold cyan]\n名称: {data['name']}\n仓库: {data['repo_path']}", title="项目已创建"))


# =========================================================
# run
# =========================================================


def _watch(client: httpx.Client, run_id: str, until: Optional[set[str]] = None) -> str:
    """消费 SSE 事件流，打印人类可读进度。返回最终状态提示。"""
    terminal = {"completed", "failed", "rejected", "cancelled"}
    last_status = "unknown"
    with client.stream("GET", f"/runs/{run_id}/events", params={"follow": "true"}, timeout=None) as stream:
        event_type = ""
        for line in stream.iter_lines():
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                try:
                    payload = json.loads(line[len("data: "):])
                except ValueError:
                    continue
                msg = payload.get("message") or ""
                agent = payload.get("agent") or "-"
                seq = payload.get("seq", "")
                style = "dim"
                if event_type in {"tool_call"}:
                    style = "cyan"
                elif event_type in {"test_result", "validation_result"}:
                    style = "yellow"
                elif event_type in {"review_result", "commit_done", "run_finished"}:
                    style = "green"
                elif event_type in {"task_failed", "error", "run_failed"}:
                    style = "red"
                elif event_type in {"approval_required"}:
                    style = "bold magenta"
                if msg:
                    console.print(f"[{style}][{seq:>3}][{agent}][/][{style}]{escape(msg)}[/{style}]")
                if event_type in {"approval_required"}:
                    if until is not None:
                        return "approval_required"
                    console.print("[magenta]运行已暂停，等待人工审批：codeguild approve --run " + run_id + " --decision approve[/magenta]")
                    return "approval_required"
                if event_type in {"run_finished", "run_failed"}:
                    if until is not None:
                        # 继续消费以获取最终状态（简化：直接查询状态）
                        return "finished"
                    return "finished"
        # 流结束（run ended or replay finished)
        try:
            run = client.get(f"/runs/{run_id}").json()
            last_status = run.get("status", "unknown")
        except Exception:
            pass
    return last_status


@app.command()
def run(
    project: str = typer.Option(..., "--project", "-p", help="项目 ID"),
    request: str = typer.Option(..., "--request", "-r", help="自然语言开发需求"),
    watch: bool = typer.Option(True, help="实时观察事件流"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="后端地址"),
):
    """发起一次开发运行。"""
    with _client(base_url) as client:
        resp = client.post(f"/projects/{project}/runs", json={"request": request})
        if resp.status_code != 200:
            _fail(resp)
        run_data = resp.json()["run"]
        run_id = run_data["id"]
        console.print(Panel.fit(f"运行 ID: [bold cyan]{run_id}[/bold cyan]\n分支: {run_data.get('branch')}\n工作区: {run_data.get('workspace_path')}", title="运行已启动"))
        if watch:
            _watch(client, run_id)
        else:
            console.print(f"可使用 codeguild watch --run {run_id} 观察进度")


# =========================================================
# watch / status / tasks / diff
# =========================================================


@app.command()
def watch(
    run: str = typer.Option(..., "--run", help="运行 ID"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="后端地址"),
):
    """实时观察运行事件流（SSE）。"""
    with _client(base_url) as client:
        _watch(client, run)


@app.command()
def status(
    run: str = typer.Option(..., "--run", help="运行 ID"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="后端地址"),
):
    """查看运行状态与评估指标。"""
    with _client(base_url) as client:
        resp = client.get(f"/runs/{run}")
        if resp.status_code != 200:
            _fail(resp)
        data = resp.json()
    table = Table(title=f"运行 {run[:8]}", show_header=False)
    table.add_row("状态", data.get("status", ""))
    table.add_row("当前 Agent", data.get("current_agent", ""))
    table.add_row("分支", data.get("branch", ""))
    table.add_row("错误", escape((data.get("error") or "")[:300]))
    console.print(table)
    metrics = data.get("metrics") or {}
    if metrics:
        mt = Table(title="指标（Cost / Tokens / Tool Calls）", show_header=True)
        mt.add_column("项")
        mt.add_column("值")
        for key in (
            "input_tokens", "output_tokens", "cost_usd", "tool_calls", "agent_runs",
            "tasks_total", "tasks_completed", "test_pass_rate", "retry_count", "execution_seconds",
        ):
            if key in metrics:
                mt.add_row(key, str(metrics[key]))
        console.print(mt)


@app.command()
def tasks(
    run: str = typer.Option(..., "--run", help="运行 ID"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="后端地址"),
):
    """查看任务 DAG 状态。"""
    with _client(base_url) as client:
        resp = client.get(f"/runs/{run}/tasks")
        if resp.status_code != 200:
            _fail(resp)
        rows = resp.json().get("tasks", [])
    table = Table(show_header=True)
    for col in ("ID", "状态", "标题", "依赖", "尝试"):
        table.add_column(col)
    color = {
        "COMPLETED": "green", "FAILED": "red", "RUNNING": "yellow",
        "READY": "cyan", "BLOCKED": "magenta", "PENDING": "dim",
    }
    for t in rows:
        style = color.get(t.get("status", ""), "")
        table.add_row(
            t.get("id", ""),
            f"[{style}]{t.get('status', '')}[/{style}]",
            escape((t.get("title") or "")[:48]),
            ", ".join(t.get("dependencies") or []) or "-",
            str(t.get("attempts", 0)),
        )
    console.print(table)


@app.command()
def diff(
    run: str = typer.Option(..., "--run", help="运行 ID"),
    save: Optional[str] = typer.Option(None, help="保存到文件"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="后端地址"),
):
    """查看代码变更（Git Diff）。"""
    with _client(base_url) as client:
        resp = client.get(f"/runs/{run}/diff")
        if resp.status_code != 200:
            _fail(resp)
        data = resp.json()
    text = data.get("diff", "")
    if save:
        Path(save).write_text(text, encoding="utf-8")
        console.print(f"已保存到 {save}")
    else:
        console.print(text[:20000], markup=False, highlight=False)


# =========================================================
# approve
# =========================================================


@app.command()
def approve(
    run: str = typer.Option(..., "--run", help="运行 ID"),
    decision: str = typer.Option(..., help="approve | reject | continue"),
    note: str = typer.Option("", help="审批备注"),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="后端地址"),
):
    """提交人工审批。"""
    with _client(base_url) as client:
        resp = client.post(f"/runs/{run}/approve", json={"decision": decision, "note": note})
        if resp.status_code != 200:
            _fail(resp)
    console.print(f"[green]审批已提交: {decision}[/green]")
    console.print(f"继续观察： codeguild watch --run {run}")


# =========================================================
# sandbox-build
# =========================================================


@app.command("sandbox-build")
def sandbox_build(tag: str = typer.Option("multi-agent-sandbox:py312", help="镜像标签")):
    """构建推荐沙箱镜像（python:3.12 + pytest）。"""
    import subprocess

    dockerfile = Path(__file__).resolve().parent.parent / "sandbox" / "sandbox.Dockerfile"
    if not dockerfile.exists():
        console.print(f"[red]找不到 {dockerfile}[/red]")
        raise typer.Exit(1)
    cmd = ["docker", "build", "-t", tag, "-f", str(dockerfile), str(dockerfile.parent)]
    console.print(f"执行: {' '.join(cmd)}")
    code = subprocess.call(cmd)
    if code == 0:
        console.print(f"[green]镜像构建完成: {tag}[/green]（.env 中 SANDBOX_IMAGE={tag}）")
    else:
        console.print("[red]镜像构建失败[/red]")
        raise typer.Exit(code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
