# 方式一：使用 win10toast
from win10toast import ToastNotifier

toaster = ToastNotifier()
toaster.show_toast(
    "⏰ 在干嘛？",
    "该记录当前活动了！",
    duration=10,         # 显示时长（秒）
    threaded=True,       # 异步，不阻塞
)

# 方式二：使用 plyer（跨平台）
# from plyer import notification

# notification.notify(
#     title="⏰ 在干嘛？",
#     message="该记录当前活动了！",
#     timeout=10,           # 自动关闭时间
# )