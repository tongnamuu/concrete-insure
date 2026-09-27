import asyncio
import copy
from insurelens.agent import run_investigation
from insurelens.core import AppError

RECOVERABLE = {'NIM_TIMEOUT','NIM_UNAVAILABLE','NIM_SERVICE_UNAVAILABLE','NIM_MODEL_UNAVAILABLE','NIM_AUTH_FAILED','NIM_RATE_LIMIT','NIM_INVALID_JSON','NIM_INCOMPLETE_RESPONSE','NIM_INVALID_RESPONSE','NIM_INVALID_TOOL_CALL','NIM_STOP_WITHOUT_SEARCH','REPEATED_TOOL_CALL','AGENT_STEP_LIMIT','UNSUPPORTED_TOOL','INVALID_TOOL_ARGUMENTS'}


async def with_provider_fallback(input, primary, local=run_investigation):
    # Isolate each run's mutable case facts; never reuse partially changed provider state.
    def fresh():
        return {key: copy.deepcopy(value) if key in {'document', 'request', 'products'} else value for key, value in input.items()}
    snapshot = fresh()
    try:
        return await primary(**fresh())
    except AppError as error:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError() from error
        if str(error) not in RECOVERABLE:
            raise
        input.get('emit', lambda *_: None)('stage_started', {'stage': 'local_recovery', 'message': 'NVIDIA 응답을 받지 못해 로컬에서 검증된 근거를 찾습니다.'})
        class LocalProvider:
            enabled = False
        result = await local(**{**snapshot, 'request': {**snapshot['request'], 'cloudConsent': False, 'translation': False}, 'nim': LocalProvider()})
        return {**result, 'mode': 'local', 'warnings': [str(error)]}
