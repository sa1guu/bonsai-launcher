# -*- coding: utf-8 -*-
"""
Bonsai Launcher — Ternary-Bonsai-2-27B-gguf 一键部署工具 (Windows)

WebView 界面 (pywebview + Edge WebView2) + Python 后端:
  - 自动识别 NVIDIA / AMD / Intel 显卡或纯 CPU, 镜像加速下载匹配的 llama.cpp
    运行时 (PrismML fork, 含 PQ2_0 / PTQ1_0 三值量化内核)
  - 不下载/不内置任何模型: 导入本地 .gguf 即可
  - 对话助手 / 参数滑杆 / 端口设置 / 关闭视觉 / OpenAI 兼容 API 暴露给本机应用
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser

import requests
import webview

APP_NAME = "Bonsai Launcher"
RUNTIME_REPO = "PrismML-Eng/llama.cpp"
DEFAULT_MODEL_NAME = "Ternary-Bonsai-2-27B-PTQ1_0.gguf"

# GitHub 加速镜像 (前缀式代理); 下载前先探测 github.com 是否直连可用:
# 可用则直连优先, 不可用则镜像优先, 另一侧始终兜底
GH_PROXIES = [
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
    "https://gh.llkk.cc/",
]

_GH_DIRECT = None


def gh_reachable():
    """探测 github.com 是否可直连 (结果缓存)."""
    global _GH_DIRECT
    if _GH_DIRECT is None:
        try:
            requests.head("https://github.com", timeout=6, allow_redirects=True)
            _GH_DIRECT = True
        except Exception:
            _GH_DIRECT = False
    return _GH_DIRECT


def gh_prefixes():
    """直连可用 -> [直连, 镜像...]; 不可用 -> [镜像..., 直连]."""
    if gh_reachable():
        return [""] + GH_PROXIES
    return GH_PROXIES + [""]

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

DEFAULT_CONFIG = {
    "backend": "auto",
    "model_path": "",
    "port": "8080", "host": "127.0.0.1",
    "ctx": "8192", "ngl": "99", "threads": "",
    "batch": "2048", "ubatch": "512", "parallel": "1",
    "cache_k": "f16", "cache_v": "f16",
    "flash": True, "mlock": False, "novision": True,
    "temp": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.05,
    "repeat": 1.0, "presence": 0.0,
    "think": "default",
}


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = app_dir()
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
VERSION_PATH = os.path.join(RUNTIME_DIR, "version.json")
os.makedirs(RUNTIME_DIR, exist_ok=True)


def read_runtime_version():
    """运行时版本信息 {tag, backend, time}; 未安装/旧版无记录返回 None."""
    try:
        with open(VERSION_PATH, "r", encoding="utf-8") as f:
            v = json.load(f)
        if v.get("tag") and find_server_exe():
            return v
    except Exception:
        pass
    return None


def write_runtime_version(tag, backend):
    try:
        with open(VERSION_PATH, "w", encoding="utf-8") as f:
            json.dump({"tag": tag, "backend": backend,
                       "time": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    except Exception:
        pass


# ---------------------------------------------------------------- 核心逻辑

def gh_proxied(url, proxy):
    return proxy + url if proxy else url


def http_get_json(url, timeout=30):
    last = None
    for p in gh_prefixes():
        try:
            r = requests.get(gh_proxied(url, p), timeout=timeout)
            if r.ok:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise last or RuntimeError("所有镜像均失败")


def latest_release_tag():
    try:
        d = http_get_json(f"https://api.github.com/repos/{RUNTIME_REPO}/releases/latest")
        if d.get("tag_name"):
            return d["tag_name"], [a["name"] for a in d.get("assets", [])]
    except Exception:
        pass
    last = None
    for p in gh_prefixes():
        try:
            r = requests.get(
                gh_proxied(f"https://github.com/{RUNTIME_REPO}/releases/latest", p),
                allow_redirects=False, timeout=30)
            m = re.search(r"/releases/tag/([^/?#]+)", r.headers.get("Location", ""))
            if m:
                return m.group(1), None
            last = RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise last or RuntimeError("无法获取最新版本号")


def detect_hardware():
    names = []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW).stdout
        names = [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        pass
    low = " | ".join(names).lower()
    vendor = "cpu"
    if "nvidia" in low or "geforce" in low or "quadro" in low or "rtx" in low or "gtx" in low:
        vendor = "nvidia"
    elif "amd" in low or "radeon" in low:
        vendor = "amd"
    elif "intel" in low or "arc" in low or "iris" in low or "uhd" in low:
        vendor = "intel"

    cuda_ver = None
    if vendor == "nvidia":
        try:
            out = subprocess.run(["nvidia-smi"], capture_output=True, text=True,
                                 timeout=15, creationflags=CREATE_NO_WINDOW).stdout
            m = re.search(r"CUDA Version:\s*([\d.]+)", out)
            if m:
                cuda_ver = "13.3" if int(m.group(1).split(".")[0]) >= 13 else "12.4"
        except Exception:
            pass
        if cuda_ver is None:
            cuda_ver = "12.4"
    return {"vendor": vendor, "names": names, "cuda": cuda_ver}


def backend_asset_names(tag, backend, cuda_ver):
    if backend == "cuda":
        cv = cuda_ver or "12.4"
        return [f"llama-{tag}-bin-win-cuda-{cv}-x64.zip",
                f"cudart-llama-bin-win-cuda-{cv}-x64.zip"]
    if backend == "vulkan":
        return [f"llama-{tag}-bin-win-vulkan-x64.zip"]
    if backend == "hip":
        return [f"llama-{tag}-bin-win-hip-radeon-x64.zip"]
    return [f"llama-{tag}-bin-win-cpu-x64.zip"]


def find_server_exe():
    for root, _dirs, files in os.walk(RUNTIME_DIR):
        for f in files:
            if f.lower() == "llama-server.exe":
                return os.path.join(root, f)
    return None


def download_file(url, dest, progress_cb, log_cb, use_gh_proxy=False, cancel_ev=None):
    part = dest + ".part"
    urls = [gh_proxied(url, p) for p in gh_prefixes()] if use_gh_proxy else [url]
    last = None
    for u in urls:
        try:
            pos = os.path.getsize(part) if os.path.exists(part) else 0
            headers = {"Range": f"bytes={pos}-"} if pos else {}
            with requests.get(u, stream=True, headers=headers, timeout=(15, 60),
                              allow_redirects=True) as r:
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code}")
                if r.status_code == 200 and pos:
                    pos = 0
                mode = "ab" if pos else "wb"
                total = pos + int(r.headers.get("Content-Length") or 0)
                done, tmark, dmark = pos, time.time(), pos
                with open(part, mode) as f:
                    for chunk in r.iter_content(chunk_size=1024 * 512):
                        if cancel_ev and cancel_ev.is_set():
                            raise InterruptedError("已取消")
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if now - tmark >= 0.4:
                            progress_cb(done, total, (done - dmark) / (now - tmark))
                            tmark, dmark = now, done
            if total and os.path.getsize(part) < total:
                raise RuntimeError("下载不完整")
            os.replace(part, dest)
            progress_cb(os.path.getsize(dest), os.path.getsize(dest), 0)
            return
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            log_cb(f"镜像失败 ({u.split('/')[2]}): {e}")
    raise last or RuntimeError("所有镜像均下载失败")


def ram_info():
    class MEMSTAT(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        s = MEMSTAT()
        s.dwLength = ctypes.sizeof(s)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return {"total": s.ullTotalPhys, "avail": s.ullAvailPhys}
    except Exception:
        return {"total": 0, "avail": 0}


def gpu_stats_nvidia():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
            creationflags=CREATE_NO_WINDOW).stdout.strip()
        line = out.splitlines()[0]
        util, used, total = [int(x.strip()) for x in line.split(",")[:3]]
        return {"ok": True, "util": util, "vram_used": used, "vram_total": total}
    except Exception:
        return None


_GPU_TOTAL_CACHE = {"mb": 0}


def _ps(script, timeout=15):
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
        creationflags=CREATE_NO_WINDOW).stdout.strip()


def vram_total_mb():
    """注册表读取显存总量 (AMD/Intel/NVIDIA 通用), 缓存结果."""
    if _GPU_TOTAL_CACHE["mb"]:
        return _GPU_TOTAL_CACHE["mb"]
    try:
        out = _ps("(Get-ItemProperty 'HKLM:\\SYSTEM\\ControlSet001\\Control\\Class"
                  "\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -Name"
                  " 'HardwareInformation.qwMemorySize' -ErrorAction SilentlyContinue"
                  " | Measure-Object -Property 'HardwareInformation.qwMemorySize'"
                  " -Maximum).Maximum / 1MB")
        mb = int(float(out.splitlines()[-1]))
        if mb > 0:
            _GPU_TOTAL_CACHE["mb"] = mb
    except Exception:
        pass
    return _GPU_TOTAL_CACHE["mb"]


def gpu_stats_wddm():
    """Windows GPU 性能计数器 (AMD/Intel 可用, 无需装驱动工具)."""
    try:
        out = _ps(
            "$u=(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage'"
            " -ErrorAction Stop).CounterSamples | Measure-Object CookedValue -Sum;"
            "$m=(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage'"
            " -ErrorAction Stop).CounterSamples | Measure-Object CookedValue -Sum;"
            "\"$([math]::Min([math]::Round($u.Sum),100));$([math]::Round($m.Sum/1MB))\"")
        util_s, used_s = out.splitlines()[-1].split(";")
        total = vram_total_mb()
        return {"ok": True, "util": int(util_s), "vram_used": int(used_s),
                "vram_total": total or int(used_s)}
    except Exception:
        return None


def gpu_stats():
    """优先 NVIDIA, 失败回退 WDDM 计数器; 都失败返回空."""
    g = gpu_stats_nvidia() or gpu_stats_wddm()
    return g or {"ok": False, "util": 0, "vram_used": 0, "vram_total": 0}


# ---------------------------------------------------------------- JS 桥接

class Api:
    def __init__(self):
        self._window = None
        self.cfg = dict(DEFAULT_CONFIG)
        self._load_config()
        self.hw = {"vendor": "unknown", "names": [], "cuda": None}
        self.server_proc = None
        self.server_ready = False
        self.cancel_dl = threading.Event()
        self.last_tps = 0.0
        self._chat_abort = None
        self._gpu_cache = {"ok": False, "util": 0, "vram_used": 0, "vram_total": 0}
        threading.Thread(target=self._gpu_sampler, daemon=True).start()

    def _gpu_sampler(self):
        while True:
            try:
                self._gpu_cache = gpu_stats()
            except Exception:
                pass
            time.sleep(2)

    # ------------- 事件推送
    def push(self, event, data):
        if self._window:
            try:
                self._window.evaluate_js(
                    "window.dispatchEvent(new CustomEvent(%s, {detail: %s}))"
                    % (json.dumps(event), json.dumps(data, ensure_ascii=False)))
            except Exception:
                pass

    def log(self, msg):
        self.push("log", {"msg": str(msg), "t": time.strftime("%H:%M:%S")})

    # ------------- 配置
    def _load_config(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self.cfg.update(json.load(f))
        except Exception:
            pass

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_config(self):
        return self.cfg

    def save_config(self, cfg):
        cfg = dict(cfg)
        if not cfg.get("model_path"):
            cfg.pop("model_path", None)  # model_path 只能由 pick_model 修改, 防止前端旧值覆盖
        self.cfg.update(cfg)
        self._save_config()
        return True

    # ------------- 状态
    def get_state(self):
        exe = find_server_exe()
        mp = self.cfg.get("model_path", "")
        return {
            "hw": self.hw,
            "runtime": {"installed": bool(exe), "path": exe or "",
                        "version": (read_runtime_version() or {}).get("tag", ""),
                        "backend": (read_runtime_version() or {}).get("backend", "")},
            "model": {"path": mp, "exists": bool(mp and os.path.exists(mp)),
                      "size": os.path.getsize(mp) if mp and os.path.exists(mp) else 0,
                      "name": os.path.basename(mp) if mp else ""},
            "server": {"running": bool(self.server_proc and self.server_proc.poll() is None),
                       "ready": self.server_ready,
                       "url": "http://%s:%s/v1" % (self.cfg["host"], self.cfg["port"])},
            "config": self.cfg,
            "default_model_name": DEFAULT_MODEL_NAME,
        }

    def refresh_hw(self):
        def work():
            self.hw = detect_hardware()
            self.push("hw", self.hw)
        threading.Thread(target=work, daemon=True).start()
        return True

    def server_tps(self):
        """从 llama-server /metrics 的累计计数算平均 tok/s, 兼容任何客户端."""
        running = bool(self.server_proc and self.server_proc.poll() is None)
        if running:
            try:
                txt = requests.get(
                    "http://%s:%s/metrics" % (self.cfg["host"], self.cfg["port"]),
                    timeout=2).text
                def metric(name):
                    m = re.search(r"^llamacpp:%s ([\d.]+)" % name, txt, re.M)
                    return float(m.group(1)) if m else 0.0
                gauge = metric("predicted_tokens_seconds")
                if gauge > 0:
                    self.last_tps = round(gauge, 1)
                else:
                    sec = metric("tokens_predicted_seconds_total")
                    if sec > 0:
                        self.last_tps = round(metric("tokens_predicted_total") / sec, 1)
            except Exception:
                pass
        return self.last_tps, running

    def poll_stats(self):
        tps, running = self.server_tps()
        return {
            "gpu": self._gpu_cache,
            "ram": ram_info(),
            "tps": tps,
            "running": running,
            "ready": self.server_ready,
        }

    # ------------- 运行时
    def resolve_backend(self, choice):
        if choice == "auto":
            return {"nvidia": "cuda", "amd": "vulkan", "intel": "vulkan"}.get(
                self.hw.get("vendor"), "cpu")
        return choice

    def runtime_status(self):
        """已装版本 vs 最新版本; 联网部分异步, 结果经 rt_status 事件推送."""
        cur = read_runtime_version()

        def work():
            try:
                tag, _ = latest_release_tag()
                self.push("rt_status", {
                    "ok": True, "latest": tag,
                    "current": (cur or {}).get("tag", ""),
                    "backend": (cur or {}).get("backend", ""),
                    "up_to_date": bool(cur and cur.get("tag") == tag)})
            except Exception as e:  # noqa: BLE001
                self.push("rt_status", {"ok": False, "err": str(e),
                                        "current": (cur or {}).get("tag", "")})
        threading.Thread(target=work, daemon=True).start()
        return True

    def check_deps(self):
        """检测系统级依赖: WebView2 / VC++ 运行库 / Vulkan / N卡驱动."""
        import winreg
        deps = []

        def reg_val(root, path, name):
            try:
                with winreg.OpenKey(root, path) as k:
                    return winreg.QueryValueEx(k, name)[0]
            except Exception:
                return None

        wv = (reg_val(winreg.HKEY_LOCAL_MACHINE,
                      r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
                      r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "pv")
              or reg_val(winreg.HKEY_CURRENT_USER,
                         r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
                         r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "pv"))
        deps.append({"name": "WebView2 运行时", "ok": bool(wv and wv != "0.0.0.0"),
                     "version": wv or "", "desc": "应用界面显示所必需",
                     "url": "https://developer.microsoft.com/microsoft-edge/webview2/"})

        vc = (reg_val(winreg.HKEY_LOCAL_MACHINE,
                      r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64", "Version")
              or reg_val(winreg.HKEY_LOCAL_MACHINE,
                         r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0"
                         r"\VC\Runtimes\x64", "Version"))
        deps.append({"name": "VC++ 2015-2022 运行库 (x64)", "ok": bool(vc),
                     "version": (vc or "").lstrip("v"),
                     "desc": "llama-server.exe 运行所必需",
                     "url": "https://aka.ms/vs/17/release/vc_redist.x64.exe"})

        vk = os.path.exists(r"C:\Windows\System32\vulkan-1.dll")
        deps.append({"name": "Vulkan 运行时", "ok": vk, "version": "",
                     "desc": "AMD / Intel 显卡推理所需 (N卡 CUDA 模式不需要)",
                     "url": "https://vulkan.lunarg.com/sdk/home"})

        nv_ok, nv_ver = False, ""
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
                creationflags=CREATE_NO_WINDOW).stdout.strip()
            if out and out.splitlines()[0].strip():
                nv_ok, nv_ver = True, out.splitlines()[0].strip()
        except Exception:
            pass
        deps.append({"name": "NVIDIA 驱动", "ok": nv_ok, "version": nv_ver,
                     "desc": "N 卡 CUDA 推理所需 (A卡/核显可忽略)",
                     "url": "https://www.nvidia.cn/drivers/lookup/"})
        return deps

    def download_runtime(self, backend_choice):
        if getattr(self, "_dl_running", False):
            return {"ok": False, "err": "已有下载任务进行中"}
        backend = self.resolve_backend(backend_choice)
        self.cancel_dl.clear()
        self._dl_running = True

        def prog(done, total, speed):
            self.push("dl_progress", {
                "pct": (done / total * 100) if total else 0,
                "done": done, "total": total, "speed": speed})

        def work():
            try:
                self.log("GitHub 直连可用, 直连优先" if gh_reachable()
                         else "GitHub 不可直连, 使用镜像加速")
                self.log(f"获取 {RUNTIME_REPO} 最新版本...")
                tag, assets = latest_release_tag()
                self.log(f"最新版本: {tag} | 后端: {backend}")
                cur = read_runtime_version()
                if cur and cur.get("tag") == tag and cur.get("backend") == backend:
                    self.log(f"本地已是最新版本 ({tag}, {backend}), 无需下载")
                    self.push("runtime_done", {"ok": True, "skipped": True})
                    return
                if cur:
                    self.log(f"检测到旧版本 {cur.get('tag')} ({cur.get('backend')}), 执行升级")
                need = backend_asset_names(tag, backend, self.hw.get("cuda"))
                if assets:
                    need = [n for n in need if n in assets] or need
                import zipfile
                for name in need:
                    url = f"https://github.com/{RUNTIME_REPO}/releases/download/{tag}/{name}"
                    dest = os.path.join(RUNTIME_DIR, name)
                    if not os.path.exists(dest):
                        self.log(f"下载 {name} ...")
                        download_file(url, dest, prog, self.log,
                                      use_gh_proxy=True, cancel_ev=self.cancel_dl)
                    else:
                        self.log(f"已存在, 跳过: {name}")
                    self.log(f"解压 {name} ...")
                    with zipfile.ZipFile(dest) as z:
                        z.extractall(RUNTIME_DIR)
                for f in os.listdir(RUNTIME_DIR):
                    if (f.startswith(("llama-", "cudart-")) and f.endswith(".zip")
                            and f not in need):
                        try:
                            os.remove(os.path.join(RUNTIME_DIR, f))
                            self.log(f"清理旧版本包: {f}")
                        except Exception:
                            pass
                write_runtime_version(tag, backend)
                self.log(f"运行时安装完成 ({tag}, {backend})")
                self.push("runtime_done", {"ok": True})
            except InterruptedError:
                self.log("下载已取消")
                self.push("runtime_done", {"ok": False, "err": "已取消"})
            except Exception as e:  # noqa: BLE001
                self.log(f"运行时下载失败: {e}")
                self.push("runtime_done", {"ok": False, "err": str(e)})
            finally:
                self._dl_running = False
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    # ------------- 模型导入
    def pick_model(self):
        res = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("GGUF 模型 (*.gguf)", "所有文件 (*.*)"))
        if res:
            self.cfg["model_path"] = res[0]
            self._save_config()
            return self.get_state()["model"]
        return None

    # ------------- 服务控制
    def _build_args(self):
        exe = find_server_exe()
        if not exe:
            raise RuntimeError("未找到 llama-server.exe, 请先在「模型管理」下载运行时")
        model = self.cfg.get("model_path", "")
        if not model or not os.path.exists(model):
            raise RuntimeError("请先导入模型文件 (.gguf)")
        c = self.cfg
        args = [exe, "-m", model,
                "--host", str(c["host"]), "--port", str(c["port"]),
                "-c", str(c["ctx"]), "-ngl", str(c["ngl"]),
                "-b", str(c["batch"]), "-ub", str(c["ubatch"]),
                "-np", str(c["parallel"])]
        if str(c.get("threads", "")).strip():
            args += ["-t", str(c["threads"]).strip()]
        args += ["--flash-attn", "on" if c.get("flash") else "off", "--metrics"]
        if c.get("mlock"):
            args += ["--mlock"]
        if c.get("novision"):
            args += ["--no-mmproj"]
        if c.get("cache_k") != "f16":
            args += ["--cache-type-k", c["cache_k"]]
        if c.get("cache_v") != "f16":
            args += ["--cache-type-v", c["cache_v"]]
        for flag, key in [("--temp", "temp"), ("--top-p", "top_p"), ("--top-k", "top_k"),
                          ("--min-p", "min_p"), ("--repeat-penalty", "repeat"),
                          ("--presence-penalty", "presence")]:
            v = str(c.get(key, "")).strip()
            if v:
                args += [flag, v]
        return args

    def start_server(self, cfg=None):
        if cfg:
            cfg = dict(cfg)
            if not cfg.get("model_path"):
                cfg.pop("model_path", None)  # 同上: 不允许启动请求清空已导入的模型路径
            self.cfg.update(cfg)
            self._save_config()
        if self.server_proc and self.server_proc.poll() is None:
            return {"ok": False, "err": "服务已在运行"}
        try:
            args = self._build_args()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": str(e)}
        self.log("启动: " + " ".join(os.path.basename(args[0]) if i == 0 else a
                                     for i, a in enumerate(args)))
        try:
            self.server_proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                cwd=os.path.dirname(args[0]), creationflags=CREATE_NO_WINDOW)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": f"启动失败: {e}"}
        self.server_ready = False
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._wait_ready, daemon=True).start()
        self.push("server", {"running": True, "ready": False})
        return {"ok": True}

    def _read_stdout(self):
        p = self.server_proc
        try:
            for line in p.stdout:
                self.log(line.rstrip())
        except Exception:
            pass
        code = p.wait()
        self.log(f"服务进程退出, 代码 {code}")
        self.server_ready = False
        self.push("server", {"running": False, "ready": False})

    def _wait_ready(self):
        host, port = self.cfg["host"], self.cfg["port"]
        url = "http://%s:%s/health" % ("127.0.0.1" if host in ("0.0.0.0", "") else host, port)
        for _ in range(180):
            if not self.server_proc or self.server_proc.poll() is not None:
                return
            try:
                r = requests.get(url, timeout=2)
                if r.status_code in (200, 503):
                    self.server_ready = True
                    self.log(f"服务已就绪: http://{host}:{port}/v1")
                    self.push("server", {"running": True, "ready": True})
                    return
            except Exception:
                pass
            time.sleep(1)

    def stop_server(self):
        p = self.server_proc
        if p and p.poll() is None:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            except Exception:
                p.terminate()
        self.server_ready = False
        self.push("server", {"running": False, "ready": False})
        return {"ok": True}

    # ------------- 对话
    def chat(self, messages, params=None):
        """流式转发到本地 llama-server, delta 通过 chat_delta 事件推送."""
        if not self.server_ready:
            return {"ok": False, "err": "服务未就绪, 请先在「模型管理」启动服务"}
        c = self.cfg
        url = "http://127.0.0.1:%s/v1/chat/completions" % c["port"]
        body = {
            "model": "bonsai",
            "messages": messages,
            "stream": True,
            "temperature": float(c.get("temp", 1.0)),
            "top_p": float(c.get("top_p", 0.95)),
            "top_k": int(c.get("top_k", 20)),
            "min_p": float(c.get("min_p", 0.05)),
            "repeat_penalty": float(c.get("repeat", 1.0)),
            "presence_penalty": float(c.get("presence", 0.0)),
        }
        think = str(c.get("think", "default"))
        if think == "off":
            body["chat_template_kwargs"] = {"enable_thinking": False}
        elif think == "low":
            body["reasoning_effort"] = "low"
        if params:
            body.update(params)

        def work():
            t0 = time.time()
            ntok = 0
            try:
                r = requests.post(url, json=body, stream=True, timeout=(10, 600))
                if (r.status_code == 500
                        and ("chat_template_kwargs" in body or "reasoning_effort" in body)
                        and ("template" in r.text.lower() or "think" in r.text.lower()
                             or "reasoning" in r.text.lower())):
                    # 部分模型的 chat template 不认识思考控制参数, 去掉后自动重试一次
                    r.close()
                    self.log("当前模型不支持思考力度参数, 已自动按标准模式重试")
                    body2 = {k: v for k, v in body.items()
                             if k not in ("chat_template_kwargs", "reasoning_effort")}
                    r = requests.post(url, json=body2, stream=True, timeout=(10, 600))
                self._chat_abort = r
                if r.status_code != 200:
                    self.push("chat_done", {"ok": False,
                                            "err": f"HTTP {r.status_code}: {r.text[:300]}"})
                    return
                r.encoding = "utf-8"
                for line in r.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        j = json.loads(data)
                        delta = j["choices"][0].get("delta", {})
                        piece = delta.get("reasoning_content") or delta.get("content") or ""
                        if piece:
                            ntok += 1
                            self.push("chat_delta", {"text": piece})
                    except Exception:
                        continue
                dt = max(time.time() - t0, 0.01)
                if ntok:
                    self.last_tps = round(ntok / dt, 1)
                self.push("chat_done", {"ok": True, "tps": self.last_tps})
            except Exception as e:  # noqa: BLE001
                if "Connection" in type(e).__name__ or "aborted" in str(e).lower():
                    self.push("chat_done", {"ok": True, "stopped": True})
                else:
                    self.push("chat_done", {"ok": False, "err": str(e)})
            finally:
                self._chat_abort = None
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def chat_stop(self):
        r = self._chat_abort
        if r:
            try:
                r.close()
            except Exception:
                pass
        return True

    # ------------- 其他
    def open_webui(self):
        webbrowser.open("http://%s:%s" % (self.cfg["host"], self.cfg["port"]))
        return True

    def sys_info(self):
        import platform
        return {
            "os": f"{platform.system()} {platform.release()}",
            "gpu": ", ".join(self.hw.get("names") or ["未检测到"]),
            "cuda": self.hw.get("cuda") or "—",
            "ram": ram_info(),
        }


def main():
    api = Api()
    index = os.path.join(resource_dir(), "web", "index.html")
    win = webview.create_window(
        "Bonsai Launcher — Ternary-Bonsai-2-27B",
        index, js_api=api,
        width=1440, height=900, min_size=(1150, 720),
        text_select=True)
    api._window = win

    def on_closed():
        api._save_config()
        if api.server_proc and api.server_proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(api.server_proc.pid)],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
    win.events.closed += on_closed
    win.events.loaded += lambda: api.refresh_hw()
    webview.start(debug=False)


if __name__ == "__main__":
    main()
