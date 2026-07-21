# -*- coding: utf-8 -*-
r"""
SSHFS Mount Manager（Windows）
- 使用 SSHFS-Win 的 \\sshfs.r\user@host!port\path UNC 语法
- 通过 Windows WNet API 挂载/解除挂载，不把密码拼到 net use 命令行
- 仅在挂载成功后保存配置
- 密码使用当前 Windows 用户的 DPAPI 加密后保存
- 解除挂载后主动刷新 Explorer，并提供“清理幽灵盘”兜底按钮

依赖：
1. Windows 10/11
2. WinFsp + SSHFS-Win
3. Python 3（含 tkinter）
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import string
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional


APP_DIR_NAME = "SSHFS-Mount-Manager"
CONFIG_VERSION = 3

NO_ERROR = 0
ERROR_ACCESS_DENIED = 5
ERROR_BAD_NETPATH = 53
ERROR_BAD_NET_NAME = 67
ERROR_ALREADY_ASSIGNED = 85
ERROR_INVALID_PASSWORD = 86
ERROR_BAD_DEVICE = 1200
ERROR_CONNECTION_UNAVAIL = 1201
ERROR_DEVICE_ALREADY_REMEMBERED = 1202
ERROR_NO_NET_OR_BAD_PATH = 1203
ERROR_BAD_PROVIDER = 1204
ERROR_EXTENDED_ERROR = 1208
ERROR_SESSION_CREDENTIAL_CONFLICT = 1219
ERROR_LOGON_FAILURE = 1326
ERROR_NOT_CONNECTED = 2250

RESOURCETYPE_DISK = 0x00000001
CONNECT_UPDATE_PROFILE = 0x00000001
CRYPTPROTECT_UI_FORBIDDEN = 0x00000001

# Windows Shell 变更通知：
# 解除网络盘后主动通知 Explorer“盘符已移除”，减少红叉幽灵盘残留。
SHCNE_DRIVEREMOVED = 0x00000080
SHCNF_PATHW = 0x0005
SHCNF_FLUSH = 0x1000

CREATE_NO_WINDOW = 0x08000000


class NETRESOURCEW(ctypes.Structure):
    _fields_ = [
        ("dwScope", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("dwDisplayType", wintypes.DWORD),
        ("dwUsage", wintypes.DWORD),
        ("lpLocalName", wintypes.LPWSTR),
        ("lpRemoteName", wintypes.LPWSTR),
        ("lpComment", wintypes.LPWSTR),
        ("lpProvider", wintypes.LPWSTR),
    ]


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class WindowsApi:
    """封装 Windows WNet 与 DPAPI。"""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("本程序只能在 Windows 上运行。")

        self.mpr = ctypes.WinDLL("mpr", use_last_error=True)
        self.crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        self.mpr.WNetAddConnection2W.argtypes = [
            ctypes.POINTER(NETRESOURCEW),
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
        ]
        self.mpr.WNetAddConnection2W.restype = wintypes.DWORD

        self.mpr.WNetCancelConnection2W.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        self.mpr.WNetCancelConnection2W.restype = wintypes.DWORD

        self.mpr.WNetGetConnectionW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.mpr.WNetGetConnectionW.restype = wintypes.DWORD

        self.mpr.WNetGetLastErrorW.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        self.mpr.WNetGetLastErrorW.restype = wintypes.DWORD

        self.crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            wintypes.LPCWSTR,
            ctypes.POINTER(DATA_BLOB),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(DATA_BLOB),
        ]
        self.crypt32.CryptProtectData.restype = wintypes.BOOL

        self.crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(DATA_BLOB),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(DATA_BLOB),
        ]
        self.crypt32.CryptUnprotectData.restype = wintypes.BOOL

        self.kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self.kernel32.LocalFree.restype = wintypes.HLOCAL

        self.shell32.SHChangeNotify.argtypes = [
            wintypes.LONG,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.shell32.SHChangeNotify.restype = None

    def mount(
        self,
        drive: str,
        unc_path: str,
        username: str,
        password: str,
    ) -> int:
        resource = NETRESOURCEW()
        resource.dwType = RESOURCETYPE_DISK
        resource.lpLocalName = drive
        resource.lpRemoteName = unc_path

        # flags=0：只建立当前登录会话中的连接，不要求 Windows 在下次登录自动恢复。
        return int(
            self.mpr.WNetAddConnection2W(
                ctypes.byref(resource),
                password,
                username,
                0,
            )
        )

    def unmount(self, drive: str, force: bool = True) -> int:
        # CONNECT_UPDATE_PROFILE 同时清除可能遗留的“已记住连接”。
        return int(
            self.mpr.WNetCancelConnection2W(
                drive,
                CONNECT_UPDATE_PROFILE,
                bool(force),
            )
        )

    def notify_drive_removed(self, drive: str) -> None:
        """
        通知 Windows Shell：该盘符已经被移除。

        WNetCancelConnection2 负责真正解除映射；SHChangeNotify 只负责让
        Explorer 尽快刷新“此电脑”的显示，不会删除任何服务器文件。
        """
        path_buffer = ctypes.c_wchar_p(drive.rstrip("\\/") + "\\")
        self.shell32.SHChangeNotify(
            SHCNE_DRIVEREMOVED,
            SHCNF_PATHW | SHCNF_FLUSH,
            ctypes.cast(path_buffer, ctypes.c_void_p),
            None,
        )

    def get_mapping(self, drive: str) -> tuple[int, Optional[str]]:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        code = int(
            self.mpr.WNetGetConnectionW(
                drive,
                buffer,
                ctypes.byref(size),
            )
        )
        if code == NO_ERROR:
            return code, buffer.value
        return code, None

    def get_extended_error(self) -> str:
        error_code = wintypes.DWORD(0)
        error_text = ctypes.create_unicode_buffer(2048)
        provider = ctypes.create_unicode_buffer(512)
        code = int(
            self.mpr.WNetGetLastErrorW(
                ctypes.byref(error_code),
                error_text,
                len(error_text),
                provider,
                len(provider),
            )
        )
        if code == NO_ERROR:
            parts = []
            if provider.value:
                parts.append(f"提供程序：{provider.value}")
            if error_code.value:
                parts.append(f"扩展错误码：{error_code.value}")
            if error_text.value:
                parts.append(error_text.value)
            return "\n".join(parts)
        return ""

    def protect_text(self, text: str) -> str:
        if not text:
            return ""

        raw = text.encode("utf-8")
        raw_buffer = ctypes.create_string_buffer(raw, len(raw))
        in_blob = DATA_BLOB(
            len(raw),
            ctypes.cast(raw_buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        out_blob = DATA_BLOB()

        ok = self.crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "SSHFS Mount Manager password",
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return base64.b64encode(encrypted).decode("ascii")
        finally:
            if out_blob.pbData:
                self.kernel32.LocalFree(
                    ctypes.cast(out_blob.pbData, wintypes.HLOCAL)
                )

    def unprotect_text(self, encoded: str) -> str:
        if not encoded:
            return ""

        encrypted = base64.b64decode(encoded.encode("ascii"), validate=True)
        encrypted_buffer = ctypes.create_string_buffer(encrypted, len(encrypted))
        in_blob = DATA_BLOB(
            len(encrypted),
            ctypes.cast(encrypted_buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        out_blob = DATA_BLOB()
        description = wintypes.LPWSTR()

        ok = self.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            ctypes.byref(description),
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return raw.decode("utf-8")
        finally:
            if out_blob.pbData:
                self.kernel32.LocalFree(
                    ctypes.cast(out_blob.pbData, wintypes.HLOCAL)
                )
            if description:
                self.kernel32.LocalFree(
                    ctypes.cast(description, wintypes.HLOCAL)
                )


def config_file_path() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home())))
    return base / APP_DIR_NAME / "config.json"


def normalize_drive(value: str) -> str:
    value = value.strip().upper().rstrip("\\/")
    if len(value) == 1:
        value += ":"
    if len(value) != 2 or value[1] != ":" or value[0] not in string.ascii_uppercase:
        raise ValueError("盘符必须是类似 X: 的格式。")
    return value


def normalize_remote_path(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if not value:
        raise ValueError("请输入服务器目标文件夹。")
    if not value.startswith("/"):
        value = "/" + value
    while "//" in value:
        value = value.replace("//", "/")
    if len(value) > 1:
        value = value.rstrip("/")
    return value


def build_sshfs_unc(user: str, host: str, port: int, remote_path: str) -> str:
    r"""
    绝对路径使用 sshfs.r：
    /mnt/data -> \\sshfs.r\user@host!22\mnt\data
    """
    user = user.strip()
    host = host.strip()

    if not user:
        raise ValueError("请输入 SSH 用户名。")
    if any(ch in user for ch in r"@\/"):
        raise ValueError("用户名不能包含 @、\\ 或 /。")
    if not host:
        raise ValueError("请输入服务器 IP 或主机名。")
    if any(ch in host for ch in r"\/ "):
        raise ValueError("服务器地址不能包含空格、\\ 或 /。")
    if not (1 <= port <= 65535):
        raise ValueError("端口必须在 1 到 65535 之间。")

    remote_path = normalize_remote_path(remote_path)
    host_part = f"{host}!{port}"
    base = rf"\\sshfs.r\{user}@{host_part}"

    path_part = remote_path.strip("/").replace("/", "\\")
    return base if not path_part else base + "\\" + path_part


def friendly_error(api: WindowsApi, code: int) -> str:
    hints = {
        ERROR_ACCESS_DENIED: "访问被拒绝。请检查服务器目录权限，或确认盘符未被其他程序锁定。",
        ERROR_BAD_NETPATH: "找不到网络路径。请检查 IP、端口、VPN/内网连接和 SSH 服务。",
        ERROR_BAD_NET_NAME: "找不到网络名。请确认 WinFsp 与 SSHFS-Win 已正确安装。",
        ERROR_ALREADY_ASSIGNED: "该盘符已经被占用，请换一个盘符或先解除现有挂载。",
        ERROR_INVALID_PASSWORD: "密码无效。",
        ERROR_BAD_DEVICE: "盘符格式无效或设备不可用。",
        ERROR_CONNECTION_UNAVAIL: "网络连接当前不可用。",
        ERROR_DEVICE_ALREADY_REMEMBERED: "该盘符存在已记住的旧连接，请先解除挂载。",
        ERROR_NO_NET_OR_BAD_PATH: "网络不可用，或者远程路径格式不正确。",
        ERROR_BAD_PROVIDER: "未找到 SSHFS-Win 网络提供程序。请检查安装。",
        ERROR_SESSION_CREDENTIAL_CONFLICT: (
            "Windows 已使用不同凭据连接到同一网络提供程序。"
            "请先解除相关挂载，必要时注销后重试。"
        ),
        ERROR_LOGON_FAILURE: "登录失败。请检查 SSH 用户名和密码。",
        ERROR_NOT_CONNECTED: "该盘符当前没有网络挂载。",
    }

    try:
        system_text = ctypes.FormatError(code).strip()
    except Exception:
        system_text = ""

    lines = [f"错误码：{code}"]
    if system_text:
        lines.append(system_text)
    if code in hints:
        lines.append(hints[code])
    if code == ERROR_EXTENDED_ERROR:
        extended = api.get_extended_error()
        if extended:
            lines.append(extended)
    return "\n".join(lines)


class MountManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.api = WindowsApi()
        self.tasks: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False

        self.root.title("SSHFS 挂载管理器")
        self.root.geometry("900x720")
        self.root.minsize(820, 660)

        # First-run fields are intentionally blank. The application only
        # restores values from the user's local DPAPI-protected config
        # after a successful mount.
        self.host_var = tk.StringVar(value="")
        self.port_var = tk.StringVar(value="22")
        self.user_var = tk.StringVar(value="")
        self.password_var = tk.StringVar()
        self.remote_path_var = tk.StringVar(value="")
        self.drive_var = tk.StringVar(value="X:")
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
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Warning.TLabel", foreground="#9A3412")
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="SSHFS 挂载管理器",
            style="Title.TLabel",
        ).pack(anchor="w")

        ttk.Label(
            outer,
            text=(
                "通过 SSHFS-Win 将服务器绝对路径映射为 Windows 盘符；"
                "挂载成功后自动保存本次配置。"
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

        ttk.Label(form, text="Windows 盘符").grid(
            row=1, column=2, sticky="w", padx=(18, 8), pady=6
        )
        drive_combo = ttk.Combobox(
            form,
            textvariable=self.drive_var,
            values=[f"{letter}:" for letter in reversed(string.ascii_uppercase[3:])],
            width=8,
            state="normal",
        )
        drive_combo.grid(row=1, column=3, sticky="ew", pady=6)

        ttk.Label(form, text="SSH 密码").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=6
        )
        self.password_entry = ttk.Entry(
            form,
            textvariable=self.password_var,
            show="●",
        )
        self.password_entry.grid(row=2, column=1, sticky="ew", pady=6)

        password_options = ttk.Frame(form)
        password_options.grid(
            row=2, column=2, columnspan=2, sticky="w", padx=(18, 0), pady=6
        )
        ttk.Checkbutton(
            password_options,
            text="显示密码",
            variable=self.show_password_var,
            command=self._toggle_password,
        ).pack(side="left")
        ttk.Checkbutton(
            password_options,
            text="保存密码（DPAPI 加密）",
            variable=self.remember_password_var,
        ).pack(side="left", padx=(16, 0))

        ttk.Label(form, text="服务器目标目录").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(form, textvariable=self.remote_path_var).grid(
            row=3, column=1, columnspan=3, sticky="ew", pady=6
        )

        ttk.Label(
            form,
            text=(
                "注意：这不是只读镜像。挂载后的可写能力由服务器上该账号的权限决定；"
                "若当前 SSH 账号对目录可写，Codex 等本地程序也可能修改服务器文件。"
            ),
            style="Warning.TLabel",
            wraplength=810,
            justify="left",
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 2))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=14)

        primary_buttons = ttk.Frame(buttons)
        primary_buttons.pack(fill="x")

        self.mount_button = ttk.Button(
            primary_buttons,
            text="新建挂载",
            command=self.mount_clicked,
        )
        self.mount_button.pack(side="left")

        self.unmount_button = ttk.Button(
            primary_buttons,
            text="解除所选盘符",
            command=self.unmount_clicked,
        )
        self.unmount_button.pack(side="left", padx=(10, 0))

        self.open_button = ttk.Button(
            primary_buttons,
            text="打开盘符",
            command=self.open_drive,
        )
        self.open_button.pack(side="left", padx=(10, 0))

        self.refresh_button = ttk.Button(
            primary_buttons,
            text="刷新状态",
            command=self.refresh_mounts,
        )
        self.refresh_button.pack(side="left", padx=(10, 0))

        secondary_buttons = ttk.Frame(buttons)
        secondary_buttons.pack(fill="x", pady=(10, 0))

        ttk.Button(
            secondary_buttons,
            text="环境检查",
            command=self.check_environment,
        ).pack(side="left")

        self.restart_explorer_button = ttk.Button(
            secondary_buttons,
            text="重启 Explorer（清幽灵盘）",
            command=self.restart_explorer,
        )
        self.restart_explorer_button.pack(side="left", padx=(10, 0))

        ttk.Button(
            secondary_buttons,
            text="清除已保存配置",
            command=self.clear_saved_config,
        ).pack(side="right")

        mappings_frame = ttk.LabelFrame(outer, text="当前网络盘", padding=10)
        mappings_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            mappings_frame,
            columns=("drive", "remote"),
            show="headings",
            height=9,
        )
        self.tree.heading("drive", text="盘符")
        self.tree.heading("remote", text="远程路径")
        self.tree.column("drive", width=80, anchor="center", stretch=False)
        self.tree.column("remote", width=620, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)
        self.tree.bind("<Double-1>", lambda _event: self.open_drive())

        scrollbar = ttk.Scrollbar(
            mappings_frame,
            orient="vertical",
            command=self.tree.yview,
        )
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        status_frame = ttk.Frame(outer)
        status_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(status_frame, text="状态：").pack(side="left")
        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            style="Status.TLabel",
        ).pack(side="left")

        ttk.Label(
            outer,
            text=(
                f"配置位置：{config_file_path()}  "
                "（密码不是明文，而是绑定当前 Windows 用户和当前电脑的 DPAPI 密文）"
            ),
            style="Hint.TLabel",
            wraplength=840,
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
        if values:
            self.drive_var.set(values[0])

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.mount_button.configure(state=state)
        self.unmount_button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.restart_explorer_button.configure(state=state)
        if message:
            self.status_var.set(message)

    def _collect_values(self) -> dict:
        try:
            port = int(self.port_var.get().strip())
        except ValueError as exc:
            raise ValueError("SSH 端口必须是整数。") from exc

        drive = normalize_drive(self.drive_var.get())
        host = self.host_var.get().strip()
        user = self.user_var.get().strip()
        password = self.password_var.get()
        remote_path = normalize_remote_path(self.remote_path_var.get())
        unc_path = build_sshfs_unc(user, host, port, remote_path)

        return {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "remote_path": remote_path,
            "drive": drive,
            "unc_path": unc_path,
        }

    def mount_clicked(self) -> None:
        if self.busy:
            return

        try:
            values = self._collect_values()
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        if not values["password"]:
            if not messagebox.askyesno(
                "密码为空",
                "密码框为空。仍然继续尝试挂载吗？",
                parent=self.root,
            ):
                return

        drive = values["drive"]
        map_code, mapped_remote = self.api.get_mapping(drive)

        if map_code == NO_ERROR and mapped_remote:
            replace = messagebox.askyesno(
                "盘符已被挂载",
                f"{drive} 当前映射到：\n{mapped_remote}\n\n"
                "是否先解除该映射，再建立新的挂载？",
                parent=self.root,
            )
            if not replace:
                return
            replace_existing = True
        else:
            replace_existing = False
            if os.path.exists(drive + "\\"):
                messagebox.showerror(
                    "盘符已被占用",
                    f"{drive} 已被本地设备或其他类型的连接占用，请换一个盘符。",
                    parent=self.root,
                )
                return

        self._set_busy(True, "正在连接 SSHFS，请稍候……")
        threading.Thread(
            target=self._mount_worker,
            args=(values, replace_existing),
            daemon=True,
        ).start()

    def _mount_worker(self, values: dict, replace_existing: bool) -> None:
        try:
            if replace_existing:
                unmount_code = self.api.unmount(values["drive"], force=True)
                if unmount_code not in (NO_ERROR, ERROR_NOT_CONNECTED):
                    self.tasks.put(
                        (
                            "mount_result",
                            {
                                "ok": False,
                                "code": unmount_code,
                                "phase": "unmount",
                                "values": values,
                            },
                        )
                    )
                    return

            code = self.api.mount(
                values["drive"],
                values["unc_path"],
                values["user"],
                values["password"],
            )
            self.tasks.put(
                (
                    "mount_result",
                    {
                        "ok": code == NO_ERROR,
                        "code": code,
                        "phase": "mount",
                        "values": values,
                    },
                )
            )
        except Exception as exc:
            self.tasks.put(("exception", exc))

    def unmount_clicked(self) -> None:
        if self.busy:
            return

        try:
            drive = normalize_drive(self.drive_var.get())
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        code, remote = self.api.get_mapping(drive)
        if code != NO_ERROR or not remote:
            messagebox.showinfo(
                "无需解除",
                f"{drive} 当前没有网络挂载。",
                parent=self.root,
            )
            return

        if not messagebox.askyesno(
            "确认解除挂载",
            f"即将解除：\n{drive} → {remote}\n\n"
            "请先关闭正在访问该盘符的 VS Code、Codex 和资源管理器窗口。\n"
            "是否继续？",
            parent=self.root,
        ):
            return

        self._set_busy(True, f"正在解除 {drive} ……")
        threading.Thread(
            target=self._unmount_worker,
            args=(drive,),
            daemon=True,
        ).start()

    def _unmount_worker(self, drive: str) -> None:
        try:
            code = self.api.unmount(drive, force=True)
            self.tasks.put(
                (
                    "unmount_result",
                    {
                        "ok": code in (NO_ERROR, ERROR_NOT_CONNECTED),
                        "code": code,
                        "drive": drive,
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
                        "程序异常",
                        repr(payload),
                        parent=self.root,
                    )
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self._poll_tasks)

    def _handle_mount_result(self, result: dict) -> None:
        self._set_busy(False)
        values = result["values"]

        if result["ok"]:
            try:
                self._save_successful_config(values)
                save_note = "已保存本次成功配置。"
            except Exception as exc:
                save_note = f"挂载成功，但保存配置失败：{exc}"

            self.status_var.set(
                f"挂载成功：{values['drive']} → {values['remote_path']}"
            )
            self.refresh_mounts()
            messagebox.showinfo(
                "挂载成功",
                f"{values['drive']} 已映射到：\n{values['unc_path']}\n\n{save_note}",
                parent=self.root,
            )
        else:
            phase_text = "解除旧挂载" if result["phase"] == "unmount" else "建立挂载"
            self.status_var.set(f"{phase_text}失败")
            messagebox.showerror(
                f"{phase_text}失败",
                friendly_error(self.api, result["code"]),
                parent=self.root,
            )
            self.refresh_mounts()

    def _handle_unmount_result(self, result: dict) -> None:
        self._set_busy(False)
        if result["ok"]:
            # 映射已经由 WNetCancelConnection2 真正解除。
            # 再通知 Explorer 刷新，尽量避免“此电脑”残留红叉幽灵盘。
            self.api.notify_drive_removed(result["drive"])
            self.refresh_mounts()
            self.status_var.set(f"已解除 {result['drive']}")
            messagebox.showinfo(
                "解除成功",
                f"{result['drive']} 已解除挂载；服务器文件不会被删除。\n\n"
                "程序已通知 Explorer 刷新。若“此电脑”仍残留红叉盘符，"
                "可点击“重启 Explorer（清幽灵盘）”。",
                parent=self.root,
            )
        else:
            self.status_var.set("解除挂载失败")
            messagebox.showerror(
                "解除挂载失败",
                friendly_error(self.api, result["code"]),
                parent=self.root,
            )
            self.refresh_mounts()

    def refresh_mounts(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        count = 0
        for letter in string.ascii_uppercase:
            drive = f"{letter}:"
            code, remote = self.api.get_mapping(drive)
            if code == NO_ERROR and remote:
                self.tree.insert("", "end", values=(drive, remote))
                count += 1

        self.status_var.set(f"已刷新，发现 {count} 个网络盘映射。")

    def open_drive(self) -> None:
        try:
            drive = normalize_drive(self.drive_var.get())
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        code, _remote = self.api.get_mapping(drive)
        if code != NO_ERROR:
            messagebox.showinfo(
                "盘符未挂载",
                f"{drive} 当前没有网络挂载。",
                parent=self.root,
            )
            return

        try:
            os.startfile(drive + "\\")  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror(
                "无法打开",
                str(exc),
                parent=self.root,
            )

    def _save_successful_config(self, values: dict) -> None:
        path = config_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        remember_password = bool(self.remember_password_var.get())
        encrypted_password = (
            self.api.protect_text(values["password"])
            if remember_password
            else ""
        )

        data = {
            "version": CONFIG_VERSION,
            "host": values["host"],
            "port": values["port"],
            "user": values["user"],
            "remote_path": values["remote_path"],
            "drive": values["drive"],
            "remember_password": remember_password,
            "password_dpapi": encrypted_password,
        }

        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, path)

    def _load_config(self) -> None:
        path = config_file_path()
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data.get("version", 0)) != CONFIG_VERSION:
                return

            self.host_var.set(str(data.get("host", self.host_var.get())))
            self.port_var.set(str(data.get("port", self.port_var.get())))
            self.user_var.set(str(data.get("user", self.user_var.get())))
            self.remote_path_var.set(
                str(data.get("remote_path", self.remote_path_var.get()))
            )
            self.drive_var.set(str(data.get("drive", self.drive_var.get())))

            remember = bool(data.get("remember_password", False))
            self.remember_password_var.set(remember)
            if remember and data.get("password_dpapi"):
                self.password_var.set(
                    self.api.unprotect_text(str(data["password_dpapi"]))
                )
            self.status_var.set("已加载上次成功挂载的配置。")
        except Exception as exc:
            self.status_var.set("保存配置读取失败；已使用默认值。")
            messagebox.showwarning(
                "配置读取失败",
                "无法读取或解密上次保存的配置。\n"
                "可能原因：更换了 Windows 用户、换了电脑，或配置文件损坏。\n\n"
                f"{exc}",
                parent=self.root,
            )

    def clear_saved_config(self) -> None:
        path = config_file_path()
        if not path.exists():
            messagebox.showinfo(
                "没有保存配置",
                "当前没有已保存的配置。",
                parent=self.root,
            )
            return

        if not messagebox.askyesno(
            "确认清除",
            "是否删除保存的服务器信息和加密密码？\n"
            "这不会解除当前挂载，也不会删除服务器文件。",
            parent=self.root,
        ):
            return

        try:
            path.unlink()
            self.password_var.set("")
            self.status_var.set("已清除保存配置。")
            messagebox.showinfo(
                "已清除",
                "保存配置已删除。",
                parent=self.root,
            )
        except OSError as exc:
            messagebox.showerror(
                "清除失败",
                str(exc),
                parent=self.root,
            )

    def restart_explorer(self) -> None:
        """
        兜底清理 Explorer 的网络盘显示缓存。

        这会短暂关闭任务栏、桌面和所有资源管理器窗口，然后立即重新启动
        explorer.exe。它不会重启电脑，也不会删除服务器或本地文件。
        """
        if not messagebox.askyesno(
            "确认重启 Explorer",
            "该操作会短暂关闭任务栏、桌面和所有文件资源管理器窗口，"
            "随后立即恢复。\n\n"
            "正在复制、移动或重命名文件时不要执行。\n"
            "是否继续？",
            parent=self.root,
        ):
            return

        try:
            flags = CREATE_NO_WINDOW
            subprocess.run(
                ["taskkill", "/f", "/im", "explorer.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=flags,
            )
            subprocess.Popen(
                ["explorer.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            self.root.after(1200, self.refresh_mounts)
            self.status_var.set("Explorer 已重启，正在刷新盘符状态……")
            messagebox.showinfo(
                "已重启 Explorer",
                "任务栏和桌面会短暂消失后恢复。\n"
                "红叉幽灵盘通常会随之清除。",
                parent=self.root,
            )
        except OSError as exc:
            messagebox.showerror(
                "重启 Explorer 失败",
                str(exc),
                parent=self.root,
            )

    def check_environment(self) -> None:
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        program_files_x86 = Path(
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        )

        sshfs_candidates = [
            program_files / "SSHFS-Win" / "bin" / "sshfs.exe",
            program_files_x86 / "SSHFS-Win" / "bin" / "sshfs.exe",
        ]
        winfsp_candidates = [
            program_files / "WinFsp",
            program_files_x86 / "WinFsp",
        ]

        sshfs_found = next((p for p in sshfs_candidates if p.exists()), None)
        winfsp_found = next((p for p in winfsp_candidates if p.exists()), None)

        lines = [
            f"操作系统：Windows（{sys.getwindowsversion().major}.{sys.getwindowsversion().minor}）",
            f"Python：{sys.version.split()[0]}",
            (
                f"SSHFS-Win：已找到 {sshfs_found}"
                if sshfs_found
                else "SSHFS-Win：未在常见安装目录找到"
            ),
            (
                f"WinFsp：已找到 {winfsp_found}"
                if winfsp_found
                else "WinFsp：未在常见安装目录找到"
            ),
        ]

        if sshfs_found and winfsp_found:
            lines.append("\n初步检查通过。最终仍以实际挂载结果为准。")
        else:
            lines.append(
                "\n若你已经能手动使用 net use 挂载，则可能只是安装在了其他目录。"
            )

        messagebox.showinfo(
            "环境检查",
            "\n".join(lines),
            parent=self.root,
        )


def main() -> None:
    if os.name != "nt":
        print("本程序只能在 Windows 上运行。", file=sys.stderr)
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
