#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OpenClaw 代理 GUI 启动器
双击运行即可通过图形界面控制服务的启动与停止，实时显示日志。
"""

import sys
import threading
import queue
import logging
from tkinter import Tk, Frame, Button, Text, Scrollbar, END, VERTICAL, RIGHT, Y, LEFT, BOTH, DISABLED, NORMAL
from tkinter import messagebox

# 导入我们的服务器控制函数
import server
from server import start_proxy_server, stop_proxy_server, logger as svc_logger

# ---------- 日志重定向 ----------
class QueueHandler(logging.Handler):
    """将日志记录发送到 queue 中，供 GUI 轮询显示"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(record)

class ServerManagerGUI:
    def __init__(self):
        self.root = Tk()
        self.root.title("OpenClaw Proxy Manager v1.0")
        self.root.geometry("900x550")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 日志队列
        self.log_queue = queue.Queue()
        # 配置队列处理器
        self._setup_logging()

        # 构建界面
        self._build_ui()

        # 定时轮询日志队列
        self.root.after(100, self._poll_log_queue)

    def _setup_logging(self):
        """在 root logger 上添加队列处理器，保留原有的控制台和文件输出"""
        # 获取我们使用的 logger
        handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        handler.setLevel(logging.DEBUG)

        # 添加到 root logger，这样所有模块的日志都会被捕获
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        # 同时确保 deepseek-proxy 的日志级别足够低
        svc_logger.setLevel(logging.DEBUG)

    def _build_ui(self):
        # 顶部按钮栏
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10, padx=10, fill="x")

        self.start_btn = Button(btn_frame, text="启动服务", width=15, command=self.start_server)
        self.start_btn.pack(side=LEFT, padx=5)

        self.stop_btn = Button(btn_frame, text="停止服务", width=15, command=self.stop_server, state=DISABLED)
        self.stop_btn.pack(side=LEFT, padx=5)

        self.status_label = Button(btn_frame, text="● 未运行", bd=0, relief="flat", foreground="gray", font=("Arial", 10, "bold"))
        self.status_label.pack(side=LEFT, padx=20)

        # 日志显示区域
        log_frame = Frame(self.root)
        log_frame.pack(pady=5, padx=10, fill=BOTH, expand=True)

        self.log_text = Text(log_frame, wrap="none", state=DISABLED)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)

        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        # 底部清空日志按钮
        clear_btn = Button(self.root, text="清空日志", command=self.clear_log)
        clear_btn.pack(pady=5)

    def start_server(self):
        """在后台线程启动服务器"""
        if hasattr(self, '_server_running') and self._server_running:
            messagebox.showinfo("提示", "服务器已在运行")
            return

        # 禁用启动按钮，防止重复点击
        self.start_btn.config(state=DISABLED)
        self.status_label.config(text="● 启动中...", foreground="orange")

        def run():
            try:
                start_proxy_server(host='0.0.0.0', port=9999)
                self._server_running = True
                # 通过队列在 GUI 线程更新界面
                self.root.after(0, self._on_server_started)
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, self._on_start_failed, err_msg)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _on_server_started(self):
        """服务器成功启动后的 GUI 更新"""
        self.stop_btn.config(state=NORMAL)
        self.start_btn.config(state=DISABLED)
        self.status_label.config(text="● 运行中", foreground="green")

    def _on_start_failed(self, error):
        """启动失败时的 GUI 更新"""
        self.start_btn.config(state=NORMAL)
        self.status_label.config(text="● 启动失败", foreground="red")
        messagebox.showerror("启动失败", error)

    def stop_server(self):
        """停止服务器"""
        if not hasattr(self, '_server_running') or not self._server_running:
            return

        self.stop_btn.config(state=DISABLED)
        self.status_label.config(text="● 停止中...", foreground="orange")

        def run():
            try:
                stop_proxy_server()
                self._server_running = False
                self.root.after(0, self._on_server_stopped)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("停止异常", str(e)))
                self.root.after(0, self._on_server_stopped)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _on_server_stopped(self):
        self.start_btn.config(state=NORMAL)
        self.stop_btn.config(state=DISABLED)
        self.status_label.config(text="● 已停止", foreground="gray")

    def clear_log(self):
        self.log_text.config(state=NORMAL)
        self.log_text.delete('1.0', END)
        self.log_text.config(state=DISABLED)

    def _poll_log_queue(self):
        """定期从队列取出日志并显示到文本框"""
        while True:
            try:
                record = self.log_queue.get_nowait()
            except queue.Empty:
                break
            else:
                msg = self._format_record(record)
                self.log_text.config(state=NORMAL)
                self.log_text.insert(END, msg + "\n")
                self.log_text.see(END)
                self.log_text.config(state=DISABLED)
        self.root.after(100, self._poll_log_queue)

    def _format_record(self, record):
        # 只需使用 formatter 格式化
        handler = logging.getLogger().handlers[0] if logging.getLogger().handlers else None
        if handler and handler.formatter:
            return handler.formatter.format(record)
        return f"{record.asctime} [{record.levelname}] {record.getMessage()}"

    def _on_close(self):
        """关闭窗口时停止服务器"""
        if hasattr(self, '_server_running') and self._server_running:
            if messagebox.askyesno("退出确认", "服务器仍在运行，确定要退出并停止服务吗？"):
                self.stop_server()
                self.root.after(500, self.root.destroy)  # 等待停止线程结束
        else:
            self.root.destroy()

    def run(self):
        # 禁用 Windows 控制台快速编辑（如果是在控制台环境下运行，避免误触暂停进程）
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
                mode = ctypes.c_uint32()
                kernel32.GetConsoleMode(handle, ctypes.byref(mode))
                new_mode = mode.value & ~(0x0040 | 0x0020)
                kernel32.SetConsoleMode(handle, new_mode)
            except:
                pass
        self.root.mainloop()


if __name__ == '__main__':
    gui = ServerManagerGUI()
    gui.run()
