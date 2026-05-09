import re
import json
from json import JSONDecodeError
import logging

logger = logging.getLogger('deepseek-proxy')

def _strip_outer_noise(text):
    text = text.strip()
    if not text.startswith('{'):
        start = text.find('{')
        if start == -1:
            return text
        text = text[start:]
    end = text.rfind('}')
    if end != -1 and end != len(text) - 1:
        text = text[:end+1]
    return text

def _find_first_json_object(text):
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
    if depth > 0:
        return text[start:] + '}'
    return None

def _repair_by_error_position(json_str):
    max_attempts = 10
    s = json_str
    for _ in range(max_attempts):
        try:
            json.loads(s)
            return s
        except JSONDecodeError as e:
            pos = e.pos
            if pos >= len(s):
                return None
            if s[pos] == '"':
                s = s[:pos] + '\\' + s[pos:]
            elif s[pos] in (',', ':'):
                s = s[:pos] + s[pos+1:]
            else:
                s = s[:pos] + s[pos+1:]
    return None

def _fix_exec_special(json_str):
    pattern = r'"name"\s*:\s*"exec"\s*,\s*"arguments"\s*:\s*"command"\s*:\s*"([^"]+)"(?:\s*,\s*"workdir"\s*:\s*"([^"]+)")?(?:\s*,\s*"timeout"\s*:\s*(\d+))?\s*\}'
    m = re.search(pattern, json_str, re.DOTALL)
    if m:
        cmd = m.group(1).replace('"', '\\"')
        workdir = m.group(2) or "/root"
        timeout = m.group(3) or "30"
        fixed = f'{{"name":"exec","arguments":{{"command":"{cmd}","workdir":"{workdir}","timeout":{timeout}}}}}'
        return fixed
    return None

def _fix_command_by_delimiter(json_str):
    marker = '"command":"'
    idx = json_str.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    delimiters = ['","workdir"', '","timeout"', '"}']
    min_pos = len(json_str)
    for delim in delimiters:
        pos = json_str.find(delim, start)
        if pos != -1 and pos < min_pos:
            min_pos = pos
    if min_pos == len(json_str):
        return None
    raw_command = json_str[start:min_pos]
    placeholder = '\u0001'
    escaped = raw_command.replace('\\"', placeholder)
    escaped = escaped.replace('"', '\\"')
    escaped = escaped.replace(placeholder, '\"')
    escaped = escaped.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    return json_str[:start] + escaped + json_str[min_pos:]

def _fix_exec_command_quotes(json_str):
    marker = '"command":"'
    idx = json_str.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    i = start
    in_single = False
    while i < len(json_str):
        ch = json_str[i]
        if ch == "'" and not in_single:
            in_single = True
            i += 1
            continue
        elif ch == "'" and in_single:
            in_single = False
            i += 1
            continue
        if in_single:
            i += 1
            continue
        if ch == '\\':
            i += 2
            continue
        if ch == '"':
            j = i + 1
            while j < len(json_str) and json_str[j] in (' ', '\t', '\n', '\r'):
                j += 1
            if j < len(json_str) and json_str[j] in (',', '}'):
                raw_command = json_str[start:i]
                placeholder = '\u0001'
                escaped = raw_command.replace('\\"', placeholder)
                escaped = escaped.replace('"', '\\"')
                escaped = escaped.replace(placeholder, '\"')
                escaped = escaped.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                return json_str[:start] + escaped + json_str[i:]
        i += 1
    return None

def _fix_newlines_in_strings(json_str):
    result = []
    in_string = False
    escape = False
    for ch in json_str:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\':
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch in ('\n', '\r', '\t'):
            repl = {'\n': '\\n', '\r': '\\r', '\t': '\\t'}
            result.append(repl[ch])
        else:
            result.append(ch)
    return ''.join(result)

def _fix_string_inner_quotes(json_str):
    result = []
    in_string = False
    escape = False
    i = 0
    while i < len(json_str):
        ch = json_str[i]
        if escape:
            result.append(ch)
            escape = False
            i += 1
            continue
        if ch == '\\':
            result.append(ch)
            escape = True
            i += 1
            continue
        if ch == '"':
            if not in_string:
                in_string = True
                result.append(ch)
            else:
                j = i + 1
                while j < len(json_str) and json_str[j] in (' ', '\t', '\n', '\r'):
                    j += 1
                if j >= len(json_str) or json_str[j] in (',', ':', ']', '}'):
                    in_string = False
                    result.append(ch)
                else:
                    result.append('\\"')
            i += 1
            continue
        result.append(ch)
        i += 1
    if in_string:
        result.append('"')
    return ''.join(result)

def _fix_mcporter_args_quotes(json_str):
    marker = "--args '"
    idx = json_str.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    i = start
    while i < len(json_str):
        if json_str[i] == '\\':
            i += 2
            continue
        if json_str[i] == '\'':
            inner = json_str[start:i]
            escaped = json.dumps(inner)[1:-1]
            return json_str[:start] + escaped + json_str[i:]
        i += 1
    return None

def _fix_embedded_python_cmd(json_str):
    pattern = r'("command"\s*:\s*")(python3? -c )(")'
    match = re.search(pattern, json_str, re.DOTALL)
    if not match:
        return None
    prefix = match.group(1) + match.group(2) + match.group(3)
    start = match.end()
    i = start
    esc = False
    while i < len(json_str):
        ch = json_str[i]
        if esc:
            esc = False
            i += 1
            continue
        if ch == '\\':
            esc = True
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < len(json_str) and json_str[j] in (' ', '\t', '\n', '\r'):
                j += 1
            if j < len(json_str) and (json_str[j] == ',' or json_str[j] == '}'):
                inner = json_str[start:i]
                escaped = json.dumps(inner)[1:-1]
                fixed = json_str[:start] + escaped + json_str[i:]
                return fixed
        i += 1
    return None

def _repair_write_content(obj_str):
    """专门修复 write 工具调用，提取 content 并重新编码"""
    try:
        obj = json.loads(obj_str)
        if obj.get('name') == 'write' and 'arguments' in obj:
            args = obj['arguments']
            if 'content' in args and isinstance(args['content'], str):
                content = args['content']
                try:
                    json.loads(content)
                except:
                    args['content'] = json.dumps(content)[1:-1]
                return json.dumps(obj)
        return obj_str
    except Exception:
        pass

    pattern = r'"name"\s*:\s*"write"\s*,\s*"arguments"\s*:\s*{\s*"path"\s*:\s*"([^"]+)"\s*,\s*"content"\s*:\s*"(.+)"\s*}'
    match = re.search(pattern, obj_str, re.DOTALL)
    if match:
        path = match.group(1)
        raw_content = match.group(2)
        escaped_content = json.dumps(raw_content)[1:-1]
        return f'{{"name":"write","arguments":{{"path":"{path}","content":"{escaped_content}"}}}}'
    return obj_str

def _repair_exec_command(obj_str, debug=lambda x: None):
    """修复 exec 工具命令，提取 command 并正确转义"""
    try:
        outer = _find_first_json_object(obj_str)
        if not outer:
            return obj_str
        name_match = re.search(r'"name"\s*:\s*"exec"', outer)
        if not name_match:
            return obj_str
        cmd_match = re.search(r'"command"\s*:\s*"', outer)
        if not cmd_match:
            return obj_str
        cmd_start = cmd_match.end()
        i = cmd_start
        end = -1
        while i < len(outer):
            if outer[i] == '"':
                j = i + 1
                while j < len(outer) and outer[j] in ' \t\n\r':
                    j += 1
                if j < len(outer) and (outer[j] == ',' or outer[j] == '}'):
                    end = i
                    break
            i += 1
        if end == -1:
            return obj_str
        raw_cmd = outer[cmd_start:end]
        escaped_cmd = json.dumps(raw_cmd)[1:-1]
        args_body = f'"command":"{escaped_cmd}"'
        workdir_match = re.search(r'"workdir"\s*:\s*"([^"]*)"', outer)
        timeout_match = re.search(r'"timeout"\s*:\s*(\d+)', outer)
        if workdir_match:
            args_body += f',"workdir":"{workdir_match.group(1)}"'
        if timeout_match:
            args_body += f',"timeout":{timeout_match.group(1)}'
        new_outer = f'{{"name":"exec","arguments":{{{args_body}}}}}'
        debug(f"[exec修复] 新对象: {new_outer[:200]}...")
        return new_outer
    except Exception as e:
        debug(f"[exec修复] 异常: {e}")
        return obj_str

def fix_malformed_json(json_str):
    s = _strip_outer_noise(json_str)
    s = _fix_newlines_in_strings(s)

    fixed = _fix_mcporter_args_quotes(s)
    if fixed:
        s = fixed

    fixed = _fix_embedded_python_cmd(s)
    if fixed:
        s = fixed

    fixed = _fix_exec_special(s)
    if fixed:
        try:
            json.loads(fixed)
            return fixed
        except:
            pass

    fixed = _fix_exec_command_quotes(s)
    if fixed:
        try:
            json.loads(fixed)
            return fixed
        except:
            pass

    fixed = _fix_command_by_delimiter(s)
    if fixed:
        try:
            json.loads(fixed)
            return fixed
        except:
            pass

    fixed = _fix_string_inner_quotes(s)
    if fixed != s:
        try:
            json.loads(fixed)
            return fixed
        except:
            pass

    s2 = _fix_newlines_in_strings(s)
    if s2 != s:
        try:
            json.loads(s2)
            return s2
        except:
            pass

    if not s2.endswith('}'):
        s2 += '}'

    repaired = _repair_by_error_position(s2)
    if repaired:
        try:
            json.loads(repaired)
            return repaired
        except:
            pass

    return s2

def _split_json_objects_in_line(line):
    results = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] == '{':
            depth = 0
            in_string = False
            escape = False
            start = i
            while i < n:
                ch = line[i]
                if escape:
                    escape = False
                    i += 1
                    continue
                if ch == '\\':
                    escape = True
                    i += 1
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    i += 1
                    continue
                if not in_string:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            results.append(line[start:i+1])
                            i += 1
                            break
                i += 1
            else:
                i += 1
        else:
            i += 1
    return results

def _try_parse_json(s, debug=None):
    """尝试解析 JSON，失败时依次尝试各种修复，并输出修复路径"""
    # 1. 直接解析
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
            if debug:
                debug("[修复路径] 直接解析成功")
            return obj
    except Exception as e:
        if debug:
            debug(f"[修复路径] 直接解析失败: {e}")

    # 2. 通用修复 fix_malformed_json
    fixed = fix_malformed_json(s)
    try:
        obj = json.loads(fixed)
        if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
            if debug:
                debug("[修复路径] fix_malformed_json 成功")
            return obj
    except Exception as e:
        if debug:
            debug(f"[修复路径] fix_malformed_json 失败: {e}")

    # 3. write 专用修复（增强版）
    if 'write' in s:
        repaired = _repair_write_content(s)
        try:
            obj = json.loads(repaired)
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                if debug:
                    debug("[修复路径] _repair_write_content 成功")
                return obj
        except Exception as e:
            if debug:
                debug(f"[修复路径] _repair_write_content 失败: {e}")
        try:
            match = re.search(r'"name"\s*:\s*"write"\s*,\s*"arguments"\s*:\s*(\{[^}]*\})', s, re.DOTALL)
            if match:
                args_str = match.group(1)
                path_match = re.search(r'"path"\s*:\s*"([^"]*)"', args_str)
                content_match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', args_str)
                if path_match and content_match:
                    path = path_match.group(1)
                    content_raw = content_match.group(1)
                    content_escaped = json.dumps(content_raw)[1:-1]
                    new_obj = {"name": "write", "arguments": {"path": path, "content": content_escaped}}
                    if debug:
                        debug("[修复路径] write正则重建成功")
                    return new_obj
        except Exception as e:
            if debug:
                debug(f"[修复路径] write正则重建失败: {e}")

    # 4. exec command 专用修复
    if 'exec' in s and 'command' in s:
        repaired = _repair_exec_command(s, debug=debug)
        try:
            obj = json.loads(repaired)
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                if debug:
                    debug("[修复路径] _repair_exec_command 成功")
                return obj
        except Exception as e:
            if debug:
                debug(f"[修复路径] _repair_exec_command 失败: {e}")

    # 5. 终极兜底：暴力正则替换 command 或 content 内双引号
    if 'exec' in s and 'command' in s:
        try:
            new_s = re.sub(r'("command"\s*:\s*")(.*?)(")', lambda m: m.group(1) + m.group(2).replace('"', '\\"') + m.group(3), s, flags=re.DOTALL)
            obj = json.loads(new_s)
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                if debug:
                    debug("[修复路径] 暴力正则修复成功")
                return obj
        except Exception as e:
            if debug:
                debug(f"[修复路径] 暴力正则修复失败: {e}")
    if 'write' in s and 'content' in s:
        try:
            new_s = re.sub(r'("content"\s*:\s*")(.*?)(")', lambda m: m.group(1) + m.group(2).replace('"', '\\"') + m.group(3), s, flags=re.DOTALL)
            obj = json.loads(new_s)
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                if debug:
                    debug("[修复路径] write 暴力正则修复成功")
                return obj
        except Exception as e:
            if debug:
                debug(f"[修复路径] write 暴力正则修复失败: {e}")

    return None

def extract_all_function_calls(text, debug_callback=None):
    if not text:
        return []
    def debug(msg):
        if debug_callback:
            debug_callback(msg)
        else:
            logger.debug(msg)
    results = []
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        json_obj = _find_first_json_object(line)
        if json_obj:
            debug(f"[extract] 截取到JSON对象: {json_obj[:80]}...")
            obj = _try_parse_json(json_obj, debug=debug)
            if obj:
                results.append(obj)
                debug(f"提取调用: {obj.get('name')}")
                continue
        parts = _split_json_objects_in_line(line)
        if parts:
            for part in parts:
                debug(f"[extract] 处理片段: {part[:80]}...")
                obj = _try_parse_json(part, debug=debug)
                if obj:
                    results.append(obj)
                    debug(f"提取调用: {obj.get('name')}")
                else:
                    debug(f"无法解析片段: {part[:100]}")
        else:
            debug(f"[extract] 整行: {line[:80]}...")
            obj = _try_parse_json(line, debug=debug)
            if obj:
                results.append(obj)
                debug(f"提取调用: {obj.get('name')}")
            else:
                debug(f"无法解析整行: {line[:100]}")
    debug(f"共提取 {len(results)} 个调用")
    return results

def extract_function_call(text, debug_callback=None):
    calls = extract_all_function_calls(text, debug_callback)
    return calls[0] if calls else None

def is_likely_tool_call(text):
    if not text or len(text) < 10:
        return False
    if re.search(r'"name"\s*:\s*"\w+"', text) and re.search(r'"arguments"\s*:', text):
        return True
    if re.search(r'"name"\s*:\s*"(write|exec|read|edit|mcp__\S+)"', text):
        return True
    return False

def repair_malformed_tool_call(text, debug_callback=None):
    if not text:
        return None
    def debug(msg):
        if debug_callback:
            debug_callback(msg)
    fixed = fix_malformed_json(text)
    try:
        obj = json.loads(fixed)
        if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
            debug("[repair_malformed_tool_call] 整体修复成功")
            return fixed
    except Exception as e:
        debug(f"[repair_malformed_tool_call] 整体修复失败: {e}")
    parts = _split_json_objects_in_line(text)
    if parts:
        for part in parts:
            try:
                obj = json.loads(part)
                if "name" in obj and "arguments" in obj:
                    debug("[repair_malformed_tool_call] 拆分对象成功")
                    return part
            except:
                pass
    if 'write' in text:
        repaired = _repair_write_content(text)
        try:
            obj = json.loads(repaired)
            if "name" in obj and "arguments" in obj:
                debug("[repair_malformed_tool_call] write修复成功")
                return repaired
        except Exception as e:
            debug(f"[repair_malformed_tool_call] write修复失败: {e}")
    if 'exec' in text and 'command' in text:
        repaired = _repair_exec_command(text, debug=debug)
        try:
            obj = json.loads(repaired)
            if "name" in obj and "arguments" in obj:
                debug("[repair_malformed_tool_call] exec修复成功")
                return repaired
        except Exception as e:
            debug(f"[repair_malformed_tool_call] exec修复失败: {e}")
    return None

def split_long_mdx(tool_calls, max_len=8000):
    new_calls = []
    i = 0
    while i < len(tool_calls):
        call = tool_calls[i]
        if call.get('name') == 'write' and i+1 < len(tool_calls) and tool_calls[i+1].get('name') == 'exec':
            content_str = call['arguments'].get('content', '')
            try:
                args = json.loads(content_str)
                mdx = args.get('mdx', '')
                title = args.get('title', '未命名文档')
                if len(mdx) > max_len:
                    logger.debug(f"mdx 长度 {len(mdx)} 超过阈值 {max_len}，开始拆分")
                    paragraphs = mdx.split('\n\n')
                    parts = []
                    current_part = ""
                    for para in paragraphs:
                        if len(current_part) + len(para) + 2 < max_len:
                            current_part += para + "\n\n"
                        else:
                            if current_part:
                                parts.append(current_part.rstrip())
                            current_part = para + "\n\n"
                    if current_part:
                        parts.append(current_part.rstrip())
                    for idx, part in enumerate(parts, 1):
                        new_title = f"{title} (第{idx}部分)" if len(parts) > 1 else title
                        new_args = {"title": new_title, "mdx": part}
                        new_content = json.dumps(new_args, ensure_ascii=False)
                        new_write = {
                            "name": "write",
                            "arguments": {
                                "path": f"/tmp/td_args_{idx}.json",
                                "content": new_content
                            }
                        }
                        new_exec = {
                            "name": "exec",
                            "arguments": {
                                "command": f"mcporter call tencent-docs.create_smartcanvas_by_mdx --args \"$(cat /tmp/td_args_{idx}.json)\"",
                                "workdir": "/root",
                                "timeout": 45
                            }
                        }
                        new_calls.append(new_write)
                        new_calls.append(new_exec)
                    i += 2
                    continue
            except Exception as e:
                logger.debug(f"拆分时解析失败: {e}")
        new_calls.append(call)
        i += 1
    return new_calls
