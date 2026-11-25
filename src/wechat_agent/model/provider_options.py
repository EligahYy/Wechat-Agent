"""Provider-specific options for known official chat-completions endpoints."""
from urllib.parse import urlsplit


DEEPSEEK_TEXT_MODELS = frozenset({'deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-pro'})


def deepseek_non_thinking(endpoint: str, model_id: str) -> bool:
    if model_id not in DEEPSEEK_TEXT_MODELS:
        return False
    url = urlsplit(endpoint)
    return (
        url.scheme == 'https'
        and url.netloc in {'api.deepseek.com', 'api.deepseek.com:443'}
        and url.path.rstrip('/') in {'/chat/completions', '/v1/chat/completions'}
    )


def profile_non_thinking(request, config) -> bool:
    return (
        request.purpose == 'profile'
        and request.phase in {'extract', 'merge'}
        and deepseek_non_thinking(config.endpoint, config.model_id)
    )
