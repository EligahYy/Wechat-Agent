"""Summarize wire payloads without rendering XML, expanding forwards or changing evidence."""
import json
import re

LABELS={'merged_messages':'转发聊天记录','image':'图片','voice':'语音','video':'视频','file':'文件',
        'quote':'引用消息','app':'应用消息','system':'系统通知','revoke':'撤回消息'}
VARIANTS={'MergedMessages':'转发聊天记录','Image':'图片','Voice':'语音','Video':'视频','File':'文件',
          'Quote':'引用消息','Link':'链接','Location':'位置','Emoji':'表情','Sticker':'表情',
          'MiniProgram':'小程序','ContactCard':'名片','Transfer':'转账','RedPacket':'红包'}
WIRE_XML=re.compile(r'^\s*(?:[\w@.-]+:\s*)?<(?:\?xml\b|msg\b|appmsg\b|sysmsg\b|voicemsg\b|videomsg\b|emoji\b|location\b|img\b|msgsource\b)',re.I)

def display_body(kind,body):
    label=LABELS.get(kind,'暂不支持展示的消息')
    fallback=f'[{label}]'
    if kind=='merged_messages':return fallback
    if not body:return ''
    if WIRE_XML.match(body):return fallback
    if body.lstrip().startswith(('{','[')) and re.search(r'"MergedMessages"\s*:',body):return '[转发聊天记录]'
    if body.lstrip().startswith(('{','[')) and '"raw_xml"' in body and len(body)>262144:return fallback
    payload=None
    # Bound parsing work; large nontext payloads cannot flood the reader.
    if len(body)<=262144 and body.lstrip().startswith('{'):
        try:payload=json.loads(body)
        except (ValueError,RecursionError):pass
    if isinstance(payload,dict):
        if 'MergedMessages' in payload:return '[转发聊天记录]'
        for variant,title in VARIANTS.items():
            if variant not in payload:continue
            value=payload[variant]
            text=value.get('reply_text' if variant=='Quote' else 'title') if isinstance(value,dict) else None
            if variant in ('File','Quote','Link','MiniProgram') and isinstance(text,str) and text.strip() and not WIRE_XML.match(text) and len(text)<=512:
                return f'[{title}] {text}' if variant in ('Link','MiniProgram') else text
            return f'[{title}]'
        if kind!='text' or 'raw_xml' in payload:return fallback
    if kind!='text' and (body.lstrip().startswith(('{','[')) or '<msg' in body or 'raw_xml' in body):return fallback
    return body
