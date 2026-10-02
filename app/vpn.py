"""Bring up the VPN profile exported from a Teltonika RUT, then tear it down."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path


class VpnSession:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.mode: str | None = None
        self.config_path: Path | None = None
        self._auth_path: Path | None = None
        self._drain_task: asyncio.Task | None = None

    async def up(self, mode: str, config_path: Path | None, username: str, password: str) -> tuple[str, str]:
        await self.down()
        if mode == "none":
            return (
                "skipped",
                "Using the current network route. If the chiller is behind the RUT, connect the VPN first, or choose WireGuard or OpenVPN here.",
            )
        if config_path is None:
            raise RuntimeError("Upload the client profile exported from the Teltonika before connecting.")
        if mode == "wireguard":
            return await self._wireguard(config_path)
        if mode == "openvpn":
            return await self._openvpn(config_path, username, password)
        raise RuntimeError(f"Unknown VPN mode {mode}")

    async def down(self) -> None:
        mode = self.mode
        path = self.config_path
        proc = self.proc
        drain = self._drain_task
        self.proc = None
        self.mode = None
        self.config_path = None
        self._drain_task = None
        if drain is not None:
            drain.cancel()
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except TimeoutError:
                proc.kill()
                await proc.wait()
        if mode == "wireguard" and path is not None:
            await self._run(_privileged(["wg-quick", "down", str(path)]), ignore_error=True)
        if self._auth_path is not None and self._auth_path.exists():
            self._auth_path.unlink()
            self._auth_path = None

    async def _wireguard(self, path: Path) -> tuple[str, str]:
        if shutil.which("wg-quick") is None:
            raise RuntimeError(
                "wg-quick is not installed. Install wireguard-tools, or bring the tunnel up yourself and set VPN to already connected."
            )
        code, output = await self._run(_privileged(["wg-quick", "up", str(path)]))
        if code != 0:
            raise RuntimeError(_privilege_hint(output, "WireGuard"))
        self.mode = "wireguard"
        self.config_path = path
        return "up", "WireGuard tunnel is up"

    async def _openvpn(self, path: Path, username: str, password: str) -> tuple[str, str]:
        if shutil.which("openvpn") is None:
            raise RuntimeError(
                "openvpn is not installed. Install it, or connect the tunnel yourself and set VPN to already connected."
            )
        args = _privileged(["openvpn", "--config", str(path), "--connect-retry-max", "2"])
        if username:
            auth = path.with_suffix(".auth")
            auth.write_text(f"{username}\n{password}\n", encoding="utf-8")
            os.chmod(auth, 0o600)
            self._auth_path = auth
            args.extend(["--auth-user-pass", str(auth)])
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        lines: list[str] = []
        assert self.proc.stdout is not None
        try:
            while True:
                line = await asyncio.wait_for(self.proc.stdout.readline(), 25)
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    lines.append(text)
                if "Initialization Sequence Completed" in text:
                    self.mode = "openvpn"
                    self.config_path = path
                    self._drain_task = asyncio.create_task(self._drain_stdout())
                    return "up", "OpenVPN tunnel is up"
                if "AUTH_FAILED" in text:
                    await self.down()
                    raise RuntimeError("OpenVPN rejected the username or password.")
        except TimeoutError:
            await self.down()
            tail = " | ".join(lines[-6:]) or "no output"
            raise RuntimeError(f"OpenVPN did not connect within 25s. {tail}") from None
        code = self.proc.returncode
        tail = " | ".join(lines[-8:]) or "no output"
        await self.down()
        raise RuntimeError(_privilege_hint(f"exit {code}: {tail}", "OpenVPN"))

    async def _drain_stdout(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _run(self, args: list[str], ignore_error: bool = False) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            if ignore_error:
                return 1, str(exc)
            raise RuntimeError(f"Could not run {args[0]}") from exc
        stdout, _ = await proc.communicate()
        text = stdout.decode(errors="replace").strip()
        return proc.returncode or 0, text


def _privileged(args: list[str]) -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return args
    return ["sudo", "-n", *args]


def _privilege_hint(output: str, name: str) -> str:
    lowered = output.lower()
    if "password is required" in lowered or "a terminal is required" in lowered or "not in the sudoers" in lowered:
        return (
            f"{name} needs permission to create a network interface. "
            "Connect the tunnel in NetworkManager (or with sudo), then set VPN to already connected. "
            f"Detail: {output[-400:]}"
        )
    return f"{name} failed. {output[-500:]}"
