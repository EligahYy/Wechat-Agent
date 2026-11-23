"""Explicit minimal chat-completions check; contains no customer materials."""
import asyncio
import httpx
from .probe import ModelProbeConfig,ModelProbeError,_request,_validate_response
from .gateway import MODEL_DEADLINE_SECONDS, MODEL_HTTP_TIMEOUT

async def check_connection(saved,credentials,transport=None):
    key=credentials.get(saved['credential_ref'])
    config=ModelProbeConfig(endpoint=saved['endpoint'],model_id=saved['model_id'],response_mode=saved['response_mode'],probe_output_tokens=min(256,saved['max_output_tokens']))
    facts={'capacity_verified':False,'vision_verified':False}
    try:
        async with asyncio.timeout(MODEL_DEADLINE_SECONDS):
            async with httpx.AsyncClient(transport=transport,follow_redirects=False,timeout=MODEL_HTTP_TIMEOUT,trust_env=False) as client:
                response=await client.post(config.endpoint,json=_request(config),headers={'Authorization':'Bearer '+key})
                _validate_response(response,config,facts)
    except ModelProbeError as error:return 'failed',str(error)
    except httpx.ConnectTimeout:return 'failed','model_connect_timeout'
    except (httpx.TimeoutException,TimeoutError):return 'failed','model_timeout'
    except httpx.HTTPError:return 'failed','model_unreachable'
    except (TypeError,ValueError,KeyError,IndexError,AttributeError):return 'failed','model_response_invalid'
    return 'passed',None
