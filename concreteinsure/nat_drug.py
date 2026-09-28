"""NAT medicine tools and an SDK-backed LangChain client for its native agent."""
import json
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function import FunctionGroup
from nat.builder.llm import LLMProviderInfo
from nat.cli.register_workflow import register_function_group, register_llm_client, register_llm_provider
from nat.data_models.function import FunctionGroupBaseConfig
from nat.data_models.llm import LLMBaseConfig

from concreteinsure.agents.drug_agent import SKILL, EmptyArgs, NameArgs, ProductArgs, current_state
from concreteinsure.core import AppError
from concreteinsure.diagnostics import record


class MedicineToolsConfig(FunctionGroupBaseConfig, name='concreteinsure_medicine_tools'):
    pass


@register_function_group(config_type=MedicineToolsConfig)
async def medicine_tools(config: MedicineToolsConfig, builder: Builder):
    group = FunctionGroup(config=config)

    async def lookup_products(value: NameArgs) -> str:
        record('agent.tool', agent='drug_evidence', tool='lookup_products')
        return json.dumps(await current_state().lookup(value.name_id), ensure_ascii=False)

    async def inspect_ingredients(value: ProductArgs) -> str:
        record('agent.tool', agent='drug_evidence', tool='inspect_ingredients')
        return json.dumps(await current_state().ingredients(value.product_id), ensure_ascii=False)

    async def inspect_label(value: ProductArgs) -> str:
        record('agent.tool', agent='drug_evidence', tool='inspect_label')
        return json.dumps(await current_state().label(value.product_id), ensure_ascii=False)

    async def finish_evidence(value: EmptyArgs) -> str:
        record('agent.tool', agent='drug_evidence', tool='finish_evidence')
        return current_state().finish()

    group.add_function('lookup_products', lookup_products, input_schema=NameArgs,
                       description='Find MFDS candidates for one provided name_id. Never select a candidate for the user.')
    group.add_function('inspect_ingredients', inspect_ingredients, input_schema=ProductArgs,
                       description='Fetch fresh official ingredients for a user-selected product_id. Returns label availability.')
    group.add_function('inspect_label', inspect_label, input_schema=ProductArgs,
                       description='Inspect original label evidence after ingredients. Required when labelAvailable is true.')
    group.add_function('finish_evidence', finish_evidence, input_schema=EmptyArgs,
                       description='Application-only completion control. Revalidates all required observations and source integrity before returning server evidence.')
    yield group


class EvidenceNimConfig(LLMBaseConfig, name='concreteinsure_evidence_nim'):
    pass


@register_llm_provider(config_type=EvidenceNimConfig)
async def evidence_provider(config: EvidenceNimConfig, builder: Builder):
    yield LLMProviderInfo(config=config, description='Request-scoped Nemotron via NeMo Microservices SDK; no extra credentials.')


class EvidenceChatModel(BaseChatModel):
    # NAT streams internally; disable streaming so the existing bounded SDK call
    # stays responsible for timeout, retry, cancellation and console diagnostics.
    disable_streaming: bool = True

    @property
    def _llm_type(self):
        return 'concreteinsure_nemo_microservices'

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools])

    def _generate(self, *args, **kwargs):
        raise AppError('ASYNC_AGENT_REQUIRED', 503)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        state = current_state()
        if state.completion_ready:
            # NAT still executes its validated return_direct tool, but deciding
            # to finish is application control flow, not another NIM inference.
            record('agent.finalizing', agent='drug_evidence', reason='required_evidence_complete')
            call = {'name': 'medicine__finish_evidence', 'args': {},
                    'id': 'application-finish-' + uuid4().hex, 'type': 'tool_call'}
            source = 'application'
        else:
            original = convert_to_openai_messages(messages)
            prompt = [{'role': 'system', 'content': SKILL}, *original]
            tools = [tool for tool in kwargs['tools']
                     if tool['function']['name'] != 'medicine__finish_evidence']
            response = await state.nim.complete(prompt, tools)
            call = state.plan(response)
            source = 'model'
        # Prose and model-authored evidence never cross this boundary. The
        # internal control message carries no fabricated provider token usage.
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[call],
                          response_metadata={'finish_reason': 'tool_calls', 'completion_source': source}))])


@register_llm_client(config_type=EvidenceNimConfig, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
async def evidence_client(config: EvidenceNimConfig, builder: Builder):
    yield EvidenceChatModel()
