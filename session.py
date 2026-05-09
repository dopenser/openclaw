DEEPSEEK_MAX_TOKENS = 128000
TOKEN_THRESHOLD = 0.9

sessions = {}

def get_session(session_id):
    return sessions.setdefault(session_id, {'token_count': 0})

def update_session_tokens(session_id, delta):
    sess = get_session(session_id)
    sess['token_count'] += delta
    return sess['token_count']

def should_new_chat(session_id):
    sess = get_session(session_id)
    return sess['token_count'] > DEEPSEEK_MAX_TOKENS * TOKEN_THRESHOLD

def reset_session(session_id):
    sessions.pop(session_id, None)
