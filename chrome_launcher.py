import os
import subprocess
import time
import requests

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
]

def find_chrome_path():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return "chrome"

def launch_chrome_debug(url: str, user_data_dir: str = r"C:\temp\chrome_debug", port: int = 9222):
    """
    确保 Chrome 以远程调试模式运行并打开指定 URL
    :param url:           要打开的网页地址
    :param user_data_dir: Chrome 用户数据目录
    :param port:          调试端口
    """
    try:
        resp = requests.get(f'http://localhost:{port}/json', timeout=2)
        if resp.status_code == 200:
            print("✅ Chrome 调试端口已存在")
            return
    except:
        pass

    print(f"🔄 启动 Chrome 并打开 {url} ...")
    chrome_path = find_chrome_path()
    try:
        subprocess.Popen([
            chrome_path,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={user_data_dir}",
            url
        ])
        time.sleep(4)
        try:
            resp = requests.get(f'http://localhost:{port}/json', timeout=2)
            if resp.status_code == 200:
                print("✅ Chrome 已启动")
                return
        except:
            pass
    except Exception as e:
        print(f"⚠️ 启动失败: {e}")
    print("请手动打开 Chrome 并访问对应页面")
