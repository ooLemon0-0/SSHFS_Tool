# -*- coding: utf-8 -*-
"""
SSHFS Mount Manager（macOS）

A small tkinter GUI for mounting remote directories with macFUSE + SSHFS.
The application:
- keeps connection fields blank on first run;
- mounts through the installed `sshfs` command;
- sends the SSH password through stdin using SSHFS `password_stdin`;
- stores an optional remembered password in the macOS Keychain;
- saves non-secret settings only after a successful mount;
- can unmount selected SSHFS volumes and restart Finder as a fallback.

Requirements:
1. macOS
2. macFUSE + SSHFS
3. Python 3 with tkinter
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional


APP_NAME = "SSHFS Mount Manager"
APP_DIR_NAME = "SSHFS Mount Manager"
CONFIG_VERSION = 1
KEYCHAIN_SERVICE = "SSHFS Mount Manager"

ERR_SEC_SUCCESS = 0
ERR_SEC_DUPLICATE_ITEM = -25299
ERR_SEC_ITEM_NOT_FOUND = -25300


def config_file_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / APP_DIR_NAME
        / "config.json"
    )


def normalize_remote_path(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if not value:
        raise ValueError("请输入服务器目标目录。")
    if not value.startswith("/"):
        value = "/" + value
    while "//" in value:
        value = value.replace("//", "/")
    if len(value) > 1:
        value = value.rstrip("/")
    return value


def normalize_mount_point(value: str) -> Path:
    value = value.strip()
    if not value:
        raise ValueError("请输入本地挂载目录。")

    path = Path(os.path.expandvars(os.path.expanduser(value))).resolve()
    if path == Path("/"):
        raise ValueError("不能把远程目录挂载到 macOS 根目录 /。")
    return path


def validate_connection(
    host: str,
    port_text: str,
    user: str,
    password: str,
    remote_path: str,
    mount_point: str,
) -> dict:
    host = host.strip()
    user = user.strip()

    if not host:
        raise ValueError("请输入服务器 IP 或主机名。")
    if any(ch in host for ch in "\r\n\t "):
        raise ValueError("服务器地址不能包含空白字符。")
    if not user:
        raise ValueError("请输入 SSH 用户名。")
    if any(ch in user for ch in "\r\n\t@/\\"):
        raise ValueError("SSH 用户名包含不支持的字符。")
    if not password:
        raise ValueError("请输入 SSH 密码。")
    if "\x00" in password:
        raise ValueError("密码不能包含空字符。")

    try:
        port = int(port_text.strip())
    except ValueError as exc:
        raise ValueError("SSH 端口必须是整数。") from exc

    if not (1 <= port <= 65535):
        raise ValueError("SSH 端口必须在 1 到 65535 之间。")

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "remote_path": normalize_remote_path(remote_path),
        "mount_point": str(normalize_mount_point(mount_point)),
    }


def find_sshfs() -> Optional[str]:
    candidates = [
        shutil.which("sshfs"),
        "/usr/local/bin/sshfs",
        "/opt/homebrew/bin/sshfs",
        "/usr/bin/sshfs",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def find_command(name: str, common_paths: list[str]) -> Optional[str]:
    candidate = shutil.which(name)
    if candidate:
        return candidate
    for path in common_paths:
        if Path(path).is_file():
            return path
    return None


def decode_mount_field(value: str) -> str:
    # `mount` may escape spaces and backslashes in output.
    replacements = {
        r"\040": " ",
        r"\011": "\t",
        r"\012": "\n",
        r"\134": "\\",
    }
    for encoded, decoded in replacements.items():
        value = value.replace(encoded, decoded)
    return value


def list_sshfs_mounts() -> list[dict[str, str]]:
    mount_cmd = find_command("mount", ["/sbin/mount", "/usr/sbin/mount"])
    if not mount_cmd:
        return []

    try:
        result = subprocess.run(
            [mount_cmd],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    mounts: list[dict[str, str]] = []
    pattern = re.compile(r"^(.*?) on (.*?) \((.*?)\)$")

    for raw_line in result.stdout.splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue

        source, mount_point, options = match.groups()
        source = decode_mount_field(source)
        mount_point = decode_mount_field(mount_point)
        lower = raw_line.lower()

        # macFUSE mount output normally contains macfuse/osxfuse.
        # Restrict generic macFUSE entries to SSH-like sources.
        looks_like_sshfs = (
            "sshfs" in lower
            or (
                ("macfuse" in lower or "osxfuse" in lower)
                and "@" in source
                and ":" in source
            )
        )
        if not looks_like_sshfs:
            continue

        mounts.append(
            {
                "source": source,
                "mount_point": mount_point,
                "options": options,
            }
        )

    return mounts


def is_mounted(mount_point: str) -> bool:
    normalized = str(Path(mount_point).resolve())
    return any(
        str(Path(item["mount_point"]).resolve()) == normalized
        for item in list_sshfs_mounts()
    )


class MacKeychain:
    """Minimal wrapper around the macOS Security framework."""

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("macOS Keychain is only available on macOS.")

        self.security = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/Security.framework/Security"
        )
        self.core_foundation = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )

        self.security.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.security.SecKeychainAddGenericPassword.restype = ctypes.c_int32

        self.security.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.security.SecKeychainFindGenericPassword.restype = ctypes.c_int32

        self.security.SecKeychainItemModifyAttributesAndData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        self.security.SecKeychainItemModifyAttributesAndData.restype = (
            ctypes.c_int32
        )

        self.security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        self.security.SecKeychainItemDelete.restype = ctypes.c_int32

        self.security.SecKeychainItemFreeContent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.security.SecKeychainItemFreeContent.restype = ctypes.c_int32

        self.core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        self.core_foundation.CFRelease.restype = None

    @staticmethod
    def _encoded(value: str) -> bytes:
        return value.encode("utf-8")

    def _find_item(self, account: str) -> tuple[int, ctypes.c_void_p]:
        service = self._encoded(KEYCHAIN_SERVICE)
        account_bytes = self._encoded(account)
        item_ref = ctypes.c_void_p()

        status = int(
            self.security.SecKeychainFindGenericPassword(
                None,
                len(service),
                service,
                len(account_bytes),
                account_bytes,
                None,
                None,
                ctypes.byref(item_ref),
            )
        )
        return status, item_ref

    def get_password(self, account: str) -> Optional[str]:
        service = self._encoded(KEYCHAIN_SERVICE)
        account_bytes = self._encoded(account)
        password_length = ctypes.c_uint32(0)
        password_data = ctypes.c_void_p()
        item_ref = ctypes.c_void_p()

        status = int(
            self.security.SecKeychainFindGenericPassword(
                None,
                len(service),
                service,
                len(account_bytes),
                account_bytes,
                ctypes.byref(password_length),
                ctypes.byref(password_data),
                ctypes.byref(item_ref),
            )
        )

        if status == ERR_SEC_ITEM_NOT_FOUND:
            return None
        if status != ERR_SEC_SUCCESS:
            raise RuntimeError(f"读取 macOS 钥匙串失败，OSStatus={status}")

        try:
            raw = ctypes.string_at(password_data, password_length.value)
            return raw.decode("utf-8")
        finally:
            if password_data:
                self.security.SecKeychainItemFreeContent(None, password_data)
            if item_ref:
                self.core_foundation.CFRelease(item_ref)

    def save_password(self, account: str, password: str) -> None:
        status, item_ref = self._find_item(account)
        password_bytes = self._encoded(password)
        password_buffer = ctypes.create_string_buffer(
            password_bytes, len(password_bytes)
        )

        try:
            if status == ERR_SEC_SUCCESS and item_ref:
                update_status = int(
                    self.security.SecKeychainItemModifyAttributesAndData(
                        item_ref,
                        None,
                        len(password_bytes),
                        ctypes.cast(password_buffer, ctypes.c_void_p),
                    )
                )
                if update_status != ERR_SEC_SUCCESS:
                    raise RuntimeError(
                        "更新 macOS 钥匙串密码失败，"
                        f"OSStatus={update_status}"
                    )
                return

            if status != ERR_SEC_ITEM_NOT_FOUND:
                raise RuntimeError(
                    f"查询 macOS 钥匙串失败，OSStatus={status}"
                )

            service = self._encoded(KEYCHAIN_SERVICE)
            account_bytes = self._encoded(account)
            add_status = int(
                self.security.SecKeychainAddGenericPassword(
                    None,
                    len(service),
                    service,
                    len(account_bytes),
                    account_bytes,
                    len(password_bytes),
                    ctypes.cast(password_buffer, ctypes.c_void_p),
                    None,
                )
            )
            if add_status not in (ERR_SEC_SUCCESS, ERR_SEC_DUPLICATE_ITEM):
                raise RuntimeError(
                    f"写入 macOS 钥匙串失败，OSStatus={add_status}"
                )
        finally:
            if item_ref:
                self.core_foundation.CFRelease(item_ref)

    def delete_password(self, account: str) -> None:
        status, item_ref = self._find_item(account)
        try:
            if status == ERR_SEC_ITEM_NOT_FOUND:
                return
            if status != ERR_SEC_SUCCESS or not item_ref:
                raise RuntimeError(
                    f"查询 macOS 钥匙串失败，OSStatus={status}"
                )

            delete_status = int(self.security.SecKeychainItemDelete(item_ref))
            if delete_status not in (ERR_SEC_SUCCESS, ERR_SEC_ITEM_NOT_FOUND):
                raise RuntimeError(
                    f"删除 macOS 钥匙串密码失败，OSStatus={delete_status}"
                )
        finally:
            if item_ref:
                self.core_foundation.CFRelease(item_ref)


class MountManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("macOS 版本只能在 macOS 上运行。")

        self.root = root
        self.keychain = MacKeychain()
        self.tasks: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False

        self.root.title("SSHFS Mount Manager — macOS")
        self.root.geometry("940x730")
        self.root.minsize(840, 660)

        self.host_var = tk.StringVar(value="")
        self.port_var = tk.StringVar(value="22")
        self.user_var = tk.StringVar(value="")
        self.password_var = tk.StringVar(value="")
        self.remote_path_var = tk.StringVar(value="")
        self.mount_point_var = tk.StringVar(
            value=str(Path.home() / "SSHFS-Mount")
        )
        self.remember_password_var = tk.BooleanVar(value=True)
        self.show_password_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")

        self._configure_style()
        self._build_ui()
        self._load_config()
        self.refresh_mounts()
        self.root.after(150, self._poll_tasks)

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("aqua")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Helvetica", 18, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Warning.TLabel", foreground="#9A3412")
        style.configure("Status.TLabel", font=("Helvetica", 11, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="SSHFS Mount Manager",
            style="Title.TLabel",
        ).pack(anchor="w")

        ttk.Label(
            outer,
            text=(
                "将服务器目录挂载到 macOS 本地目录，供 AI 工具、"
                "编辑器和文件分析工具读取。"
            ),
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        form = ttk.LabelFrame(outer, text="连接信息", padding=14)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="服务器 IP / 主机名").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(form, textvariable=self.host_var).grid(
            row=0, column=1, sticky="ew", pady=6
        )

        ttk.Label(form, text="SSH 端口").grid(
            row=0, column=2, sticky="w", padx=(18, 8), pady=6
        )
        ttk.Entry(form, textvariable=self.port_var, width=10).grid(
            row=0, column=3, sticky="ew", pady=6
        )

        ttk.Label(form, text="SSH 用户名").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(form, textvariable=self.user_var).grid(
            row=1, column=1, sticky="ew", pady=6
        )

        ttk.Label(form, text="SSH 密码").grid(
            row=1, column=2, sticky="w", padx=(18, 8), pady=6
        )
        self.password_entry = ttk.Entry(
            form,
            textvariable=self.password_var,
            show="●",
        )
        self.password_entry.grid(row=1, column=3, sticky="ew", pady=6)

        ttk.Label(form, text="服务器目标目录").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(form, textvariable=self.remote_path_var).grid(
            row=2, column=1, columnspan=3, sticky="ew", pady=6
        )

        ttk.Label(form, text="macOS 本地挂载目录").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(form, textvariable=self.mount_point_var).grid(
            row=3, column=1, columnspan=3, sticky="ew", pady=6
        )

        options = ttk.Frame(form)
        options.grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(8, 2)
        )
        ttk.Checkbutton(
            options,
            text="显示密码",
            variable=self.show_password_var,
            command=self._toggle_password,
        ).pack(side="left")
        ttk.Checkbutton(
            options,
            text="将密码保存到 macOS 钥匙串",
            variable=self.remember_password_var,
        ).pack(side="left", padx=(18, 0))

        ttk.Label(
            form,
            text=(
                "SSHFS 映射的是服务器真实目录，并非独立副本。"
                "当前 SSH 账号有写权限时，本地 AI 工具或编辑器也可能修改远程文件。"
            ),
            style="Warning.TLabel",
            wraplength=850,
            justify="left",
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 2))

        button_area = ttk.Frame(outer)
        button_area.pack(fill="x", pady=14)

        primary = ttk.Frame(button_area)
        primary.pack(fill="x")

        self.mount_button = ttk.Button(
            primary,
            text="新建挂载",
            command=self.mount_clicked,
        )
        self.mount_button.pack(side="left")

        self.unmount_button = ttk.Button(
            primary,
            text="解除所选挂载",
            command=self.unmount_clicked,
        )
        self.unmount_button.pack(side="left", padx=(10, 0))

        self.open_button = ttk.Button(
            primary,
            text="在 Finder 中打开",
            command=self.open_mount_point,
        )
        self.open_button.pack(side="left", padx=(10, 0))

        self.refresh_button = ttk.Button(
            primary,
            text="刷新状态",
            command=self.refresh_mounts,
        )
        self.refresh_button.pack(side="left", padx=(10, 0))

        secondary = ttk.Frame(button_area)
        secondary.pack(fill="x", pady=(10, 0))

        ttk.Button(
            secondary,
            text="环境检查",
            command=self.check_environment,
        ).pack(side="left")

        self.restart_finder_button = ttk.Button(
            secondary,
            text="重启 Finder（清幽灵卷）",
            command=self.restart_finder,
        )
        self.restart_finder_button.pack(side="left", padx=(10, 0))

        ttk.Button(
            secondary,
            text="清除已保存配置",
            command=self.clear_saved_config,
        ).pack(side="right")

        mounts_frame = ttk.LabelFrame(
            outer, text="当前 SSHFS 挂载", padding=10
        )
        mounts_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            mounts_frame,
            columns=("source", "mount_point"),
            show="headings",
            height=9,
        )
        self.tree.heading("source", text="远程来源")
        self.tree.heading("mount_point", text="本地挂载目录")
        self.tree.column("source", width=360, anchor="w")
        self.tree.column("mount_point", width=480, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)
        self.tree.bind("<Double-1>", lambda _event: self.open_mount_point())

        scrollbar = ttk.Scrollbar(
            mounts_frame,
            orient="vertical",
            command=self.tree.yview,
        )
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        status = ttk.Frame(outer)
        status.pack(fill="x", pady=(12, 0))
        ttk.Label(status, text="状态：").pack(side="left")
        ttk.Label(
            status,
            textvariable=self.status_var,
            style="Status.TLabel",
        ).pack(side="left")

        ttk.Label(
            outer,
            text=(
                f"配置位置：{config_file_path()}；"
                "保存的密码位于当前用户的 macOS 钥匙串中。"
            ),
            style="Hint.TLabel",
            wraplength=880,
        ).pack(anchor="w", pady=(8, 0))

    def _toggle_password(self) -> None:
        self.password_entry.configure(
            show="" if self.show_password_var.get() else "●"
        )

    def _tree_selected(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if len(values) >= 2:
            self.mount_point_var.set(str(values[1]))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.mount_button.configure(state=state)
        self.unmount_button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.restart_finder_button.configure(state=state)
        if message:
            self.status_var.set(message)

    @staticmethod
    def _account_key(values: dict) -> str:
        return (
            f"{values['user']}@{values['host']}:{values['port']}"
        )

    def _collect_values(self) -> dict:
        return validate_connection(
            self.host_var.get(),
            self.port_var.get(),
            self.user_var.get(),
            self.password_var.get(),
            self.remote_path_var.get(),
            self.mount_point_var.get(),
        )

    def mount_clicked(self) -> None:
        if self.busy:
            return

        try:
            values = self._collect_values()
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        sshfs_path = find_sshfs()
        if not sshfs_path:
            messagebox.showerror(
                "未找到 SSHFS",
                "没有找到 sshfs 命令。\n\n"
                "请先安装 macFUSE 与 SSHFS，再重新启动程序。",
                parent=self.root,
            )
            return

        mount_point = Path(values["mount_point"])
        if is_mounted(str(mount_point)):
            messagebox.showinfo(
                "已经挂载",
                f"{mount_point} 当前已经是 SSHFS 挂载点。",
                parent=self.root,
            )
            return

        if mount_point.exists():
            try:
                has_contents = any(mount_point.iterdir())
            except OSError as exc:
                messagebox.showerror(
                    "无法读取挂载目录", str(exc), parent=self.root
                )
                return
            if has_contents:
                messagebox.showerror(
                    "挂载目录不是空目录",
                    "SSHFS 挂载目录必须为空。\n\n"
                    f"请清空或更换本地目录：\n{mount_point}",
                    parent=self.root,
                )
                return

        self._set_busy(True, "正在建立 SSHFS 挂载，请稍候……")
        threading.Thread(
            target=self._mount_worker,
            args=(values, sshfs_path),
            daemon=True,
        ).start()

    def _mount_worker(self, values: dict, sshfs_path: str) -> None:
        mount_point = Path(values["mount_point"])
        created_mount_point = False

        try:
            if not mount_point.exists():
                mount_point.mkdir(parents=True, exist_ok=False)
                created_mount_point = True

            source = (
                f"{values['user']}@{values['host']}:"
                f"{values['remote_path']}"
            )
            command = [
                sshfs_path,
                source,
                str(mount_point),
                "-p",
                str(values["port"]),
                "-o",
                "reconnect",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=3",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "password_stdin",
            ]

            result = subprocess.run(
                command,
                input=values["password"] + "\n",
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            if result.returncode == 0:
                # Give Finder/macFUSE a moment to publish the new mount.
                time.sleep(0.5)

            self.tasks.put(
                (
                    "mount_result",
                    {
                        "ok": result.returncode == 0,
                        "returncode": result.returncode,
                        "stdout": result.stdout.strip(),
                        "stderr": result.stderr.strip(),
                        "values": values,
                        "created_mount_point": created_mount_point,
                    },
                )
            )
        except subprocess.TimeoutExpired:
            self.tasks.put(
                (
                    "mount_result",
                    {
                        "ok": False,
                        "returncode": None,
                        "stdout": "",
                        "stderr": "连接超时。请检查服务器地址、端口和网络。",
                        "values": values,
                        "created_mount_point": created_mount_point,
                    },
                )
            )
        except Exception as exc:
            self.tasks.put(("exception", exc))

    def unmount_clicked(self) -> None:
        if self.busy:
            return

        try:
            mount_point = str(
                normalize_mount_point(self.mount_point_var.get())
            )
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        if not is_mounted(mount_point):
            messagebox.showinfo(
                "没有检测到挂载",
                f"没有在当前 SSHFS 列表中找到：\n{mount_point}",
                parent=self.root,
            )
            return

        if not messagebox.askyesno(
            "确认解除挂载",
            "请先关闭正在访问该目录的 AI 工具、编辑器、终端和 Finder 窗口。\n\n"
            f"是否解除：\n{mount_point}",
            parent=self.root,
        ):
            return

        self._set_busy(True, "正在解除挂载……")
        threading.Thread(
            target=self._unmount_worker,
            args=(mount_point, False),
            daemon=True,
        ).start()

    def _unmount_worker(
        self, mount_point: str, force: bool
    ) -> None:
        diskutil = find_command(
            "diskutil", ["/usr/sbin/diskutil", "/usr/bin/diskutil"]
        )
        umount = find_command(
            "umount", ["/sbin/umount", "/usr/sbin/umount"]
        )

        try:
            if diskutil:
                command = [diskutil, "unmount"]
                if force:
                    command.append("force")
                command.append(mount_point)
            elif umount:
                command = [umount]
                if force:
                    command.append("-f")
                command.append(mount_point)
            else:
                raise RuntimeError("没有找到 diskutil 或 umount。")

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.tasks.put(
                (
                    "unmount_result",
                    {
                        "ok": result.returncode == 0,
                        "force": force,
                        "returncode": result.returncode,
                        "stdout": result.stdout.strip(),
                        "stderr": result.stderr.strip(),
                        "mount_point": mount_point,
                    },
                )
            )
        except subprocess.TimeoutExpired:
            self.tasks.put(
                (
                    "unmount_result",
                    {
                        "ok": False,
                        "force": force,
                        "returncode": None,
                        "stdout": "",
                        "stderr": "解除挂载超时。",
                        "mount_point": mount_point,
                    },
                )
            )
        except Exception as exc:
            self.tasks.put(("exception", exc))

    def _poll_tasks(self) -> None:
        try:
            while True:
                event, payload = self.tasks.get_nowait()
                if event == "mount_result":
                    self._handle_mount_result(payload)
                elif event == "unmount_result":
                    self._handle_unmount_result(payload)
                elif event == "exception":
                    self._set_busy(False, "操作失败")
                    messagebox.showerror(
                        "程序异常", repr(payload), parent=self.root
                    )
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self._poll_tasks)

    def _handle_mount_result(self, result: dict) -> None:
        self._set_busy(False)
        values = result["values"]

        if result["ok"]:
            save_note = self._save_successful_config(values)
            self.refresh_mounts()
            self.status_var.set(
                f"挂载成功：{values['mount_point']}"
            )
            messagebox.showinfo(
                "挂载成功",
                f"远程目录已挂载到：\n{values['mount_point']}\n\n"
                f"{save_note}",
                parent=self.root,
            )
            return

        if result.get("created_mount_point"):
            mount_point = Path(values["mount_point"])
            try:
                if mount_point.exists() and not any(mount_point.iterdir()):
                    mount_point.rmdir()
            except OSError:
                pass

        details = result.get("stderr") or result.get("stdout")
        if not details:
            details = f"sshfs 返回代码：{result.get('returncode')}"
        self.status_var.set("挂载失败")
        messagebox.showerror(
            "挂载失败",
            details,
            parent=self.root,
        )
        self.refresh_mounts()

    def _handle_unmount_result(self, result: dict) -> None:
        self._set_busy(False)

        if result["ok"]:
            self.refresh_mounts()
            self.status_var.set(
                f"已解除：{result['mount_point']}"
            )
            messagebox.showinfo(
                "解除成功",
                "SSHFS 映射已解除，服务器文件不会被删除。\n\n"
                "如果 Finder 仍然显示旧卷，可以点击"
                "“重启 Finder（清幽灵卷）”。",
                parent=self.root,
            )
            return

        details = result.get("stderr") or result.get("stdout")
        if not details:
            details = f"返回代码：{result.get('returncode')}"

        if not result["force"]:
            force = messagebox.askyesno(
                "普通解除失败",
                f"{details}\n\n"
                "是否尝试强制解除？\n"
                "强制解除前必须停止对该目录的读写。",
                parent=self.root,
            )
            if force:
                self._set_busy(True, "正在强制解除挂载……")
                threading.Thread(
                    target=self._unmount_worker,
                    args=(result["mount_point"], True),
                    daemon=True,
                ).start()
                return

        self.status_var.set("解除挂载失败")
        messagebox.showerror(
            "解除挂载失败",
            details,
            parent=self.root,
        )
        self.refresh_mounts()

    def refresh_mounts(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        mounts = list_sshfs_mounts()
        for item in mounts:
            self.tree.insert(
                "",
                "end",
                values=(item["source"], item["mount_point"]),
            )

        self.status_var.set(
            f"已刷新，发现 {len(mounts)} 个 SSHFS 挂载。"
        )

    def open_mount_point(self) -> None:
        try:
            mount_point = normalize_mount_point(
                self.mount_point_var.get()
            )
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        if not mount_point.exists():
            messagebox.showinfo(
                "目录不存在",
                f"本地目录不存在：\n{mount_point}",
                parent=self.root,
            )
            return

        open_cmd = find_command("open", ["/usr/bin/open"])
        if not open_cmd:
            messagebox.showerror(
                "无法打开 Finder",
                "没有找到 macOS open 命令。",
                parent=self.root,
            )
            return

        try:
            subprocess.Popen(
                [open_cmd, str(mount_point)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            messagebox.showerror(
                "无法打开 Finder", str(exc), parent=self.root
            )

    def restart_finder(self) -> None:
        if not messagebox.askyesno(
            "确认重启 Finder",
            "该操作会关闭并重新启动 Finder 窗口。\n\n"
            "正在复制、移动或重命名文件时不要执行。\n"
            "是否继续？",
            parent=self.root,
        ):
            return

        killall = find_command("killall", ["/usr/bin/killall"])
        if not killall:
            messagebox.showerror(
                "无法重启 Finder",
                "没有找到 killall 命令。",
                parent=self.root,
            )
            return

        try:
            result = subprocess.run(
                [killall, "Finder"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode not in (0, 1):
                raise RuntimeError(
                    result.stderr.strip()
                    or f"killall 返回代码 {result.returncode}"
                )
            self.root.after(1200, self.refresh_mounts)
            self.status_var.set("Finder 已重启，正在刷新挂载状态……")
            messagebox.showinfo(
                "Finder 已重启",
                "Finder 会自动重新启动。\n"
                "残留的幽灵卷通常会随之清除。",
                parent=self.root,
            )
        except Exception as exc:
            messagebox.showerror(
                "重启 Finder 失败", str(exc), parent=self.root
            )

    def _save_successful_config(self, values: dict) -> str:
        path = config_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        remember = bool(self.remember_password_var.get())
        account = self._account_key(values)
        keychain_note = ""

        previous_account = None
        if path.exists():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                previous_account = previous.get("keychain_account")
            except Exception:
                previous_account = None

        if previous_account and previous_account != account:
            try:
                self.keychain.delete_password(str(previous_account))
            except Exception:
                pass

        if remember:
            try:
                self.keychain.save_password(account, values["password"])
                keychain_note = "密码已保存到 macOS 钥匙串。"
            except Exception as exc:
                remember = False
                keychain_note = f"连接设置已保存，但密码保存失败：{exc}"
        else:
            try:
                self.keychain.delete_password(account)
            except Exception:
                pass
            keychain_note = "未保存密码。"

        data = {
            "version": CONFIG_VERSION,
            "host": values["host"],
            "port": values["port"],
            "user": values["user"],
            "remote_path": values["remote_path"],
            "mount_point": values["mount_point"],
            "remember_password": remember,
            "keychain_account": account if remember else "",
        }

        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, path)
        return f"已保存本次成功配置。{keychain_note}"

    def _load_config(self) -> None:
        path = config_file_path()
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data.get("version", 0)) != CONFIG_VERSION:
                return

            self.host_var.set(str(data.get("host", "")))
            self.port_var.set(str(data.get("port", "22")))
            self.user_var.set(str(data.get("user", "")))
            self.remote_path_var.set(str(data.get("remote_path", "")))
            self.mount_point_var.set(
                str(
                    data.get(
                        "mount_point",
                        str(Path.home() / "SSHFS-Mount"),
                    )
                )
            )

            remember = bool(data.get("remember_password", False))
            self.remember_password_var.set(remember)
            account = str(data.get("keychain_account", ""))
            if remember and account:
                password = self.keychain.get_password(account)
                if password is not None:
                    self.password_var.set(password)

            self.status_var.set("已加载上次成功挂载的配置。")
        except Exception as exc:
            self.status_var.set("保存配置读取失败，已使用空白配置。")
            messagebox.showwarning(
                "配置读取失败",
                "无法读取本地配置或 macOS 钥匙串。\n\n"
                f"{exc}",
                parent=self.root,
            )

    def clear_saved_config(self) -> None:
        path = config_file_path()
        account = ""

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                account = str(data.get("keychain_account", ""))
            except Exception:
                account = ""

        if not path.exists() and not account:
            messagebox.showinfo(
                "没有保存配置",
                "当前没有已保存的配置。",
                parent=self.root,
            )
            return

        if not messagebox.askyesno(
            "确认清除",
            "是否删除本地连接设置和对应的钥匙串密码？\n\n"
            "这不会解除当前挂载，也不会删除服务器文件。",
            parent=self.root,
        ):
            return

        errors: list[str] = []
        if account:
            try:
                self.keychain.delete_password(account)
            except Exception as exc:
                errors.append(str(exc))

        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            errors.append(str(exc))

        self.password_var.set("")
        if errors:
            messagebox.showwarning(
                "部分清除失败",
                "\n".join(errors),
                parent=self.root,
            )
        else:
            self.status_var.set("已清除保存配置。")
            messagebox.showinfo(
                "已清除",
                "本地配置和保存的密码已清除。",
                parent=self.root,
            )

    def check_environment(self) -> None:
        sshfs_path = find_sshfs()
        macfuse_candidates = [
            Path("/Library/Filesystems/macfuse.fs"),
            Path("/Library/Frameworks/macFUSE.framework"),
            Path("/Library/Filesystems/osxfuse.fs"),
        ]
        macfuse_path = next(
            (path for path in macfuse_candidates if path.exists()),
            None,
        )

        lines = [
            f"macOS：{os.uname().release}",
            f"Python：{sys.version.split()[0]}",
            (
                f"SSHFS：已找到 {sshfs_path}"
                if sshfs_path
                else "SSHFS：未找到 sshfs 命令"
            ),
            (
                f"macFUSE：已找到 {macfuse_path}"
                if macfuse_path
                else "macFUSE：未在常见目录中检测到"
            ),
            f"配置目录：{config_file_path().parent}",
        ]

        if sshfs_path:
            lines.append(
                "\n初步检查通过。最终仍以实际挂载结果为准。"
            )
        else:
            lines.append(
                "\n请先按照 README 安装 macFUSE 与 SSHFS。"
            )

        messagebox.showinfo(
            "环境检查", "\n".join(lines), parent=self.root
        )


def main() -> None:
    if sys.platform != "darwin":
        print("macOS 版本只能在 macOS 上运行。", file=sys.stderr)
        raise SystemExit(1)

    root = tk.Tk()
    try:
        MountManagerApp(root)
    except Exception as exc:
        messagebox.showerror("启动失败", str(exc), parent=root)
        root.destroy()
        raise SystemExit(1)

    root.mainloop()


if __name__ == "__main__":
    main()
