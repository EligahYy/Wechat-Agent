"""Safe analysis failure summaries. No request bodies, chat text, IDs, or keys."""

import re

from .analysis import budget_state
from .config import secret
from .model_network import transport_summary


def explain(code):
    code = code or "unknown_error"
    known = {
        "HTTP_400": (
            "模型拒绝请求参数",
            "核对模型名称、JSON模式和请求参数；等待不会自动修复参数错误。",
        ),
        "HTTP_402": (
            "DeepSeek账户余额不足",
            "到DeepSeek控制台核对余额；本机每日token预算与账户余额是两回事。",
        ),
        "HTTP_404": (
            "模型或接口不存在",
            "核对DEEPSEEK_MODEL与该账户可用模型，修改后重启。",
        ),
        "HTTP_429": ("模型接口限流", "等待限流复查时间，避免连续手动重试。"),
        "blocked_credentials": (
            "API凭据或权限未通过",
            "在设置更新API key，核对模型权限后恢复。",
        ),
        "ReadTimeout": (
            "等待模型响应超时",
            "检查本机外网连接；请求可能已经计费，不应反复重试。",
        ),
        "ConnectTimeout": (
            "连接模型接口超时",
            "检查本机能否连接api.deepseek.com与代理配置。",
        ),
        "ConnectError:tls_certificate": (
            "HTTPS证书校验失败",
            "核对Python使用的CA证书及SSL_CERT_FILE/SSL_CERT_DIR；不要关闭证书校验。",
        ),
        "ConnectError:dns": (
            "无法解析模型接口域名",
            "检查当前终端的DNS与代理配置，确认api.deepseek.com可解析。",
        ),
        "ConnectError:refused": (
            "连接被拒绝",
            "若使用本机代理，核对软件是否运行及HTTP/混合端口是否一致；不要猜测端口。",
        ),
        "ConnectError:unreachable": (
            "当前路由无法到达模型接口",
            "检查当前终端的外网连接、网卡路由和代理；微信采集服务正常不代表外网可达。",
        ),
        "model_proxy_configuration": (
            "模型代理地址配置无效",
            "DEEPSEEK_PROXY仅支持direct或http(s)代理URL；代理地址不要发到聊天。",
        ),
        "model_ca_configuration": (
            "模型CA证书配置不可用",
            "核对SSL_CERT_FILE/SSL_CERT_DIR指向的文件是否存在且可读取。",
        ),
        "model_transport_configuration": (
            "模型网络客户端配置失败",
            "核对代理与CA配置，修正后重启应用。",
        ),
        "ConnectError": (
            "无法连接模型接口",
            "检查DNS、代理和HTTPS连接；微信源服务连通不代表模型接口可用。",
        ),
        "ProxyError": ("模型请求代理连接失败", "检查启动应用的终端代理配置。"),
        "model_incomplete_output": (
            "模型输出被截断",
            "当前输出额度不足或模型未完成JSON；需要检查模型与输出策略。",
        ),
        "model_unknown_actor": (
            "模型返回了输入中不存在的身份引用",
            "身份校验拒绝写入，需要修复模型输出契约，不能放开校验。",
        ),
        "model_unknown_evidence": (
            "模型返回了不存在的消息引用",
            "证据校验拒绝写入，需要修复模型输出契约，不能放开校验。",
        ),
        "explicit_date_without_source": (
            "模型约定日期缺少原话依据",
            "日期校验拒绝写入，需要修复提取结果，不能虚构截止日期。",
        ),
    }
    if code.startswith("model_schema:"):
        title, action = (
            "模型JSON字段不符合契约",
            "将下方字段错误码用于定位契约差异；不需要发送聊天原文。",
        )
    elif code.startswith("HTTP_5"):
        title, action = (
            "模型服务暂时异常",
            "等待服务恢复；持续失败时查看DeepSeek服务状态。",
        )
    else:
        title, action = known.get(
            code,
            ("分析请求未完成", "需要根据具体错误码定位，不能仅根据暂停提示推断根因。"),
        )
    safe = code if re.fullmatch(r"[A-Za-z0-9_:.,-]{1,250}", code) else "unknown_error"
    return {"code": safe, "title": title, "action": action}


def snapshot(db):
    rows = db.rows(
        "SELECT json_extract(e.payload,'$.error') error,e.created_at FROM events e JOIN jobs j ON j.id=e.entity_id JOIN conversations v ON v.id=json_extract(j.payload,'$.conversation_id') WHERE e.kind='analysis_outcome' AND v.account_id=? AND json_extract(e.payload,'$.status') IN ('failed','retry_wait','blocked_credentials') ORDER BY e.created_at DESC LIMIT 3",
        (db.settings.source_account,),
    )
    return {
        "model": db.settings.model,
        "key_configured": bool(secret("DEEPSEEK_API_KEY")),
        "budget": budget_state(db),
        "transport": transport_summary(),
        "recent_errors": [explain(r["error"]) | {"at": r["created_at"]} for r in rows],
    }
