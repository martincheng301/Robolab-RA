# Robolab-RA

手物交互采集的阶段性工具：NOKOV / XINGYING 本地接口，以及 C3D 导出数据检查。

## 当前内容

| 目录 | 功能 |
| --- | --- |
| `nokov-integration/` | 官方 Python SDK 的 JSON 命令封装，以及 UDP 录制命令预览和发送 |
| `hand-object-capture/` | 检查 C3D 导出，保留每帧坐标，生成 CSV 和检查报告 |

这是采集工具原型，尚未实现数据手套接入、跨设备同步、手部模型拟合或完整 OakInk 格式转换。阶段性单点检查不能证明已经完成手物交互数据集采集。

## 离线分析与云端环境

建议使用 Python 3.12：

```sh
python -m pip install -r requirements.txt
python hand-object-capture/inspect_c3d.py --help
python hand-object-capture/inspect_c3d.py /path/to/take.c3d outputs/take-v1
```

使用独立的新输出目录。脚本复制输入文件，并生成原始坐标 CSV、`inspection.json` 和说明。原始数据、输出结果和论文不包含在仓库中，运行前自行准备输入文件。

当前脚本针对已检查的 XINGYING 导出行为编写，要求 `mm` 单位，并检查帧号及 `POINT:FRAMES`。它标记可疑原点记录，不删帧、滤波或插值。`candidate_valid` 只是待复核筛选结果，不能作为独立测量真值。生成的中文说明仍包含 `point_test011` 样本的具体结论；换用新数据时以 JSON/CSV 实际结果为准，并人工复核说明。

Codex 云端可安装上述依赖并进行离线分析。NOKOV SDK 的 DLL、现场设备和本地网络连接需在实验室 Windows 电脑上使用；云端离线检查通过不代表相机连接成功。

## NOKOV 本地接口

详见 [安装与使用](nokov-integration/README.md)。先复制 `config.example.json` 为 `config.json` 并填写实际工程目录。默认仅预览录制命令，显式加入 `--send` 才发送。

## 文件边界

本机配置、官方 SDK 包、虚拟环境、采集工程、标定文件、日志及生成结果均通过 `.gitignore` 排除。官方 SDK 需要从 NOKOV 官方渠道单独获取。
