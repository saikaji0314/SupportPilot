from supportpilot.paths import ROOT
from langchain_openai import ChatOpenAI
import os
from pathlib import Path
from dotenv import load_dotenv


def bailian(*, timeout: float = 60.0, max_retries: int = 0):
    load_dotenv(ROOT / ".env")
    chatLLM = ChatOpenAI(
        timeout=timeout,
        max_retries=max_retries,
        api_key=os.getenv("API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-plus-2026-05-26",
    )
    return chatLLM
