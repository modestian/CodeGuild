"""SandboxManager：Docker 沙箱执行（含本地开发回退）。

对应需求：FR-SB-01~05、NFR-SEC-01/03：
- 所有代码执行必须运行在隔离环境：Agent → Harness → Sandbox Manager → Docker Container → Command
- CPU / 内存限制与执行超时
- 文件系统隔离（仅挂载工作区）、网络权限控制、Environment Variables 管理
- Secret Isolation（凭证不暴露给执行代码）
- 默认禁止访问 Host filesystem / SSH Key / Production DB / Cloud Credentials / 私有环境变量
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from app.config import Settings


class SandboxResult(BaseModel):
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: float = 0.0
    mode: str = "docker"


class SandboxError(RuntimeError):
    pass


class SandboxManager(ABC):
    mode: str = "abstract"

    @abstractmethod
    async def run(
        self,
        command: str,
        cwd: Path,
        timeout: Optional[float] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:  # pragma: no cover
        ...

    @abstractmethod
    async def check_available(self) -> tuple[bool, str]:  # pragma: no cover
        ...


# =========================================================
# Docker 沙箱（默认，FR-SB-01）
# =========================================================


class DockerSandbox(SandboxManager):
    mode = "docker"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._available: Optional[tuple[bool, str]] = None

    def _docker(self) -> str:
        return shutil.which("docker") or "docker"

    async def check_available(self) -> tuple[bool, str]:
        if self._available is not None:
            return self._available
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker(),
                "version",
                "--format",
                "{{.Server.Version}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
            if proc.returncode == 0:
                self._available = (True, stdout.decode(errors="ignore").strip())
            else:
                self._available = (False, f"Docker daemon 不可用: {stderr.decode(errors='ignore').strip()[:300]}")
        except FileNotFoundError:
            self._available = (False, "未找到 docker 命令，请安装 Docker Desktop")
        except asyncio.TimeoutError:
            self._available = (False, "docker version 超时，Docker daemon 可能未启动")
        return self._available

    async def _kill_container(self, name: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker(), "kill", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
        except Exception:  # noqa: BLE001
            pass

    async def run(
        self,
        command: str,
        cwd: Path,
        timeout: Optional[float] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        ok, detail = await self.check_available()
        if not ok:
            raise SandboxError(
                f"{detail}。可安装/启动 Docker，或在开发调试时设置 SANDBOX_MODE=local（不安全，仅供本地开发）"
            )
        timeout = timeout or self.settings.sandbox_timeout_seconds
        cwd = cwd.resolve()
        container_name = f"copilot-sbx-{uuid.uuid4().hex[:10]}"
        workspace_mount = str(cwd).replace("\\", "/")

        # Secret Isolation：不继承宿主环境，仅注入白名单与显式允许的变量（FR-SB-04/05）
        env_args: list[str] = []
        base_env = {
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "HOME": "/root",
        }
        if extra_env:
            base_env.update(extra_env)
        for key, value in base_env.items():
            env_args += ["-e", f"{key}={value}"]

        shell_command = command
        if self.settings.sandbox_setup_command:
            shell_command = f"{self.settings.sandbox_setup_command} && {command}"

        args = [
            self._docker(),
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            self.settings.sandbox_network,
            "--cpus",
            str(self.settings.sandbox_cpu_limit),
            "--memory",
            self.settings.sandbox_memory_limit,
            "--pids-limit",
            "512",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "-v",
            f"{workspace_mount}:/workspace",
            "-w",
            "/workspace",
            *env_args,
            self.settings.sandbox_image,
            "sh",
            "-lc",
            shell_command,
        ]

        started = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            await self._kill_container(container_name)
            try:
                stdout, stderr = await proc.communicate()
            except Exception:  # noqa: BLE001
                stdout, stderr = b"", b""
        duration = (time.perf_counter() - started) * 1000

        return SandboxResult(
            command=command,
            exit_code=-1 if timed_out else int(proc.returncode or 0),
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            timed_out=timed_out,
            duration_ms=round(duration, 2),
            mode="docker",
        )


# =========================================================
# 本地沙箱（仅开发调试，显式开启才生效）
# =========================================================


class LocalSandbox(SandboxManager):
    """直接在本机子进程执行。仅供开发调试（不满足安全验收要求）。"""

    mode = "local"

    # Windows 运行 Python 所需的最小环境变量白名单
    _KEEP = {
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "PATHEXT",
        "COMSPEC",
        "TEMP",
        "TMP",
        "WINDIR",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "USERNAME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMFILES",
        "PROGRAMDATA",
    }

    def __init__(self, settings: Settings):
        self.settings = settings

    async def check_available(self) -> tuple[bool, str]:
        return True, "local 模式（不安全，仅开发调试）"

    def _scrubbed_env(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            if key.upper() in self._KEEP:
                env[key] = value
        # 防御：剔除疑似密钥变量
        for key in list(env):
            upper = key.upper()
            if any(k in upper for k in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")):
                env.pop(key, None)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if extra:
            env.update(extra)
        return env

    async def run(
        self,
        command: str,
        cwd: Path,
        timeout: Optional[float] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        timeout = timeout or self.settings.sandbox_timeout_seconds
        cwd = cwd.resolve()
        full_command = command
        if self.settings.sandbox_setup_command:
            full_command = f"{self.settings.sandbox_setup_command} && {command}"

        def _exec() -> tuple[int, str, str, bool]:
            import subprocess

            try:
                proc = subprocess.run(
                    full_command,
                    shell=True,
                    cwd=str(cwd),
                    env=self._scrubbed_env(extra_env),
                    capture_output=True,
                    timeout=timeout,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                return proc.returncode, proc.stdout or "", proc.stderr or "", False
            except subprocess.TimeoutExpired as exc:
                out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
                err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
                return -1, out or "", err or "", True

        started = time.perf_counter()
        exit_code, stdout, stderr, timed_out = await asyncio.to_thread(_exec)
        duration = (time.perf_counter() - started) * 1000
        return SandboxResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout[-200_000:],
            stderr=stderr[-200_000:],
            timed_out=timed_out,
            duration_ms=round(duration, 2),
            mode="local",
        )


def create_sandbox(settings: Settings) -> SandboxManager:
    if settings.sandbox_mode == "local":
        return LocalSandbox(settings)
    return DockerSandbox(settings)
