import json
import time
import uuid
import re
import threading
import logging
import os
import sys
import secrets
from http.server import HTTPServer, BaseHTTPRequestHandler
from logging import Handler

from cdp_client import DeepSeekCDP, QwenCDP, BaseCDP
from model_config import get_model_config
from lic_verifier import verify_license
from chrome_launcher import launch_chrome_debug
from prompt import (
    estimate_tokens, parse_tools, extract_user_text, build_context,
    NO_TOOL_MARKER
)
from function_call import (
    extract_all_function_calls, is_likely_tool_call,
    repair_malformed_tool_call, split_long_mdx
)
from session import (
    get_session, update_session_tokens, should_new_chat, reset_session,
    DEEPSEEK_MAX_TOKENS, TOKEN_THRESHOLD, check_repeated_tool_call
)

# ---------- API 密钥管理 ----------
API_KEY_FILE = "api.key"

def load_or_generate_api_key() -> str:
    env_key = os.environ.get("DEEPSEEK_PROXY_API_KEY")
    if env_key:
        print("✅ 使用环境变量 DEEPSEEK_PROXY_API_KEY 提供的密钥")
        return env_key
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, "r") as f:
            key = f.read().strip()
            if key:
                print("✅ 从 api.key 文件加载密钥")
                return key
    new_key = secrets.token_hex(16)
    with open(API_KEY_FILE, "w") as f:
        f.write(new_key + "\n")
    print(f"🔑 已生成新的API密钥: {new_key}")
    print(f"   文件已保存至: {API_KEY_FILE}")
    return new_key

API_KEY = load_or_generate_api_key()

CDP_CLASS = None
MODEL_NAME = None
ENABLE_SELF_TEST = True

class FlushFileHandler(Handler):
    def __init__(self, filename, encoding='utf-8'):
        super().__init__()
        self.stream = open(filename, 'a', encoding=encoding, buffering=1)
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.stream.write(msg + '\n')
            self.stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        try:
            self.stream.close()
        except:
            pass
        super().close()

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger('deepseek-proxy')
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

_file_handler_lock = threading.Lock()
_current_log_hour = None
_current_file_handler = None

def _get_hour_str():
    return time.strftime("%Y-%m-%d_%H")

def _create_file_handler(hour_str):
    filename = os.path.join(LOG_DIR, f"server_{hour_str}.log")
    handler = FlushFileHandler(filename)
    handler.setLevel(logging.DEBUG)
    return handler

def _update_file_handler():
    global _current_log_hour, _current_file_handler
    hour = _get_hour_str()
    with _file_handler_lock:
        if hour != _current_log_hour:
            if _current_file_handler:
                logger.removeHandler(_current_file_handler)
                _current_file_handler.close()
            _current_file_handler = _create_file_handler(hour)
            logger.addHandler(_current_file_handler)
            _current_log_hour = hour

_update_file_handler()

page_lock = threading.Lock()
last_request_hash = (None, 0.0)
_failed_requests = {}
MAX_FAIL_COUNT = 3
FAIL_RESET_INTERVAL = 30

def request_hash(req_dict):
    try:
        payload = {
            'messages': req_dict.get('messages', []),
            'session_id': req_dict.get('session_id', ''),
            'model': req_dict.get('model', '')
        }
        return str(hash(json.dumps(payload, sort_keys=True, ensure_ascii=False)))
    except:
        return str(uuid.uuid4())

def trigger_new_chat(cdp):
    js_shortcut = """
    (function() {
        const body = document.body;
        const event = new KeyboardEvent('keydown', {
            key: 'j', keyCode: 74, code: 'KeyJ',
            ctrlKey: true, bubbles: true, cancelable: true
        });
        body.dispatchEvent(event);
        document.dispatchEvent(event);
        return 'shortcut_sent';
    })()
    """
    res = cdp.evaluate(js_shortcut)
    logger.debug(f"快捷键 Ctrl+J 结果: {res}")
    time.sleep(2)
    if res != 'shortcut_sent':
        logger.info("快捷键未生效，尝试按钮点击…")
        result = cdp.new_chat()
        logger.debug(f"按钮点击结果: {result}")
        return result
    return 'shortcut_sent'

def _check_and_update_failed_requests(current_hash):
    now = time.time()
    count, first_time = _failed_requests.get(current_hash, (0, now))
    if now - first_time > FAIL_RESET_INTERVAL:
        _failed_requests[current_hash] = (1, now)
        return False, 1
    return count >= MAX_FAIL_COUNT, count

def _record_failed_request(current_hash):
    now = time.time()
    count, first_time = _failed_requests.get(current_hash, (0, now))
    _failed_requests[current_hash] = (count + 1, first_time)

def ask_ai_to_fix_tool_call(malformed_text, model="deepseek-web"):
    prompt = f"""你是工具调用格式修正专家... 原始文本：{malformed_text}"""
    try:
        cdp = CDP_CLASS()
        ws_url = cdp.get_debug_url()
        if not ws_url:
            return None
        cdp.connect(ws_url)
        cdp.wait_until_idle(timeout=5)
        reply, _ = cdp.send_and_get_reply(prompt, wait=True)
        cdp.close()
        if reply and len(reply) > 10:
            return extract_all_function_calls(reply) or None
    except Exception as e:
        logger.warning(f"AI 修复工具调用失败: {e}")
    return None


class OpenAIHandler(BaseHTTPRequestHandler):
    def _send_stream_event(self, data):
        try:
            event_str = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            self.wfile.write(event_str.encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as e:
            logger.error(f"流发送失败 (连接中断): {e}")
            raise

    def _send_done(self):
        try:
            self.wfile.write("data: [DONE]\n\n".encode())
            self.wfile.flush()
        except:
            pass

    def _safe_send_done(self):
        try:
            self._send_done()
        except:
            pass

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == '/health':
            cdp = CDP_CLASS() if CDP_CLASS else BaseCDP()
            url = cdp.get_debug_url()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok" if url else "no_tab"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        _update_file_handler()
        request_id = uuid.uuid4().hex[:8]

        auth_header = self.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing or invalid Authorization header, use 'Bearer <api_key>'"}).encode())
            return
        provided_key = auth_header.split(' ')[1]
        if provided_key != API_KEY:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid API key"}).encode())
            return

        if not self.path.endswith('/chat/completions'):
            self.send_response(404)
            self.end_headers()
            return

        logger.info(f"[{request_id}] ============================================================")
        logger.info(f"[{request_id}] 新增请求")

        length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(length)
        try:
            req = json.loads(raw_body)
        except Exception as e:
            logger.error(f"[{request_id}] 请求 JSON 解析失败: {e}")
            self.send_response(400)
            self.end_headers()
            return

        logger.info(f"[{request_id}] 模型: {req.get('model')}, 消息数: {len(req.get('messages', []))}")
        try:
            body_preview = json.dumps(req, ensure_ascii=False)
            logger.debug(f"[{request_id}] 请求体完整: {body_preview}")
        except:
            pass

        messages = req.get('messages', [])
        for msg in messages:
            if msg.get('role') == 'tool':
                tool_id = msg.get('tool_call_id', '')
                content = msg.get('content', '')
                logger.info(f"[{request_id}] 工具返回 (id={tool_id}): {content[:500]}...")

        global last_request_hash
        current_hash = request_hash(req)
        prev_hash, prev_time = last_request_hash
        if prev_hash == current_hash and (time.time() - prev_time) < 5.0:
            logger.warning(f"[{request_id}] ⚠️  疑似重复请求")
        last_request_hash = (current_hash, time.time())

        should_reject, fail_count = _check_and_update_failed_requests(current_hash)
        if should_reject:
            logger.error(f"[{request_id}] 🚫 请求已连续失败 {fail_count} 次，拒绝处理")
            self.send_response(429)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            try:
                self._send_stream_event({
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": req.get('model', 'deepseek-web'),
                    "choices": [{"index": 0, "delta": {"content": "请求处理失败，已自动停止重试。请稍后再试。"}, "finish_reason": "stop"}]
                })
                self._send_done()
            except:
                pass
            return

        requested_model = req.get('model', 'deepseek-web')
        tools = req.get('tools', [])
        session_id = req.get('session_id', str(uuid.uuid4()))

        if not messages:
            self.send_response(400)
            self.end_headers()
            return

        user_text = extract_user_text(messages)
        if not user_text:
            self.send_response(400)
            self.end_headers()
            return
        logger.info(f"[{request_id}] 用户输入: {user_text[:300]}...")

        if re.search(r"(切换新会话|新对话|new\s*chat)", user_text, re.IGNORECASE):
            logger.info(f"[{request_id}] 用户指令：开启新会话")
            with page_lock:
                cdp = CDP_CLASS()
                try:
                    ws_url = cdp.get_debug_url()
                    if not ws_url:
                        self._send_confirm(requested_model, "无法连接模型页面。")
                        return
                    cdp.connect(ws_url)
                    result = trigger_new_chat(cdp)
                    if result in ('shortcut_sent', 'CLICKED', 'TEXT_CLICK'):
                        reset_session(session_id)
                        confirm_msg = "已开启新对话。"
                    else:
                        confirm_msg = "开启新对话失败，可尝试手动按 Ctrl+J。"
                except Exception as e:
                    logger.exception(f"[{request_id}] 新对话异常")
                    confirm_msg = "开启新对话时发生错误。"
                finally:
                    cdp.close()
            self._send_confirm(requested_model, confirm_msg)
            return

        acquired = page_lock.acquire(timeout=10)
        if not acquired:
            logger.warning(f"[{request_id}] 服务器忙碌，拒绝请求")
            self.send_response(503)
            self.end_headers()
            self.wfile.write(json.dumps({"error":"Server busy"}).encode())
            return

        cdp = None
        stream_broken = False
        force_plain_text = False
        force_text = ""
        try:
            history_context = build_context(messages, user_text)
            tools_desc = parse_tools(tools)
            full_prompt = tools_desc + "\n\n"
            if history_context:
                full_prompt += "对话记录：\n" + history_context + "\n"
            full_prompt += f"用户: {user_text}"

            if len(full_prompt.encode('utf-8')) > 500 * 1024:
                logger.warning(f"[{request_id}] Prompt 过大，裁剪历史")
                lines = history_context.split("\n")[-10:]
                full_prompt = tools_desc + "\n\n对话记录（裁剪后）：\n" + "\n".join(lines) + "\n用户: " + user_text

            logger.debug(f"[{request_id}] 完整 prompt 长度: {len(full_prompt)}")

            cdp = CDP_CLASS()
            ws_url = cdp.get_debug_url()
            if not ws_url:
                logger.error(f"[{request_id}] 无可用调试连接")
                _record_failed_request(current_hash)
                self.send_response(503)
                self.end_headers()
                return
            cdp.connect(ws_url)

            logger.debug(f"[{request_id}] 等待页面空闲...")
            cdp.wait_until_idle(timeout=15)

            if should_new_chat(session_id):
                logger.info(f"[{request_id}] 🔄 令牌接近上限，自动开启新对话")
                trigger_new_chat(cdp)
                reset_session(session_id)

            reply = None
            for attempt in range(2):
                try:
                    result = cdp.send_and_get_reply(full_prompt, wait=True)
                    if result:
                        reply, _ = result
                        if reply and len(reply) > 10:
                            break
                except Exception as e:
                    logger.warning(f"[{request_id}] 第{attempt+1}次发送失败: {e}")
                    if attempt < 1:
                        time.sleep(0.5)

            if not reply or len(reply) <= 10:
                logger.error(f"[{request_id}] 未获取到有效 AI 回复")
                _record_failed_request(current_hash)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                try:
                    self._send_stream_event({
                        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": requested_model,
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": "抱歉，模型暂时没有响应，请稍后重试。"}, "finish_reason": "stop"}]
                    })
                    self._send_done()
                except:
                    pass
                return

            logger.info(f"[{request_id}] LLM 完整回复长度: {len(reply)}")
            logger.debug(f"[{request_id}] LLM 完整回复:\n{reply}")
            prompt_tokens = estimate_tokens(full_prompt)
            completion_tokens = estimate_tokens(reply)
            delta_tokens = prompt_tokens + completion_tokens
            new_total = update_session_tokens(session_id, delta_tokens)

            sess = get_session(session_id)
            remaining = DEEPSEEK_MAX_TOKENS * TOKEN_THRESHOLD - new_total
            logger.info(f"[{request_id}] 📊 会话 {session_id[:8]} 累计 token: {new_total} / {int(DEEPSEEK_MAX_TOKENS * TOKEN_THRESHOLD)} (剩余 {max(0, remaining)} 触发切换)")

            # 纯文本标记检测
            if reply.rstrip().endswith(NO_TOOL_MARKER):
                logger.info(f"[{request_id}] 检测到纯文本回复标记，将直接返回文本内容")
                clean_text = reply[:reply.rfind(NO_TOOL_MARKER)].rstrip()
                if not clean_text:
                    clean_text = " "

                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'close')
                self.end_headers()

                for i in range(0, len(clean_text), 10):
                    chunk = clean_text[i:i+10]
                    delta = {"content": chunk}
                    if i == 0:
                        delta["role"] = "assistant"
                    try:
                        self._send_stream_event({
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": requested_model,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}]
                        })
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as e:
                        logger.error(f"[{request_id}] 发送纯文本块时连接中断: {e}")
                        stream_broken = True
                        break
                    time.sleep(0.005)
                if not stream_broken:
                    try:
                        self._send_stream_event({
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": requested_model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                        })
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as e:
                        logger.error(f"[{request_id}] 发送 stop 标记失败: {e}")
                        stream_broken = True
                if not stream_broken:
                    self._send_done()
                else:
                    logger.warning(f"[{request_id}] 由于连接中断，未发送 [DONE]")

                logger.info(f"[{request_id}] 纯文本回复发送完毕")
                return

            # 工具调用处理
            func_calls = []
            debug_lines = []
            def debug_callback(msg):
                debug_lines.append(msg)
                logger.debug(f"[{request_id}] [FunctionCall] {msg}")

            if is_likely_tool_call(reply):
                logger.debug(f"[{request_id}] 宽泛匹配到潜在工具调用")
                func_calls = extract_all_function_calls(reply, debug_callback=debug_callback)
                if not func_calls:
                    repaired = repair_malformed_tool_call(reply, debug_callback=debug_callback)
                    if repaired:
                        func_calls = extract_all_function_calls(repaired, debug_callback=debug_callback)
                    if not func_calls:
                        logger.info(f"[{request_id}] 尝试使用 AI 二次修正工具调用格式")
                        ai_fixed_calls = ask_ai_to_fix_tool_call(reply, model=requested_model)
                        if ai_fixed_calls:
                            func_calls = ai_fixed_calls

            if func_calls:
                func_calls = split_long_mdx(func_calls, max_len=8000)
                logger.info(f"[{request_id}] 拆分后共有 {len(func_calls)} 个工具调用")
                for idx, fc in enumerate(func_calls):
                    fc_str = json.dumps(fc, ensure_ascii=False)
                    logger.info(f"[{request_id}] 工具调用[{idx}]: {fc_str}")
            else:
                logger.info(f"[{request_id}] 无工具调用")

            # ★ 重复工具调用拦截
            if func_calls and check_repeated_tool_call(session_id, func_calls):
                logger.warning(f"[{request_id}] 🔁 检测到重复工具调用，转为纯文本回复，避免循环")
                force_plain_text = True
                force_text = "该操作正在处理中，请稍后再查询。\n" + NO_TOOL_MARKER
                func_calls = []

            for fc in func_calls:
                if fc.get("name") == "exec" and "arguments" in fc:
                    args = fc["arguments"]
                    if isinstance(args, dict):
                        args.setdefault("workdir", "/root")
                    elif isinstance(args, str):
                        try:
                            arg_obj = json.loads(args)
                            arg_obj.setdefault("workdir", "/root")
                            fc["arguments"] = arg_obj
                        except:
                            fc["arguments"] = {"command": args, "workdir": "/root"}

            # 流式响应
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()

            if func_calls:
                tool_calls_list = []
                for idx, fc in enumerate(func_calls):
                    tool_name = fc["name"]
                    args_str = json.dumps(fc["arguments"], ensure_ascii=False) if isinstance(fc["arguments"], dict) else str(fc["arguments"])
                    call_id = f"call_{uuid.uuid4().hex[:8]}"
                    tool_calls_list.append({
                        "index": idx,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": ""}
                    })
                    fc["_args_str"] = args_str
                    fc["_call_id"] = call_id

                logger.info(f"[{request_id}] 转发给 OpenClaw 的 tool_calls 数: {len(tool_calls_list)}")
                for tc in tool_calls_list:
                    logger.debug(f"[{request_id}] tool_call: index={tc['index']}, id={tc['id']}, name={tc['function']['name']}")
                logger.debug(f"[{request_id}] 工具调用参数详情:")
                for fc in func_calls:
                    logger.debug(f"[{request_id}]   name={fc['name']}, arguments={fc['_args_str']}")

                try:
                    self._send_stream_event({
                        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": requested_model,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": tool_calls_list
                            },
                            "finish_reason": None
                        }]
                    })
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as e:
                    logger.error(f"[{request_id}] 连接中断，无法发送工具调用结构: {e}")
                    stream_broken = True

                if not stream_broken:
                    for fc in func_calls:
                        if stream_broken:
                            break
                        args_str = fc["_args_str"]
                        call_id = fc["_call_id"]
                        idx = next(i for i, tc in enumerate(tool_calls_list) if tc["id"] == call_id)
                        for i in range(0, len(args_str), 4):
                            try:
                                self._send_stream_event({
                                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": requested_model,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {
                                            "tool_calls": [{
                                                "index": idx,
                                                "function": {"arguments": args_str[i:i+4]}
                                            }]
                                        },
                                        "finish_reason": None
                                    }]
                                })
                            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as e:
                                logger.error(f"[{request_id}] 发送参数块时连接中断: {e}")
                                stream_broken = True
                                break
                            time.sleep(0.005)

                if not stream_broken:
                    try:
                        self._send_stream_event({
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": requested_model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
                        })
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as e:
                        logger.error(f"[{request_id}] 发送 tool_calls 完成标记失败: {e}")
                        stream_broken = True
            else:
                plain_text = force_text if force_plain_text else reply
                for i in range(0, len(plain_text), 10):
                    chunk = plain_text[i:i+10]
                    delta = {"content": chunk}
                    if i == 0:
                        delta["role"] = "assistant"
                    try:
                        self._send_stream_event({
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": requested_model,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}]
                        })
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as e:
                        logger.error(f"[{request_id}] 发送纯文本块时连接中断: {e}")
                        stream_broken = True
                        break
                    time.sleep(0.005)
                if not stream_broken:
                    try:
                        self._send_stream_event({
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": requested_model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                        })
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as e:
                        logger.error(f"[{request_id}] 发送 stop 标记失败: {e}")
                        stream_broken = True

            if not stream_broken:
                self._send_done()
            else:
                logger.warning(f"[{request_id}] 由于连接中断，未发送 [DONE]")

            logger.info(f"[{request_id}] 流式发送完毕 (连接状态: {'正常' if not stream_broken else '中断'})")
            _failed_requests.pop(current_hash, None)

        except Exception as e:
            logger.exception(f"[{request_id}] 请求处理异常")
            _record_failed_request(current_hash)
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self._send_stream_event({
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": requested_model,
                    "choices": [{"index": 0, "delta": {"content": "处理请求时发生内部错误，请稍后重试。"}, "finish_reason": "stop"}]
                })
                self._safe_send_done()
            except:
                pass
        finally:
            if cdp:
                cdp.close()
            page_lock.release()
            logger.info(f"[{request_id}] ============================================================\n")

    def _send_confirm(self, model, msg):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        for i in range(0, len(msg), 10):
            chunk = msg[i:i+10]
            delta = {"role": "assistant", "content": chunk} if i == 0 else {"content": chunk}
            try:
                self._send_stream_event({
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}]
                })
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                break
        try:
            self._send_stream_event({
                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            })
        except:
            pass
        self._safe_send_done()
        self.wfile.flush()


def run_self_test():
    if not ENABLE_SELF_TEST:
        return
    logger.info("=" * 60)
    logger.info("🔍 开始 Function Call 解析自检...")
    test_file = os.path.join(os.path.dirname(__file__), "test_cases.txt")
    if not os.path.exists(test_file):
        logger.warning(f"自检文件 {test_file} 不存在，跳过自检")
        return

    total = 0
    passed = 0
    failed = 0
    current_case = None
    current_lines = []

    from function_call import extract_all_function_calls

    with open(test_file, 'r', encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.strip()
            case_match = re.match(r'^#\s*(\d+)[\.\s]', line)
            if case_match:
                if current_case is not None and current_lines:
                    total += 1
                    case_text = '\n'.join(current_lines)
                    debug_lines = []
                    def debug_callback(msg):
                        debug_lines.append(f"  {msg}")
                    results = extract_all_function_calls(case_text, debug_callback=debug_callback)
                    if results:
                        logger.info(f"  ✅ 用例 {current_case}: 成功提取 {len(results)} 个调用 → {[r['name'] for r in results]}")
                        for d in debug_lines:
                            logger.debug(d)
                        passed += 1
                    else:
                        logger.warning(f"  ❌ 用例 {current_case}: 提取失败 ← 内容预览: {case_text[:80]}...")
                        for d in debug_lines:
                            logger.warning(d)
                        failed += 1
                current_case = int(case_match.group(1))
                current_lines = []
                continue

            if not line or line.startswith('#'):
                continue

            current_lines.append(line)

        if current_case is not None and current_lines:
            total += 1
            case_text = '\n'.join(current_lines)
            debug_lines = []
            def debug_callback(msg):
                debug_lines.append(f"  {msg}")
            results = extract_all_function_calls(case_text, debug_callback=debug_callback)
            if results:
                logger.info(f"  ✅ 用例 {current_case}: 成功提取 {len(results)} 个调用 → {[r['name'] for r in results]}")
                passed += 1
            else:
                logger.warning(f"  ❌ 用例 {current_case}: 提取失败 ← 内容预览: {case_text[:80]}...")
                failed += 1

    logger.info(f"自检完成: 共 {total} 条用例，通过 {passed}，失败 {failed}")
    if failed > 0:
        logger.warning("⚠️  存在失败用例，请检查 function_call 逻辑或补充 test_cases.txt")
    logger.info("=" * 60)


def init_system():
    """执行许可证验证、模型配置加载、启动 Chrome 调试窗口"""
    global CDP_CLASS, MODEL_NAME
    print("=" * 60)
    print("🔐 验证许可证...")
    valid, info = verify_license()
    if not valid:
        print(f"\n❌ 许可证验证失败: {info}")
        raise RuntimeError(f"许可证无效: {info}")

    MODEL_NAME = info.get("model", "deepseek")
    channel = info.get("channel", "unknown")
    print(f"\n📦 渠道: {channel}，指定模型: {MODEL_NAME}")

    cfg = get_model_config(MODEL_NAME)
    CDP_CLASS = cfg["cdp_class"]
    url = cfg["url"]

    launch_chrome_debug(url)
    print("=" * 60)


# ---------- GUI 接口 ----------
_server_instance = None
_server_thread = None
_stop_event = threading.Event()

def start_proxy_server(host='0.0.0.0', port=9999):
    """启动 HTTP 代理服务（非阻塞，在后台线程运行）"""
    global _server_instance, _server_thread, _stop_event
    if _server_instance:
        raise RuntimeError("服务器已在运行")

    # 初始化许可证和浏览器
    init_system()
    run_self_test()

    _stop_event.clear()
    _server_instance = HTTPServer((host, port), OpenAIHandler)
    logger.info(f"🚀 DeepSeek Web 代理启动在 http://{host}:{port}/chat/completions")

    _server_thread = threading.Thread(target=_server_instance.serve_forever)
    _server_thread.daemon = True
    _server_thread.start()
    logger.info("服务线程已启动")

def stop_proxy_server():
    """停止代理服务"""
    global _server_instance, _server_thread, _stop_event
    if not _server_instance:
        logger.warning("服务器未运行")
        return
    _stop_event.set()
    _server_instance.shutdown()
    _server_thread.join(timeout=3)
    _server_instance.server_close()
    _server_instance = None
    _server_thread = None
    logger.info("服务已安全停止")


# 保留命令行直接启动的能力（不带 GUI）
if __name__ == '__main__':
    logger.info("🚀 DeepSeek Web 代理 (多模型/许可验证)")
    logger.info("端点: http://localhost:9999/chat/completions")
    logger.info(f"🔑 API密钥: {API_KEY}  (存放于 {API_KEY_FILE})")
    start_proxy_server()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_proxy_server()
        logger.info("服务已停止")
