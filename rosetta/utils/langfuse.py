from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from langfuse import Langfuse, LangfuseSpan, propagate_attributes
from openai import AsyncOpenAI

from .config import LangfuseConfig

type TraceValue = str | bool | int | float | None


@dataclass(frozen=True, slots=True)
class TraceRequest:
    name: str
    input: str | None
    user_id: str
    metadata: Mapping[str, TraceValue]


client = (
    Langfuse(
        public_key=LangfuseConfig.PUBLIC_KEY,
        secret_key=LangfuseConfig.SECRET_KEY,
        base_url=LangfuseConfig.HOST,
    )
    if LangfuseConfig.PUBLIC_KEY and LangfuseConfig.SECRET_KEY
    else None
)


def create_async_openai(*, base_url: str | None, api_key: str | None) -> AsyncOpenAI:
    if client is None:
        return AsyncOpenAI(base_url=base_url, api_key=api_key)

    from langfuse import openai as instrumented_openai

    return instrumented_openai.AsyncOpenAI(base_url=base_url, api_key=api_key)


@contextmanager
def trace_request(request: TraceRequest) -> Iterator[LangfuseSpan | None]:
    if client is None:
        yield None
        return

    with (
        client.start_as_current_observation(
            name=request.name,
            as_type="span",
            input=request.input,
        ) as span,
        propagate_attributes(
            user_id=request.user_id,
            metadata=dict(request.metadata),
        ),
    ):
        yield span
