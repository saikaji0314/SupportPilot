from langchain_openai import ChatOpenAI
from supportpilot.config import load_chat_config


def bailian(*, timeout: float | None = None, max_retries: int | None = None):
    config = load_chat_config()
    chatLLM = ChatOpenAI(
        timeout=config.timeout if timeout is None else timeout,
        max_retries=config.max_retries if max_retries is None else max_retries,
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
    )
    return chatLLM
