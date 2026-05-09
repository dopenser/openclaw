from cdp_client import DeepSeekCDP, QwenCDP, BaichuanCDP, ZhipuCDP, ErnieCDP, KimiCDP

MODEL_CONFIG = {
    "deepseek": {
        "url": "https://chat.deepseek.com",
        "cdp_class": DeepSeekCDP,
        "description": "DeepSeek Chat"
    },
    "qwen": {
        "url": "https://www.qianwen.com/",          # 更新为正确地址
        "cdp_class": QwenCDP,
        "description": "通义千问"
    },
    "baichuan": {
        "url": "https://www.baichuan-ai.com",
        "cdp_class": BaichuanCDP,
        "description": "百川大模型"
    },
    "zhipu": {
        "url": "https://chatglm.cn",
        "cdp_class": ZhipuCDP,
        "description": "智谱清言"
    },
    "ernie": {
        "url": "https://yiyan.baidu.com",
        "cdp_class": ErnieCDP,
        "description": "文心一言"
    },
    "kimi": {
        "url": "https://kimi.moonshot.cn",
        "cdp_class": KimiCDP,
        "description": "Kimi (Moonshot)"
    },
}

def get_model_config(model_name: str):
    if model_name not in MODEL_CONFIG:
        raise ValueError(f"不支持的模型: {model_name}，当前可用: {list(MODEL_CONFIG.keys())}")
    return MODEL_CONFIG[model_name]
