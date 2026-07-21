# SSHFS Mount Manager

[简体中文](#简体中文) | [English](#english)

<a id="简体中文"></a>

## 简体中文

### 项目说明

这个项目主要用于解决下面这种场景：

> 一台服务器无法连接外网，但可以通过 SSH 访问；本地的 AI 编程工具无法直接读取服务器目录，而人工逐个查找、打开和整理项目文件又非常费时。

SSHFS Mount Manager 通过 SSHFS-Win，将服务器上的指定目录挂载为 Windows 本地盘符。挂载完成后，本地运行的 AI 工具、代码编辑器和文件分析工具可以像读取普通文件夹一样读取该盘符，从而帮助用户：

- 分析陌生项目的目录结构；
- 查找训练、推理和配置入口；
- 追踪代码调用关系；
- 总结模块功能；
- 减少手动浏览和整理服务器文件的工作量。

例如，远程服务器目录：

```text
/home/user/project
```

可以被挂载为：

```text
X:\
```

随后可以在本地 Codex、Cursor、Claude Code、VS Code 或其他能够读取本地工作区的工具中打开 `X:\`。

SSHFS 并不会预先把整个项目完整复制到本地。它建立的是一个基于 SSH/SFTP 的远程文件系统映射：本地程序访问盘符中的文件时，SSHFS-Win 才通过 SSH 从服务器读取对应内容。

本项目为上述流程提供一个可复用的 Windows 图形界面，用于填写连接信息、新建挂载、解除映射、查看当前网络盘，以及清理解除挂载后可能残留的红叉“幽灵盘”。

项目中**不包含任何预设的服务器地址、用户名、密码或远程目录**。第一次使用时需要由用户自行填写。程序只会在挂载成功后，将连接设置保存到当前 Windows 用户的本地配置目录中。

### 功能

- 将服务器绝对路径挂载为 Windows 盘符；
- 在图形界面中填写 SSH 主机、端口、用户名、密码、远程目录和盘符；
- 一键新建 SSHFS 挂载；
- 解除已有网络盘映射；
- 显示当前 Windows 网络盘列表；
- 从程序中直接打开挂载盘；
- 保存上一次成功挂载的连接设置；
- 使用 Windows DPAPI 加密保存密码，不以明文写入配置文件；
- 通过 Windows WNet API 建立连接，不把密码拼接进 `net use` 命令行；
- 解除挂载后主动通知 Windows Explorer 刷新盘符；
- 提供“重启 Explorer”兜底按钮，用于清理红叉幽灵盘。

### 依赖与安装

程序需要：

- Windows 10 或 Windows 11；
- 带有 `tkinter` 的 Python 3；
- WinFsp；
- SSHFS-Win。

**运行程序之前，请先下载并安装下面两个 MSI。建议先安装 WinFsp，再安装 SSHFS-Win。**

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

请在界面中填写：

- SSH 服务器 IP 或主机名；
- SSH 端口；
- SSH 用户名；
- SSH 密码；
- 服务器绝对目录，例如 `/home/user/project`；
- Windows 盘符，例如 `X:`。

点击“新建挂载”。只有挂载成功后，程序才会保存本次连接信息。

挂载完成后，可以：

1. 在资源管理器中打开对应盘符；
2. 使用本地 AI 编程工具或编辑器打开该盘符；
3. 将它作为项目工作区进行只读分析或代码浏览。

### 本地配置与密码保存

配置保存在仓库目录之外：

```text
%APPDATA%\SSHFS-Mount-Manager\config.json
```

启用密码保存后，密码会使用 Windows DPAPI 加密。通常只有同一台电脑上的同一个 Windows 用户能够解密。

源代码目录中不会写入用户自己的连接配置。

### 重要安全说明

SSHFS 暴露的是服务器上的真实目录，不是独立副本，也不是天然只读镜像。

- SSH 账号有写权限时，编辑器、AI Agent 或其他本地程序可能修改、创建或删除远程文件；
- 需要强制只读时，应使用只读服务器账号，或在服务器端设置禁止写入的权限；
- 即使服务器本身无法访问外网，通过 SSHFS 读取的内容仍会传输到本地电脑；
- 云端 AI 工具可能会将其读取的代码片段发送到模型服务，具体行为取决于所使用的工具、账号类型和数据设置；
- 在处理公司源码、内部文档或敏感数据前，应先确认所在组织的数据安全规定；
- 正在复制、移动或重命名文件时，不要重启 Explorer。

### 解除挂载

在程序中选择对应盘符，然后点击“解除所选盘符”。

解除挂载只会删除 Windows 与服务器目录之间的映射关系，不会删除服务器上的文件。

建议在解除前关闭正在访问该盘符的：

- AI 编程工具；
- VS Code 或其他编辑器；
- 文件资源管理器窗口；
- 终端和脚本进程。

### 幽灵盘说明

Windows Explorer 偶尔会在网络映射已经解除后，继续显示一个带红叉的旧盘符。

这种情况下，底层 SSHFS 映射通常已经不存在，只是 Explorer 仍保留着旧的显示缓存。

程序会先发送 Windows Shell 的盘符移除通知。如果图标仍然存在，可以点击“重启 Explorer”。

该操作会重新启动：

- Windows 任务栏；
- 桌面外壳；
- 已打开的文件资源管理器窗口。

它不会重启 Windows，也不会删除本地或服务器文件。

---

<a id="english"></a>

## English

### Project overview

SSHFS Mount Manager is designed for a common offline-server workflow:

> A remote server cannot access the public internet but is reachable through SSH, while a local AI coding tool needs to inspect the files without manually browsing the entire project.

The application mounts a selected remote Linux directory as a Windows drive through SSHFS-Win. After mounting, locally running AI tools, code editors, and analysis utilities can open the drive as a normal workspace and help inspect project structure, locate entry points, trace code paths, and summarize modules.

For example:

```text
Remote: /home/user/project
Local:  X:\
```

SSHFS does not make a complete local copy in advance. It creates a remote filesystem mapping over SSH/SFTP, and files are transferred when local applications access them.

The project provides a reusable Windows GUI for entering SSH connection details, mounting a drive, disconnecting an existing mapping, reviewing current network drives, and restarting Windows Explorer when a disconnected drive remains visible as a red-cross ghost drive.

The repository contains **no bundled server address, username, password, or remote directory**. Users provide their own connection details on first use. Settings are stored locally only after a successful mount.

### Features

- Mount a remote absolute path as a Windows drive letter.
- Enter the SSH host, port, username, password, remote directory, and drive letter in the GUI.
- Disconnect an existing network-drive mapping.
- Display current Windows network-drive mappings.
- Open the mounted drive directly from the application.
- Save the last successful connection settings.
- Protect a saved password with Windows DPAPI instead of storing it as plaintext.
- Keep the password out of the `net use` command line by calling the Windows WNet API directly.
- Notify Windows Explorer after unmounting to reduce stale drive icons.
- Provide a fallback **Restart Explorer** button for clearing red-cross ghost drives.

### Required software

The application requires:

- Windows 10 or Windows 11;
- Python 3 with `tkinter`;
- WinFsp;
- SSHFS-Win.

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

- SSH server IP address or hostname;
- SSH port;
- SSH username;
- SSH password;
- Absolute remote directory, for example `/home/user/project`;
- Windows drive letter, for example `X:`.

Click **New Mount** in the GUI. Connection details are saved only after the mount succeeds.

After mounting, open the mapped drive in a local AI coding tool or editor and use it as a workspace for code inspection.

### Local settings and password storage

Settings are stored outside the repository at:

```text
%APPDATA%\SSHFS-Mount-Manager\config.json
```

When password saving is enabled, the password is encrypted with Windows DPAPI and is normally decryptable only by the same Windows user on the same computer.

No personal connection configuration is written into the source tree.

### Security notes

SSHFS exposes the real remote directory; it is not an independent copy or a read-only mirror.

- If the SSH account has write permission, local editors or AI agents may modify remote files.
- For enforced read-only access, use a server account or server-side permissions that deny writes.
- File contents read through SSHFS are transferred to the local computer.
- Cloud-based AI tools may send selected code or context to their model service, depending on the tool and account settings.
- Confirm your organization’s source-code and data-handling rules before processing internal or sensitive files.
- Do not restart Explorer while files are being copied, moved, or renamed.

### Ghost-drive behavior

Windows Explorer can occasionally keep a disconnected network drive visible with a red cross even after the underlying mapping has already been removed.

The application first sends a Windows Shell drive-removal notification. If the icon remains, use **Restart Explorer**. This restarts the taskbar, desktop shell, and open File Explorer windows; it does not restart Windows or delete remote files.
