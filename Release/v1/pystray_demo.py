import pystray
from PIL import Image
import tkinter as tk

# 创建隐藏主窗口
root = tk.Tk()
root.withdraw()

def on_quit(icon, item):
    """退出托盘"""
    icon.stop()
    root.quit()

def show_window(icon, item):
    """显示主窗口"""
    root.deiconify()

# 创建图标（64x64 纯色图标，也可加载 png 文件）
icon_image = Image.new("RGB", (64, 64), (0, 120, 215))

# 创建右键菜单
menu = pystray.Menu(
    pystray.MenuItem("显示窗口", show_window),
    pystray.MenuItem("退出", on_quit),
)

# 创建托盘图标
icon = pystray.Icon("wayd", icon_image, "在干嘛 - WAYD", menu)

# 在独立线程中运行托盘
import threading
t = threading.Thread(target=icon.run, daemon=True)
t.start()

# 进入主消息循环
root.mainloop()