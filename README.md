# DeepSeek License Generator

许可证生成与验证工具集，用于 DeepSeek 代理的授权管理。支持 RSA 密钥对生成、许可证文件签发、在线验证及 Chrome CDP 自动化集成。

## 功能模块

- 密钥生成：generate_keys.py 生成 RSA 公私钥对 (PEM 格式)
- 许可证生成：generate_license.py 使用私钥签发许可证 (JSON 格式)
- 许可证验证：lic_verifier.py 使用公钥验证许可证有效性
- 模型配置：model_config.py 管理 AI 模型参数与端点
- CDP 自动化：cdp_client.py、chrome_launcher.py 控制 Chrome 浏览器
- 交互界面：gui.py (SmartTool_GUI.exe) 提供图形化操作

## 快速开始

### 1. 环境要求

- Python 3.8+
- 已安装 Chrome/Chromium 浏览器
- 依赖库：pip install cryptography requests websocket-client

### 2. 生成密钥对

bash
python generate_keys.py


输出：
- private_key.pem — 私钥，用于签发许可证
- public_key.pem — 公钥，用于验证许可证

### 3. 签发许可证

bash
python generate_license.py


根据提示输入用户 ID、有效期（天数），程序会生成 license.lic 文件（JSON 格式，包含签名）。

### 4. 验证许可证

bash
python lic_verifier.py


读取 license.lic 和 public_key.pem，输出验证结果（有效/无效）。

### 5. 启动服务器（带许可证校验）

bash
python server.py


服务器启动时会自动验证许可证，验证通过后才开放以下能力：
- CDP 浏览器控制 (/cdp)
- 函数调用 (/call)
- 会话管理 (/session)

### 6. 图形界面（Windows）

双击 SmartTool_GUI.exe 或在终端执行：
bash
python gui.py


## 集成到其他项目

python
from lic_verifier import LicenseVerifier

verifier = LicenseVerifier(public_key_path="public_key.pem")
if verifier.verify_license_file("license.lic"):
    print("License is valid, starting service...")
else:
    print("Invalid license")
    exit(1)


## CDP 自动化使用示例

python
from cdp_client import CDPClient
from function_call import FunctionCall

client = CDPClient()
client.connect("localhost", 9222)
fc = FunctionCall(client)
title = fc.call("document.title")
print(title)


## 配置文件

- model_config.py — 模型端点、超时、重试等参数
- api.key — 可选的外部 API 密钥
- prompt.py — 系统提示词模板

## 故障排除

- License invalid: 重新运行 generate_license.py，确保公钥与私钥匹配
- Chrome 无法连接: 先启动 Chrome with remote-debugging: chrome --remote-debugging-port=9222
- 导入错误: 确认已安装 cryptography 模块

## 安全建议

- 私钥 (private_key.pem) 必须离线保存，切勿提交到代码仓库
- 许可证文件建议绑定硬件特征或用户账号
- 生产环境中应使用 HTTPS 保护 API 通信

## 文件清单

| 文件 | 说明 |
|------|------|
| generate_keys.py | 生成 RSA 密钥对 |
| generate_license.py | 生成许可证文件 |
| lic_verifier.py | 许可证验证器 |
| server.py | 主服务器 (带许可证校验) |
| cdp_client.py | CDP 客户端 |
| chrome_launcher.py | 启动 Chrome 调试实例 |
| function_call.py | 在浏览器中执行 JS |
| session.py | 会话管理 |
| model_config.py | 模型与网络配置 |
| prompt.py | 提示词模板 |
| gui.py | Tkinter 图形界面 |
| test_cases.txt | 测试用例 |

## 许可证

本工具仅供授权用户使用。未经许可不得分发或商用。
