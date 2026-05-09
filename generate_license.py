import json
import base64
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def sign_data(data: bytes, private_key_path: str = "private_key.pem") -> str:
    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    signature = private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode()

def generate_license(
    expire_days: int = 30,
    channel: str = "default",
    model: str = "deepseek",
    bind_ip: str = "",
    bind_domain: str = "",
    extra: dict = None
):
    now = datetime.now(timezone(timedelta(hours=8)))  # 北京时间
    payload = {
        "product": "SmartTool",
        "issue_time": now.isoformat(),
        "expire_time": (now + timedelta(days=expire_days)).isoformat(),
        "channel": channel,
        "model": model,
        "bind_ip": bind_ip,
        "bind_domain": bind_domain,
    }
    if extra:
        payload.update(extra)

    json_str = json.dumps(payload, ensure_ascii=False)
    signature = sign_data(json_str.encode())

    license_data = {
        "payload": payload,
        "signature": signature
    }
    with open("license.dat", "w", encoding="utf-8") as f:
        json.dump(license_data, f, ensure_ascii=False, indent=2)
    print("✅ license.dat 已生成")

if __name__ == "__main__":
    # 示例：30天有效期，渠道pro，指定启动通义千问
    generate_license(expire_days=30, channel="pro", model="chatgpt")
