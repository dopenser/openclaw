import json
import time

DEEPSEEK_MAX_TOKENS = 128000
TOKEN_THRESHOLD = 0.9

sessions = {}

def get_session(session_id):
    sess = sessions.setdefault(session_id, {
        'token_count': 0,
        'last_tool_calls_signature': None,
        'last_tool_call_time': 0
    })
    return sess

def update_session_tokens(session_id, delta):
    sess = get_session(session_id)
    sess['token_count'] += delta
    return sess['token_count']

def should_new_chat(session_id):
    sess = get_session(session_id)
    return sess['token_count'] > DEEPSEEK_MAX_TOKENS * TOKEN_THRESHOLD

def reset_session(session_id):
    sessions.pop(session_id, None)

def check_repeated_tool_call(session_id, tool_calls, repeat_interval=10):
    """
    如果 tool_calls 与上一次完全相同，且距离上次调用不超过 repeat_interval 秒，
    则返回 True，否则更新记录并返回 False。
    用于防止连续重复执行同一个工具调用（例如 cron list 无返回时无限循环）。
    """
    sess = get_session(session_id)
    # 将工具调用列表序列化为稳定字符串用于比较
    sig = json.dumps(tool_calls, sort_keys=True, ensure_ascii=False) if tool_calls else None
    now = time.time()
    if sess.get('last_tool_calls_signature') == sig and (now - sess.get('last_tool_call_time', 0)) < repeat_interval:
        return True
    sess['last_tool_calls_signature'] = sig
    sess['last_tool_call_time'] = now
    return False
