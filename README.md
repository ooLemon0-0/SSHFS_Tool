# SSHFS Mount Manager

[English](#english) | [简体中文](#chinese)

<a id="english"></a>

## English

### Project overview

SSHFS Mount Manager is a small Windows desktop utility for mounting a remote Linux directory as a Windows drive through SSHFS-Win.

It provides a reusable GUI for entering SSH connection details, mounting a drive, disconnecting an existing mapping, reviewing current network drives, and restarting Windows Explorer when a disconnected drive remains visible as a red-cross “ghost drive”.

The project does **not** contain any bundled server address, username, password, or remote directory. On first use, users enter their own connection details. The application only saves settings locally after a successful mount.

### Features

- Mount a remote absolute path as a Windows drive letter.
- Enter the SSH host, port, username, password, remote directory, and drive letter in the GUI.
- Disconnect an existing network-drive mapping.
- Display current Windows network-drive mappings.
- Open the mounted drive directly from the application.
- Save the last successful connection settings.
- Protect a saved password with Windows DPAPI instead of storing it as plaintext.
- Notify Windows Explorer after unmounting to reduce stale drive icons.
- Provide a fallback **Restart Explorer** button for clearing red-cross ghost drives.
- Keep the password out of the `net use` command line by calling the Windows WNet API directly.

### Required software

This application requires Windows 10 or Windows 11, Python 3 with `tkinter`, and the following two system components.

**Before running the application, download and install both MSI installers. Install WinFsp first, then SSHFS-Win.**

1. [WinFsp](https://winfsp.dev/)  
   Download the Windows `.msi` installer from the official WinFsp website.

2. [SSHFS-Win](https://github.com/winfsp/sshfs-win)  
   Download the Windows `.msi` installer from the SSHFS-Win project page or its releases.

### Run

Clone or download this repository, then run:

```text
start_sshs_manager.cmd
```

Alternatively, open PowerShell in the project directory and run:

```powershell
python .\sshfs_mount_manager.py
```

### First use

Enter:

- SSH server IP address or hostname
- SSH port
- SSH username
- SSH password
- Absolute remote directory, for example `/home/user/project`
- Windows drive letter, for example `X:`

Click **New Mount** in the GUI. Connection details are saved only after the mount succeeds.

### Local settings and password storage

Settings are stored outside the repository at:

```text
%APPDATA%\SSHFS-Mount-Manager\config.json
```

When password saving is enabled, the password is encrypted with Windows DPAPI and is normally decryptable only by the same Windows user on the same computer.

No personal connection configuration is written into the source tree.

### Security notes

SSHFS exposes the real remote directory; it is not an independent copy or a read-only mirror.

- If the SSH account has write permission, local applications such as editors or coding agents may modify remote files.
- For enforced read-only access, use a server account or server-side permissions that deny writes.
- File contents read through SSHFS are transferred to the local computer and may be processed by the local application that opens them.
- Confirm your organization’s source-code and data-handling rules before using cloud-based coding assistants.
- Do not restart Explorer while files are being copied, moved, or renamed.

### Ghost-drive behavior

Windows Explorer can occasionally keep a disconnected network drive visible with a red cross even after the underlying mapping has already been removed.

The application first sends a Windows Shell drive-removal notification. If the icon remains, use **Restart Explorer**. This restarts the taskbar, desktop shell, and open File Explorer windows; it does not restart Windows or delete remote files.

---

<a id="chinese"></a>

## 简体中文

### 项目说明

SSHFS Mount Manager 是一个 Windows 桌面小工具，用于通过 SSHFS-Win 将远程 Linux 目录挂载为 Windows 盘符。

它提供可复用的图形界面，让用户填写 SSH 连接信息、新建挂载、解除已有映射、查看当前网络盘，并在解除挂载后仍残留红叉“幽灵盘”时重启 Windows Explorer。

项目中**不包含任何预设的服务器地址、用户名、密码或远程目录**。用户第一次使用时需要自行填写。程序只会在挂载成功后，将连接设置保存到用户自己的 Windows 配置目录中。

### 功能

- 将服务器绝对路径挂载为 Windows 盘符。
- 在界面中填写 SSH 主机、端口、用户名、密码、远程目录和盘符。
- 解除现有网络盘映射。
- 显示当前 Windows 网络盘列表。
- 从程序中直接打开挂载盘。
- 保存上一次成功挂载的连接设置。
- 使用 Windows DPAPI 加密保存密码，不以明文写入配置文件。
- 解除挂载后主动通知 Windows Explorer 刷新盘符。
- 提供 **重启 Explorer** 兜底按钮，用于清理红叉幽灵盘。
- 通过 Windows WNet API 建立连接，不把密码拼接进 `net use` 命令行。

### 依赖与安装

程序需要 Windows 10 或 Windows 11、带有 `tkinter` 的 Python 3，以及下面两个系统组件。

**运行程序之前，请先下载并安装这两个 MSI。建议先安装 WinFsp，再安装 SSHFS-Win。**

1. [WinFsp](https://winfsp.dev/)  
   请从 WinFsp 官方网站下载 Windows `.msi` 安装包。

2. [SSHFS-Win](https://github.com/winfsp/sshfs-win)  
   请从 SSHFS-Win 项目页面或 Releases 下载 Windows `.msi` 安装包。

### 启动

克隆或下载项目后，双击：

```text
start_sshs_manager.cmd
```

也可以在项目目录中打开 PowerShell，执行：

```powershell
python .\sshfs_mount_manager.py
```

### 第一次使用

请填写：

- SSH 服务器 IP 或主机名
- SSH 端口
- SSH 用户名
- SSH 密码
- 服务器绝对目录，例如 `/home/user/project`
- Windows 盘符，例如 `X:`

点击界面中的“新建挂载”。只有挂载成功后，程序才会保存本次连接信息。

### 本地配置与密码保存

配置保存在仓库目录之外：

```text
%APPDATA%\SSHFS-Mount-Manager\config.json
```

启用密码保存后，密码会使用 Windows DPAPI 加密。通常只有同一台电脑上的同一个 Windows 用户能够解密。

源代码目录中不会写入用户自己的连接配置。

### 安全说明

SSHFS 暴露的是服务器上的真实目录，不是独立副本，也不是天然只读镜像。

- SSH 账号有写权限时，编辑器或代码 Agent 等本地程序可能修改远程文件。
- 需要强制只读时，应使用只读服务器账号，或在服务器端设置禁止写入的权限。
- 通过 SSHFS 读取的内容会传输到本地电脑，并可能被打开文件的本地程序处理。
- 使用云端代码助手前，应确认所在组织的源码和数据安全规定。
- 正在复制、移动或重命名文件时，不要重启 Explorer。

### 幽灵盘说明

Windows Explorer 偶尔会在网络映射已经解除后，继续显示一个带红叉的旧盘符。

程序会先发送 Windows Shell 的盘符移除通知。如果图标仍然存在，可以点击“重启 Explorer”。该操作会重启任务栏、桌面外壳和已打开的文件资源管理器窗口，但不会重启 Windows，也不会删除服务器文件。
