# SSHFS Mount Manager

一个用于把离线服务器目录挂载到本地，并交给 AI 编程工具阅读和分析的跨平台图形界面工具。

A cross-platform GUI for mounting directories from offline SSH servers so local AI coding tools can inspect and analyze them.

[简体中文](#chinese) | [English](#english)
## 下载 / Download

| 平台 | 最新版本 | 源码 |
|---|---|---|
| Windows 10/11 | [下载 Windows 版](https://github.com/ooLemon0-0/SSHFS_Tool/releases/latest/download/SSHFS-Mount-Manager-Windows.zip) | [查看 Windows 源码](./windows/) |
| macOS | [下载 macOS 版](https://github.com/ooLemon0-0/SSHFS_Tool/releases/latest/download/SSHFS-Mount-Manager-macOS.zip) | [查看 macOS 源码](./macos/) |

[查看最新 Release 和更新说明](https://github.com/ooLemon0-0/SSHFS_Tool/releases/latest)

## Platform packages / 版本选择

| Platform | Source folder | Launcher | Required filesystem tools |
|---|---|---|---|
| Windows 10/11 | [Windows version](./windows/) | [`start_sshs_manager.cmd`](./windows/start_sshs_manager.cmd) | [WinFsp](https://winfsp.dev/) + [SSHFS-Win](https://github.com/winfsp/sshfs-win) |
| macOS | [macOS version](./macos/) | [`start_sshs_manager.command`](./macos/start_sshs_manager.command) | [macFUSE](https://macfuse.github.io/) + [SSHFS for macFUSE](https://github.com/macfuse/macfuse/wiki/File-Systems-%E2%80%90-SSHFS) |

在 GitHub 仓库页面选择 **Code → Download ZIP**，可以一次下载 Windows 和 macOS 两个版本。下载后只需进入对应系统目录运行启动脚本。

On the GitHub repository page, choose **Code → Download ZIP** to download both platform versions, then run the launcher inside the matching platform folder.

---

<a id="chinese"></a>

## 简体中文

### 项目说明

这个项目主要用于解决下面这种场景：

> 一台服务器无法连接外网，但可以通过 SSH 访问；本地的 AI 编程工具无法直接读取服务器目录，而人工逐个查找、打开和整理项目文件又非常费时。

SSHFS Mount Manager 将服务器上的指定目录挂载为本地文件系统：

```text
离线服务器目录
        ↓ SSH / SFTP
Windows 盘符或 macOS 本地目录
        ↓
Codex、Cursor、Claude Code、VS Code 等本地工具
```

挂载完成后，本地运行的 AI 工具、代码编辑器和文件分析工具可以像读取普通文件夹一样读取远程项目，从而帮助用户：

- 分析陌生项目的目录结构；
- 查找训练、推理和配置入口；
- 追踪代码调用关系；
- 总结模块功能；
- 搜索指定类、函数和配置；
- 减少手动浏览和整理服务器文件的工作量。

例如，服务器目录：

```text
/home/user/project
```

在 Windows 上可以挂载为：

```text
X:\
```

在 macOS 上可以挂载为：

```text
~/SSHFS-Mount
```

SSHFS 不会预先把整个项目完整复制到本地。它建立的是基于 SSH/SFTP 的远程文件系统映射：本地程序访问某个文件时，SSHFS 才从服务器读取对应内容。

项目中不包含任何预设的服务器地址、用户名、密码或远程目录。第一次使用时需要由用户自行填写。程序只会在挂载成功后，将连接设置保存到当前操作系统用户的本地配置目录中。

### 项目结构

```text
SSHFS-Mount-Manager/
├── README.md
├── windows/
│   ├── sshfs_mount_manager_windows.py
│   └── start_sshs_manager.cmd
└── macos/
    ├── sshfs_mount_manager_macos.py
    └── start_sshs_manager.command
```

### 通用功能

- 在图形界面中填写 SSH 主机、端口、用户名、密码和远程目录；
- 新建 SSHFS 挂载；
- 解除已有挂载；
- 显示当前 SSHFS 网络盘或挂载卷；
- 从程序中直接打开挂载位置；
- 只在挂载成功后保存连接设置；
- 避免在项目源码中写入个人服务器配置；
- 提供环境检查；
- 提供文件管理器重启按钮，用于清理解除挂载后残留的幽灵盘或幽灵卷。

### Windows 版本

#### 安装依赖

运行 Windows 版本之前，必须先安装下面两个 MSI。建议按照以下顺序安装：

1. [WinFsp](https://winfsp.dev/)  
   从官方网站下载并安装 Windows `.msi`。

2. [SSHFS-Win](https://github.com/winfsp/sshfs-win)  
   从项目页面或 Releases 下载并安装 Windows `.msi`。

安装完成后，进入 `windows` 目录并双击：

```text
start_sshs_manager.cmd
```

也可以在 PowerShell 中执行：

```powershell
python .\windows\sshfs_mount_manager_windows.py
```

#### Windows 密码保存

Windows 版本使用 Windows DPAPI 加密密码，并将配置保存到：

```text
%APPDATA%\SSHFS-Mount-Manager\config.json
```

密码不会以明文写入仓库。DPAPI 密文通常只能由同一台电脑上的同一个 Windows 用户解密。

#### Windows 幽灵盘

Windows Explorer 偶尔会在底层映射已经解除后，继续显示一个带红叉的旧盘符。

程序会先发送 Windows Shell 的盘符移除通知。如果图标仍然存在，可以点击：

```text
重启 Explorer（清幽灵盘）
```

该操作会重启任务栏、桌面外壳和文件资源管理器窗口，但不会重启 Windows，也不会删除服务器文件。

### macOS 版本

#### 安装依赖

macOS 版本需要 macFUSE 与 SSHFS。可以使用下面两种安装方式之一。

##### 方式一：下载安装包

1. [下载 macFUSE](https://macfuse.github.io/)
2. [下载 SSHFS for macFUSE](https://github.com/macfuse/macfuse/wiki/File-Systems-%E2%80%90-SSHFS)

先安装 macFUSE，再安装 SSHFS。安装过程中如果 macOS 要求在“系统设置 → 隐私与安全性”中允许系统软件，按照系统提示操作，并在要求时重启电脑。

##### 方式二：Homebrew

已经安装 Homebrew 时，可以执行：

```bash
brew install --cask sshfs-mac
```

Homebrew 的 `sshfs-mac` cask 会声明 macFUSE 依赖。

#### 启动 macOS 版本

进入 `macos` 目录，双击：

```text
start_sshs_manager.command
```

第一次运行时，如果系统提示脚本没有执行权限，在终端中执行：

```bash
chmod +x ./macos/start_sshs_manager.command
./macos/start_sshs_manager.command
```

也可以直接运行 Python 源码：

```bash
python3 ./macos/sshfs_mount_manager_macos.py
```

#### macOS 密码保存

macOS 版本将非敏感设置保存到：

```text
~/Library/Application Support/SSHFS Mount Manager/config.json
```

启用密码保存后，密码会写入当前用户的 macOS 钥匙串，而不会以明文写入 JSON 或仓库目录。

挂载时，程序通过 SSHFS 的 `password_stdin` 选项将密码传给 SSHFS，不会把密码放进可见的 SSHFS 命令行参数中。

#### macOS 幽灵卷

macOS Finder 偶尔可能在解除挂载后继续显示旧卷。可以点击：

```text
重启 Finder（清幽灵卷）
```

该操作会关闭并重新启动 Finder 窗口，但不会重启 macOS，也不会删除服务器文件。

### 第一次使用

请填写：

- SSH 服务器 IP 或主机名；
- SSH 端口；
- SSH 用户名；
- SSH 密码；
- 服务器绝对目录，例如 `/home/user/project`；
- Windows 盘符，或 macOS 本地空目录。

挂载完成后，可以在本地 AI 编程工具中打开挂载位置，并将其作为工作区分析。

### 重要安全说明

SSHFS 暴露的是服务器上的真实目录，不是独立副本，也不是天然只读镜像。

- SSH 账号有写权限时，本地编辑器、AI Agent 或其他程序可能修改、创建或删除远程文件；
- 需要强制只读时，应使用只读服务器账号，或在服务器端设置禁止写入的权限；
- 即使服务器本身无法访问外网，通过 SSHFS 读取的内容仍会传输到本地电脑；
- 云端 AI 工具可能会将其读取的代码片段发送到模型服务，具体行为取决于工具、账号类型和数据设置；
- 在处理公司源码、内部文档或敏感数据前，应先确认所在组织的数据安全规定；
- 解除挂载前，应关闭正在访问挂载位置的 AI 工具、编辑器、终端和文件管理器；
- 正在复制、移动或重命名文件时，不要强制解除挂载或重启文件管理器。

---

<a id="english"></a>

## English

### Project overview

This project is intended for the following workflow:

> A server cannot access the public internet but is reachable through SSH. A local AI coding tool needs to inspect the remote project, while manually opening and organizing every file would take too much time.

SSHFS Mount Manager maps a selected server directory into the local filesystem:

```text
Offline server directory
        ↓ SSH / SFTP
Windows drive or macOS mount directory
        ↓
Codex, Cursor, Claude Code, VS Code, and other local tools
```

After mounting, locally running AI tools, code editors, and analysis utilities can inspect the remote project like a normal local workspace. This can reduce the work required to understand directory structure, locate entry points, trace code paths, search functions, and summarize modules.

SSHFS does not create a complete local copy in advance. It creates a remote filesystem mapping over SSH/SFTP and transfers files when local applications access them.

The repository contains no bundled server address, username, password, or remote directory. Users provide their own connection details on first use. Settings are saved locally only after a successful mount.

### Project layout

```text
SSHFS-Mount-Manager/
├── README.md
├── windows/
│   ├── sshfs_mount_manager_windows.py
│   └── start_sshs_manager.cmd
└── macos/
    ├── sshfs_mount_manager_macos.py
    └── start_sshs_manager.command
```

### Common features

- Enter SSH host, port, username, password, and remote directory in a GUI.
- Create and remove SSHFS mounts.
- Display current SSHFS drives or volumes.
- Open the mounted location from the application.
- Save settings only after a successful mount.
- Keep personal server configuration out of the source tree.
- Check the local SSHFS environment.
- Restart Explorer or Finder to clear stale ghost drives or volumes.

### Windows

Install both MSI packages before running the Windows version:

1. [WinFsp](https://winfsp.dev/)
2. [SSHFS-Win](https://github.com/winfsp/sshfs-win)

Then run:

```text
windows\start_sshs_manager.cmd
```

Or:

```powershell
python .\windows\sshfs_mount_manager_windows.py
```

The Windows version protects saved passwords with Windows DPAPI and stores settings at:

```text
%APPDATA%\SSHFS-Mount-Manager\config.json
```

### macOS

Install macFUSE and SSHFS:

1. [macFUSE](https://macfuse.github.io/)
2. [SSHFS for macFUSE](https://github.com/macfuse/macfuse/wiki/File-Systems-%E2%80%90-SSHFS)

Homebrew users can install the macOS package with:

```bash
brew install --cask sshfs-mac
```

Then run:

```bash
./macos/start_sshs_manager.command
```

If needed:

```bash
chmod +x ./macos/start_sshs_manager.command
```

Or run the source directly:

```bash
python3 ./macos/sshfs_mount_manager_macos.py
```

The macOS version stores non-secret settings at:

```text
~/Library/Application Support/SSHFS Mount Manager/config.json
```

Remembered passwords are stored in the current user's macOS Keychain.

### Security notes

SSHFS exposes the real remote directory. It is not an independent copy or an inherently read-only mirror.

- If the SSH account has write permission, local editors and AI agents may modify remote files.
- For enforced read-only access, use a read-only server account or server-side permissions.
- Files accessed through SSHFS are transferred to the local computer.
- Cloud-based AI tools may send selected code or context to their model service.
- Confirm organizational source-code and data-handling policies before processing internal or sensitive files.
- Close applications that are using the mount before unmounting.
- Do not force-unmount or restart the file manager while files are being copied, moved, or renamed.
