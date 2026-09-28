# Bonsai Launcher — Ternary-Bonsai-2-27B-gguf 一键部署工具 (Windows)

一个现代化界面的单文件 Windows 应用，在本机一键运行本地 GGUF 大模型，
内置对话助手，并暴露 OpenAI 兼容 API 给本机其他应用调用。
为 `Ternary-Bonsai-2-27B-PTQ1_0.gguf`（三值量化）深度优化，同时兼容任意标准 GGUF 模型
（MiniCPM、Qwen、Gemma 等系列直接导入即用；思考力度控制在不支持的模型上自动降级）。

**应用不下载、不内置任何模型文件** —— 在「模型管理」页点「导入模型文件」选中你的
`.gguf` 文件即可用，路径会自动记住，下次打开直接启动。

## 界面

- **对话助手**：本地聊天（流式输出）、GPU/显存/推理速度实时面板、右侧快速参数滑杆
- **模型管理**：硬件识别、运行时下载（镜像加速）、模型导入、服务启停、运行日志
- **参数调节**：采样参数（温度/TopP/TopK/MinP/重复惩罚/存在惩罚）、上下文与 KV 缓存、
  batch/ubatch、CPU 线程、并行槽位（多应用并发调用）
- **系统设置**：端口、监听地址（127.0.0.1 仅本机 / 0.0.0.0 局域网）、关闭视觉能力
  （`--no-mmproj` 省显存）、Flash Attention、mlock、系统信息

## 功能要点

- **自动识别硬件**：NVIDIA（CUDA 12.4/13.3 按驱动自动选择）、AMD（Vulkan / HIP）、Intel（Vulkan）、纯 CPU，
  并下载对应的 llama.cpp 运行时（[PrismML fork](https://github.com/PrismML-Eng/llama.cpp)，
  PQ2_0 / PTQ1_0 三值量化内核只在它里面，上游 llama.cpp 跑不了这两个量化）
- **运行时版本管理**：下载后记录版本号，启动自动比对最新版；已是最新直接跳过不重复下载，
  旧版本自动升级并清理残留文件
- **系统依赖检测**：一键检测 WebView2 / VC++ 运行库 / Vulkan / NVIDIA 驱动，
  迁移到新电脑时先看这里，缺失项可跳转官方下载页
- **跨显卡状态监控**：GPU 使用率 / 显存占用 NVIDIA 走 nvidia-smi，AMD / Intel 走 Windows
  WDDM 性能计数器，三种显卡都能实时显示；推理速度直接读 llama-server `/metrics` 官方吞吐量
- **运行时下载全部走镜像加速**：先探测 GitHub 是否可直连，可用直连优先、不可用镜像优先
  （`ghfast.top` / `gh-proxy.com` / `ghproxy.net` 等），另一侧始终兜底；支持断点续传
- **API 暴露给本机应用**：启动后 `http://127.0.0.1:8080/v1` 即为 OpenAI 兼容接口
  （`/v1/chat/completions`、`/v1/completions`、`/v1/models`、`/v1/embeddings`）

## 安装与使用

1. 运行 `BonsaiLauncher-Setup.exe`（安装包，免管理员，装到用户目录），
   或直接用绿色版 `dist/BonsaiLauncher.exe`
2. 打开应用 →「模型管理」→ 点「下载 / 更新运行时」（仅首次需要联网，自动匹配显卡）
3. 点「导入模型文件」→ 选中 U 盘里的 `Ternary-Bonsai-2-27B-PTQ1_0.gguf`
4. 点「启动服务」→ 回「对话助手」直接聊天，或其他应用调用 API

> 界面基于 Edge WebView2 渲染：Windows 11 和绝大多数 Windows 10 已内置；
> 个别精简系统若无，会引导安装 WebView2 Runtime（也可手动到微软官网下载）。

## 本机其他应用调用示例

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="none")
r = client.chat.completions.create(
    model="bonsai", messages=[{"role": "user", "content": "你好"}])
print(r.choices[0].message.content)
```

## 目录结构（exe 同级）

```
BonsaiLauncher.exe
runtime/   llama.cpp 运行时（自动下载解压）
config.json  界面参数与模型路径自动保存
```

## 自行打包

运行 `build.bat`：安装依赖（清华镜像）→ PyInstaller 打包 → Inno Setup 生成安装包。
