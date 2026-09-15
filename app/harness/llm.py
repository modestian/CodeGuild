"""LLM 客户端：Provider 抽象 + 结构化输出 + 校验修复 + 成本核算。

对应需求：NFR-SCALE-03（LLM 可替换：OpenAI / Claude / Gemini / Local Models 配置化切换）、
FR-EVAL-08（Token / Cost 统计）、风险：LLM 输出不稳定 → 结构化输出 + 校验 + 重试。

Provider：
- openai    ：OpenAI / DeepSeek / Ollama / vLLM / Gemini(OpenAI 兼容端点) 等
- anthropic ：Claude
- mock      ：离线测试（支持脚本化响应序列）
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional, TypeVar, Union

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.harness.retry import RetryManager, is_transient_error

logger = logging.getLogger("copilot.llm")

TModel = TypeVar("TModel", bound=BaseModel)

Message = dict[str, Any]


class LLMUsage(BaseModel):
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    content: str = ""
    # 原生 function calling 工具调用（OpenAI 格式：{id, type, function:{name, arguments}}）
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: LLMUsage = LLMUsage()
    cost_usd: float = 0.0


class StructuredOutputError(RuntimeError):
    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def extract_json(text: str) -> Optional[dict[str, Any]]:
    """从模型输出中提取 JSON 对象（容忍 markdown 代码块与前后缀文本）。"""
    if not text:
        return None
    text = text.strip()
    # 直接解析
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    # 代码块
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        try:
            data = json.loads(fence.group(1).strip())
            return data if isinstance(data, dict) else None
        except ValueError:
            pass
    # 最外层花括号
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else None
        except ValueError:
            # 常见修复：去掉尾随逗号
            fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                data = json.loads(fixed)
                return data if isinstance(data, dict) else None
            except ValueError:
                return None
    return None


class LLMClient(ABC):
    """LLM 客户端抽象。"""

    def __init__(self, settings: Settings, agent: str = ""):
        self.settings = settings
        self.agent = agent
        self.model = settings.model_for_agent(agent or None)
        self.retry = RetryManager(max_attempts=max(1, settings.llm_max_retries + 1))

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:  # pragma: no cover
        ...

    def compute_cost(self, usage: LLMUsage) -> float:
        price = self.settings.price_for_model(usage.model or self.model)
        return round(
            usage.input_tokens / 1_000_000 * price.get("input", 0.0)
            + usage.output_tokens / 1_000_000 * price.get("output", 0.0),
            6,
        )

    async def complete_structured(
        self,
        messages: list[Message],
        schema: type[TModel],
        repair_attempts: int = 2,
        temperature: Optional[float] = None,
    ) -> tuple[TModel, LLMResponse]:
        """结构化输出：JSON 提取 → Pydantic 校验 → 失败反馈修复重试。"""
        working = list(messages)
        last_error = ""
        last_response: Optional[LLMResponse] = None
        for attempt in range(repair_attempts + 1):
            response = await self.complete(working, temperature=temperature)
            last_response = response
            data = extract_json(response.content)
            if data is not None:
                try:
                    return schema.model_validate(data), response
                except ValidationError as exc:
                    last_error = self._summarize_validation_error(exc)
            else:
                last_error = "输出中未找到合法 JSON"
            if attempt < repair_attempts:
                working = working + [
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": (
                            f"你的输出不符合要求：{last_error}\n"
                            f"请严格输出一个符合以下 JSON Schema 的 JSON 对象（不要输出任何其他内容）：\n"
                            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
                        ),
                    },
                ]
        raise StructuredOutputError(f"结构化输出失败（已修复尝试 {repair_attempts} 次）: {last_error}", last_response.content if last_response else "")

    @staticmethod
    def _summarize_validation_error(exc: ValidationError) -> str:
        lines = []
        for err in exc.errors()[:8]:
            loc = ".".join(str(p) for p in err.get("loc", []))
            lines.append(f"- 字段 {loc}: {err.get('msg')}")
        return "\n".join(lines) or str(exc)


# =========================================================
# OpenAI 兼容
# =========================================================


class OpenAICompatClient(LLMClient):
    def __init__(self, settings: Settings, agent: str = ""):
        super().__init__(settings, agent)
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {
            "api_key": settings.llm_api_key or "not-needed",
            "timeout": settings.llm_timeout,
            "max_retries": 0,  # 由 RetryManager 统一处理
        }
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        self.client = AsyncOpenAI(**kwargs)

    async def complete(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        if tools:
            params["tools"] = tools

        async def _call():
            return await self.client.chat.completions.create(**params)

        completion = await self.retry.run(_call, retryable=is_transient_error)
        choice = completion.choices[0] if completion.choices else None
        message = choice.message if choice and choice.message else None
        content = (message.content if message else "") or ""
        # 原生 function calling：规范化 tool_calls（仅保留协议字段，剔除 index 等 SDK 附加项）
        tool_calls: list[dict[str, Any]] = []
        for tc in (getattr(message, "tool_calls", None) or []):
            fn = getattr(tc, "function", None)
            tool_calls.append(
                {
                    "id": tc.id or "",
                    "type": "function",
                    "function": {
                        "name": getattr(fn, "name", "") or "",
                        "arguments": getattr(fn, "arguments", "") or "{}",
                    },
                }
            )
        usage = LLMUsage(model=self.model)
        if completion.usage:
            usage.input_tokens = completion.usage.prompt_tokens or 0
            usage.output_tokens = completion.usage.completion_tokens or 0
        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage, cost_usd=self.compute_cost(usage))


# =========================================================
# Anthropic
# =========================================================


class AnthropicClient(LLMClient):
    def __init__(self, settings: Settings, agent: str = ""):
        super().__init__(settings, agent)
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=settings.llm_api_key or "not-needed", timeout=settings.llm_timeout)

    async def complete(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        convo = self._to_anthropic_messages([m for m in messages if m.get("role") != "system"])
        params: dict[str, Any] = {
            "model": self.model,
            "system": "\n\n".join(system_parts) or None,
            "messages": convo,
            "max_tokens": max_tokens or 8192,
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
        }
        if tools:
            params["tools"] = [
                {
                    "name": (t.get("function") or {}).get("name", ""),
                    "description": (t.get("function") or {}).get("description", "") or "",
                    "input_schema": (t.get("function") or {}).get("parameters")
                    or {"type": "object", "properties": {}},
                }
                for t in tools
                if (t.get("function") or {}).get("name")
            ]

        async def _call():
            return await self.client.messages.create(**params)

        completion = await self.retry.run(_call, retryable=is_transient_error)
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in completion.content or []:
            btype = getattr(block, "type", "")
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id or "",
                        "type": "function",
                        "function": {
                            "name": block.name or "",
                            "arguments": json.dumps(block.input or {}, ensure_ascii=False),
                        },
                    }
                )
        usage = LLMUsage(model=self.model)
        if completion.usage:
            usage.input_tokens = completion.usage.input_tokens or 0
            usage.output_tokens = completion.usage.output_tokens or 0
        return LLMResponse(
            content="".join(text_parts), tool_calls=tool_calls, usage=usage, cost_usd=self.compute_cost(usage)
        )

    @staticmethod
    def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
        """OpenAI 工具消息（assistant.tool_calls / role=tool）→ Anthropic 格式。

        Anthropic 要求：assistant 的 tool_use 块在其消息内；tool_result 块位于 user 消息中。
        """
        result: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        def flush_tool_results() -> None:
            if pending_tool_results:
                result.append({"role": "user", "content": list(pending_tool_results)})
                pending_tool_results.clear()

        for msg in messages:
            role = msg.get("role")
            if role == "tool":
                pending_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id") or "",
                        "content": str(msg.get("content") or ""),
                    }
                )
                continue
            flush_tool_results()
            if role == "assistant" and msg.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": str(msg["content"])})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except (TypeError, ValueError):
                        args = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id") or "",
                            "name": fn.get("name") or "",
                            "input": args if isinstance(args, dict) else {},
                        }
                    )
                result.append({"role": "assistant", "content": blocks})
                continue
            if role in {"user", "assistant"}:
                result.append({"role": role, "content": str(msg.get("content") or "")})
        flush_tool_results()
        return result


# =========================================================
# Mock（离线测试）
# =========================================================


class ScriptExhausted(RuntimeError):
    pass


class MockLLMClient(LLMClient):
    """离线 Mock：支持脚本化响应序列（str 或 dict），用于单元/集成测试。

    script 项：
    - str：直接作为响应 content
    - dict：序列化为 JSON 作为 content
    - callable(messages, schema) -> str | dict
    脚本耗尽后：若提供 fallback_synthesize（默认 True），按 schema 合成最小合法 JSON。
    """

    def __init__(
        self,
        settings: Settings,
        agent: str = "",
        script: Optional[list[Union[str, dict, Any]]] = None,
        fallback_synthesize: bool = True,
    ):
        super().__init__(settings, agent)
        self.model = f"mock::{agent or 'default'}"
        # 共享引用：多个客户端实例（每次 runtime.run 新建）顺序消费同一脚本队列
        self.script: list[Any] = script if script is not None else []
        self.fallback_synthesize = fallback_synthesize

    async def complete(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        if not self.script:
            raise ScriptExhausted(f"Mock 响应脚本已耗尽（agent={self.agent}）")
        item = self.script.pop(0)
        if callable(item):
            item = item(messages)
        est_in = sum(len(str(m.get("content", ""))) for m in messages) // 4
        # 脚本项为 JSON 决策协议的工具调用 → 转换为原生 function calling 响应
        if isinstance(item, dict) and item.get("decision") == "tool_call" and item.get("tool"):
            call_id = f"call_mock_{uuid.uuid4().hex[:12]}"
            tool_calls = [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(item["tool"]),
                        "arguments": json.dumps(item.get("arguments") or {}, ensure_ascii=False),
                    },
                }
            ]
            usage = LLMUsage(model=self.model, input_tokens=est_in, output_tokens=8)
            return LLMResponse(content="", tool_calls=tool_calls, usage=usage, cost_usd=0.0)
        content = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
        usage = LLMUsage(model=self.model, input_tokens=est_in, output_tokens=len(content) // 4)
        return LLMResponse(content=content, usage=usage, cost_usd=0.0)


def _synthesize_default(schema: type[BaseModel], field_name: str = "") -> Any:
    """按 schema 合成最小合法对象（Mock 兜底）。"""
    defaults: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        annotation = field.annotation
        if annotation in (str, Optional[str]):
            defaults[name] = ""
        elif annotation in (int, Optional[int]):
            defaults[name] = 0
        elif annotation in (float, Optional[float]):
            defaults[name] = 0.0
        elif annotation in (bool, Optional[bool]):
            defaults[name] = False
        elif annotation is dict or str(annotation).startswith("dict"):
            defaults[name] = {}
        else:
            defaults[name] = []
    return defaults


def create_llm_client(settings: Settings, agent: str = "", script: Optional[list[Any]] = None) -> LLMClient:
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockLLMClient(settings, agent, script=script)
    if provider == "anthropic":
        return AnthropicClient(settings, agent)
    return OpenAICompatClient(settings, agent)
