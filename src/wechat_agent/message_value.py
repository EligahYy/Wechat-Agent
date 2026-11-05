"""Conservative display filter. Never deletes records or filters model context."""

import re

# Exact short acknowledgements only: negative replies, dates, figures, questions
# and attachment records are deliberately retained for business context.
ACK = re.compile(
    r"^(?:你好|您好|早上好|早|晚安|谢谢|谢谢您|感谢|收到|好的|好哒|好|嗯|嗯嗯|ok|okay|👌|👍|🙏|\[微笑\]|\[握手\])[!！。.,，\s]*$",
    re.I,
)


def classify(message):
    text = message["text"].strip()
    if message["type"] != "text":
        return {
            "value": "attachment",
            "value_reason": "附件可能包含业务信息，尚未自动理解",
        }
    if not text:
        return {"value": "noise", "value_reason": "空文本"}
    if ACK.fullmatch(text):
        return {"value": "noise", "value_reason": "简短寒暄或确认；可切换查看全部"}
    return {
        "value": "candidate",
        "value_reason": "保留供业务分析；不代表模型已确认价值",
    }
