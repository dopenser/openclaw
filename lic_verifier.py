import json
import base64
import socket
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature
import ntplib

# ========== 硬编码公钥（请将你生成的 public_key.pem 内容粘贴到这里） ==========
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA25rnGtqy/0crc+ZNIfec
KqPobYwrIB7DfMuNlvNziiRMLgzzP+f0fs7UJb0HFu+4+I6f/RlH1LrbI9TYmLU5
sUIAO6x5TGO/SrkVExBRMSduYUG4maOKIQcnotpann6byPapX74hrVlTDqjkQGs7
U6ASnKXHCACVeh7STMt0ueSLb8F0F81Do9hHDVfL7ay3E+PTRL6kShT1ojF1ifl3
6S1evqDFpPkvNgn8TTBGNb06Z7S8wb3+HeATDQ6tQhsm51G/TSOCxzNh2NTjUdmG
4wpnK7ZR7VSujvkqSHNJX6z4FaMN2SN7eMD2u8u/Q7Dl4Hrtwt0MUMHZgMvRBkHv
twIDAQAB
-----END PUBLIC KEY-----
"""

# 硬编码的 NTP 服务器 IP（绕过 DNS 篡改）
NTP_SERVERS_IP = [
    "203.107.6.88",      # 阿里云NTP
    "120.25.115.20",     # 腾讯云NTP
    "194.58.204.174"     # pool.ntp.org 任一IP
]

def get_public_key():
    """从硬编码字符串加载公钥"""
    return serialization.load_pem_public_key(PUBLIC_KEY_PEM)

def get_beijing_time():
    """通过 IP 直连 NTP 获取北京时间（UTC+8），失败则抛出异常"""
    client = ntplib.NTPClient()
    times = []
    for ip in NTP_SERVERS_IP:
        try:
            response = client.request(ip, version=3, timeout=3)
            utc = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
            beijing = utc.astimezone(timezone(timedelta(hours=8)))
            times.append(beijing)
        except Exception:
            continue
    if not times:
        raise RuntimeError("❌ 所有 NTP 服务器均无法连接，请检查网络")
    # 取中位数时间，避免单一服务器偏差
    times.sort()
    return times[len(times) // 2]

def verify_license(license_file="license.dat"):
    """
    验证许可证文件，返回 (是否有效, payload 或 错误信息)
    """
    # 1. 加载许可证文件
    try:
        with open(license_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False, "许可证文件缺失或格式错误"

    payload = data.get("payload")
    signature_b64 = data.get("signature")
    if not payload or not signature_b64:
        return False, "许可证结构不完整"

    # 2. RSA 签名验证
    public_key = get_public_key()
    try:
        signature = base64.b64decode(signature_b64)
        public_key.verify(
            signature,
            json.dumps(payload, ensure_ascii=False).encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
    except InvalidSignature:
        return False, "签名无效，许可证可能被篡改"
    except Exception as e:
        return False, f"验签异常: {e}"

    # 3. IP / 域名绑定检查（可选）
    bind_ip = payload.get("bind_ip")
    if bind_ip:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
            if local_ip != bind_ip:
                return False, f"IP 绑定失败 (本机:{local_ip} 要求:{bind_ip})"
        except Exception:
            return False, "IP 绑定检查失败"
    bind_domain = payload.get("bind_domain")
    if bind_domain:
        hostname = socket.gethostname()
        if bind_domain not in hostname:
            return False, f"域名绑定失败 (主机名:{hostname})"

    # 4. 有效期检查（基于北京时间）
    try:
        now = get_beijing_time()
    except Exception as e:
        return False, f"获取网络时间失败: {e}"

    expire_str = payload.get("expire_time")
    try:
        expire_time = datetime.fromisoformat(expire_str)
    except Exception:
        return False, "到期时间格式错误"

    if now > expire_time:
        remaining = expire_time - now
        return False, f"许可证已过期 {abs(remaining.days)} 天 (到期日:{expire_time.date()})"

    # 5. 输出剩余时间
    remaining = expire_time - now
    days = remaining.days
    hours = remaining.seconds // 3600
    print(f"✅ 许可证有效 | 渠道: {payload.get('channel','未知')} | 到期: {expire_time}")
    print(f"⏳ 剩余有效期: {days} 天 {hours} 小时")
    return True, payload
