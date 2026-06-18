"""国内游戏每日新游排查系统 — 桌面启动器.

双击 EXE 或 python launcher.py 启动:
  - FastAPI 后端 (127.0.0.1:8001)
  - 自动打开浏览器访问前端页面

EXE 打包 (PyInstaller): 工作目录 = sys.executable 所在目录 (非 _MEIPASS)
"""

from __future__ import annotations

import ctypes
import os
import signal
import sys
import time
import threading
import webbrowser
from pathlib import Path

import uvicorn


def _get_app_dir() -> Path:
    """获取应用工作目录.

    - 开发模式: launcher.py 所在目录
    - EXE 模式: EXE 所在目录 (数据持久化在这里，非临时 _MEIPASS)
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parent


def _force_exit():
    """收到关闭信号时立即退出."""
    try:
        print("\n[v1.1] 收到关闭信号，正在退出...")
    except Exception:
        pass
    os._exit(0)


def _setup_exit_handler():
    """注册控制台关闭事件 + Unix 信号处理."""
    if sys.platform == "win32":
        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        def _handler(ctrl_type):
            if ctrl_type == 2:  # CTRL_CLOSE_EVENT
                _force_exit()
                return True
            if ctrl_type in (0, 1):  # CTRL_C_EVENT, CTRL_BREAK_EVENT
                _force_exit()
                return True
            return False
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True)
    else:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: _force_exit())


def _fix_stdio():
    """修复 PyInstaller --noconsole 模式下 sys.stdout/stderr 为 None 的问题.

    uvicorn 的 DefaultFormatter 依赖 sys.stdout.isatty(),
    在无控制台 EXE 中 sys.stdout 为 None 会导致 ValueError.
    """
    if sys.stdout is None:
        log_dir = _get_app_dir() / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "exe_output.log"
        sys.stdout = open(str(log_file), "a", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
        print("stdio redirected to log file (--noconsole mode)")


def main():
    print("=" * 50)
    print(" 国内游戏每日新游排查系统 v1.1")
    print(" 数据源: 好游快爆 + TapTap")
    print("=" * 50)
    print()

    # 切换工作目录
    app_dir = _get_app_dir()
    os.chdir(str(app_dir))
    print(f"工作目录: {app_dir}")

    # 确保 data/ logs/ 目录存在
    (app_dir / "data").mkdir(exist_ok=True)
    (app_dir / "logs").mkdir(exist_ok=True)

    host = "127.0.0.1"
    port = 8001

    # v1.1: 端口冲突检测 — 自动杀掉占用端口的旧进程
    import socket as _socket
    _sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    _in_use = _sock.connect_ex((host, port)) == 0
    _sock.close()
    if _in_use:
        print(f"[启动] 端口 {port} 已被占用, 正在终止旧进程...")
        if sys.platform == "win32":
            import subprocess as _sp
            try:
                result = _sp.run(
                    f'netstat -ano | findstr :{port} | findstr LISTENING',
                    capture_output=True, text=True, shell=True,
                )
                for line in result.stdout.strip().split('\n'):
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pid = parts[-1]
                        _sp.run(f'taskkill /F /PID {pid}', capture_output=True, shell=True)
                        print(f"[启动] 已终止旧进程 PID={pid}")
            except Exception:
                pass
        time.sleep(1.5)

    # v1.1: 端口轮询 — 服务就绪后再打开浏览器
    def wait_for_port(h: str, p: int, timeout: float = 30.0) -> bool:
        time.sleep(3.0)  # 留给 uvicorn 模块导入和端口绑定
        start = time.time()
        while time.time() - start < timeout:
            try:
                sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                sock.settimeout(0.5)
                if sock.connect_ex((h, p)) == 0:
                    sock.close()
                    return True
                sock.close()
            except Exception:
                pass
            time.sleep(0.3)
        return False

    def open_browser():
        if wait_for_port(host, port):
            webbrowser.open(f"http://{host}:{port}")
            print(f"[启动] 浏览器已打开: http://{host}:{port}")
        else:
            print(f"[警告] 后端未能及时监听端口，请手动打开 http://{host}:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    # v1.1: 注册退出处理器
    _setup_exit_handler()

    # 启动 FastAPI (禁用 uvicorn 默认 log 避免 isatty 问题)
    try:
        uvicorn.run(
            "backend.main:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=2,
        )
    except KeyboardInterrupt:
        print("\n用户中断, 正在退出...")
    except Exception as e:
        print(f"\n[服务异常] {e}")
        import traceback
        traceback.print_exc()
        print("\n按 Enter 键退出...")
        input()


if __name__ == "__main__":
    _fix_stdio()
    try:
        main()
    except Exception as e:
        print(f"\n[致命错误] {e}")
        import traceback
        traceback.print_exc()
        print("\n按 Enter 键退出...")
        input()
