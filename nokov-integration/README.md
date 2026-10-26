# NOKOV / XINGYING 本地接口

此目录是对 NOKOV 官方 Python SDK 和公开 UDP 录制协议的本地 JSON 命令封装，不是 NOKOV 官方 AI 插件或 MCP 服务。

## 功能与验证范围

- `doctor`：检查 Python SDK 与 DLL 能否加载，不发起网络连接。
- `probe`：连接配置中的 XINGYING SDK 地址，尝试读取一帧。
- `start` / `stop`：预览 XML 录制命令，只有显式指定 `--send` 才发送。
- `verify_integration.py`：本机安装、UDP 回环和现场只读连接验证；不是云端离线测试。

开发时使用 XINGYING 4.6.0.7923 和官方 SDK 包 `XING_Python_SDK_4105645.zip`（Python 包 `nokovpy` 3.0.1）。曾完成本地 DLL 加载和真实数据帧读取；连接状态需要每次重新验证。尚未实测真实开始／停止录制，不包含标定、创建资产、数据修复或导出控制。

## 安装与配置

需要 Windows、64 位 Python 和对应的官方 NOKOV SDK。SDK、DLL、安装包及虚拟环境未提交到仓库。

在仓库根目录使用 PowerShell，以下 `python` 应为实际安装的 64 位 Python：

```powershell
python -m venv nokov-integration/.venv
# 从官方 SDK 获取适用于当前 Python 的 wheel，再安装：
.\nokov-integration\.venv\Scripts\python.exe -m pip install 'C:\path\to\official\nokovpy.whl'
Copy-Item nokov-integration/config.example.json nokov-integration/config.json
```

wheel 路径是占位示例，请替换为下载包中的实际文件名。按 SDK 说明安装所需运行库，编辑 `config.json` 中的地址和工程目录。`server_ip` 必须与 XINGYING 数据广播所选地址一致；`capture_directory` 必须与当前工程匹配。本机配置和验证报告不提交。

## 使用

在仓库根目录运行：

```powershell
.\nokov-integration\nokov.ps1 doctor
.\nokov-integration\nokov.ps1 probe --seconds 3
.\nokov-integration\nokov.ps1 start --name take001
.\nokov-integration\nokov.ps1 stop --name take001
```

`probe` 需要 XINGYING 启用 SDK 广播；读取帧时还需要实时播放或回放采集数据。此封装不会自动向其他聊天应用注册工具。

## 发送录制命令

先按官方文档开启 XINGYING 捕获远程控制，确认端口及工程目录，并连接镜头。确实需要改变录制状态时运行：

```powershell
.\nokov-integration\nokov.ps1 start --name take001 --send
.\nokov-integration\nokov.ps1 stop --name take001 --send
```

UDP 没有执行确认响应。`sent: true` 仅表示已经发送，`execution_confirmed` 仍为 `false`，需要在 XINGYING 中确认状态。不要将发送成功视为录制成功。

## 验证脚本

```powershell
.\nokov-integration\.venv\Scripts\python.exe nokov-integration/verify_integration.py
```

此脚本要求原开发版本的 SDK 压缩包位于 `downloads/XING_Python_SDK_4105645.zip`，并校验已记录的 SHA-256。它检查 XML 编码、文件名、预览行为和 UDP 本机回环，还会执行现场只读 `probe`，生成本地 `verification.json`。它不向 XINGYING 发送录制命令。

## 官方资料

- [下载中心](https://en.nokov.com/support/downloads.html)
- [开发时使用的 SDK 下载包](https://oss1.nokov.com.cn/resources/Software/Others/XING_Python_SDK_4105645.zip)
- [SDK 介绍](https://xingying-docs.nokov.com/xingying/XingYing4.6-CN/shi-qi-cha-jian-sdk/shi-san-sdk/)
- [SDK 广播设置](https://xingying-docs.nokov.com/xingying/XingYing4.6-CN/liu-shi-tu-jie-shao/san-shu-ju-guang-bo/)
- [UDP 远程控制协议](https://xingying-docs.nokov.com/xingying/XingYing4.6-CN/shi-ba-udp-bu-huo-guang-bo-chu-fa/yi-yuan-cheng-kong-zhi/)
