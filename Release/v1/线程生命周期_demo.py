import threading
import time
import signal
import sys

class WaydDaemon:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None

    def _loop(self):
        """后台工作循环"""
        while not self._stop_event.is_set():
            print("工作中...")
            # 用 wait 替代 sleep，支持被中断唤醒
            if self._stop_event.wait(5):  # 5秒间隔
                break  # 收到停止信号
        self._cleanup()

    def _cleanup(self):
        """资源清理"""
        print("清理资源...")
        # 关闭数据库连接、保存未写入数据等

    def start(self):
        """启动后台线程"""
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """发出停止信号，等待线程结束"""
        print("正在停止...")
        self._stop_event.set()          # 1. 触发停止
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5) # 2. 等待最多5秒
        print("已停止")

# 信号处理
daemon = WaydDaemon()
daemon.start()

def handle_exit(signum, frame):
    daemon.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)   # Ctrl+C
signal.signal(signal.SIGTERM, handle_exit)  # 终止信号