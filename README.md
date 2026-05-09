# OpenClaw 许可证生成与验证系统

## 项目简介

这是一个用于生成和验证许可证的 Python 工具集，支持生成许可证密钥、验证许可证有效性，并提供模型配置、提示词管理等功能。

## 主要功能

- generate_keys.py - 生成密钥对
- generate_license.py - 生成许可证文件
- lic_verifier.py - 验证许可证有效性
- model_config.py - 模型配置管理
- prompt.py - 提示词管理
- server.py - Web 服务端
- session.py - 会话管理
- cdp_client.py - Chrome DevTools Protocol 客户端
- chrome_launcher.py - Chrome 浏览器启动器
- function_call.py - 函数调用工具

## 环境要求

- Python 3.8 或更高版本
- 操作系统：Linux / macOS / Windows

## 安装步骤

### 1. 克隆仓库

bash
git clone https://github.com/dopenser/openclaw.git
cd openclaw


### 2. 安装依赖

bash
pip install -r requirements.txt


如果项目没有 requirements.txt，请根据实际需要安装以下常用依赖：

bash
pip install cryptography pycryptodome requests websocket-client


## 配置说明

### 基础配置

配置文件通常位于项目根目录或 ~/.openclaw/ 目录下。

主要配置项：

json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8080
  },
  "license": {
    "expiry_days": 365,
    "encryption_key": "your-encryption-key"
  },
  "model": {
    "default_model": "gpt-4",
    "api_key": "your-api-key"
  }
}


### 模型配置

使用 OpenClaw 命令管理模型：

bash
# 查看已配置的模型
openclaw models list

# 添加模型认证
openclaw models auth add

# 设置当前模型
openclaw models set


## 启动方式

### 启动 Web 服务

bash
python server.py


服务默认运行在 http://localhost:8080

### 自定义端口

bash
python server.py --port 9000


### 后台运行

bash
nohup python server.py > server.log 2>&1 &


## 使用示例

### 1. 生成密钥对

bash
python generate_keys.py


输出示例：

Private key: private.pem
Public key: public.pem


### 2. 生成许可证

bash
python generate_license.py --user admin --expiry 365


### 3. 验证许可证

bash
python lic_verifier.py --license license.lic


## 配置 OpenClaw 服务

### 查看配置

bash
openclaw config get <key>


### 设置配置

bash
openclaw config set <key> <value>


示例：
bash
openclaw config set server.port 9090


### 重启服务

bash
openclaw restart


## 常见问题

### Q: 启动时提示端口被占用
A: 修改配置文件中的端口号，或使用 --port 参数指定其他端口

### Q: 许可证验证失败
A: 检查公钥是否正确，确认许可证文件是否已过期

### Q: 如何更新许可证
A: 重新运行 generate_license.py 生成新许可证替换旧文件

## 目录结构


openclaw/
├── generate_keys.py      # 密钥生成
├── generate_license.py   # 许可证生成
├── lic_verifier.py       # 许可证验证
├── model_config.py       # 模型配置
├── prompt.py             # 提示词
├── server.py             # 主服务
├── session.py            # 会话管理
├── cdp_client.py         # CDP 客户端
├── chrome_launcher.py    # Chrome 启动器
├── function_call.py      # 函数调用
└── README_zh.md          # 中文说明


## 日志查看

bash
# 查看运行日志
tail -f server.log

# 查看 OpenClaw 日志
journalctl -u openclaw -f


## 安全建议

1. 不要将私钥文件（private.pem）提交到版本控制系统
2. 定期更换加密密钥
3. 使用环境变量存储敏感信息（如 API Key）
4. 生产环境建议使用反向代理（如 Nginx）增加安全层

## 技术支持

如有问题，请提交 Issue 到 GitHub 仓库：
https://github.com/dopenser/openclaw/issues

## 更新日志

- 2026-05-09: 初始版本，包含基础许可证生成和验证功能
