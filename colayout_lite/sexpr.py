"""Single-pass decoder for complete native lists, compatible with bridge atoms."""
import re
from virtuoso_bridge.virtuoso.skill_output import _unescape_skill_string

TOKENS=re.compile(r'\s*("(?:\\.|[^"\\])*"|[()]|[^\s()"]+)',re.S)

def parse_native(text):
    stack=[];root=None;end=0;finished=False
    for match in TOKENS.finditer(text):
        if match.start()!=end:raise ValueError('Malformed native string')
        end=match.end();token=match.group(1)
        if finished:raise ValueError('Multiple native values')
        if token=='(':
            value=[]
            if stack:stack[-1].append(value)
            else:root=value
            stack.append(value)
        elif token==')':
            if not stack:raise ValueError('Unbalanced native list')
            stack.pop()
            if not stack:finished=True
        else:
            if not stack:raise ValueError('Expected native list')
            value=(token[1:-1] if '\\' not in token else _unescape_skill_string(token[1:-1])) if token.startswith('"') else None if token=='nil' else True if token=='t' else token
            stack[-1].append(value)
    if text[end:].strip() or stack or not finished:raise ValueError('Truncated native list')
    return root
