from langchain_openai import ChatOpenAI
import os
from pathlib import Path
from dotenv import load_dotenv

from supportpilot.schemas import Observation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_bailian():
    load_dotenv(PROJECT_ROOT / ".env")

    chatLLM = ChatOpenAI(
        api_key=os.getenv("API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-plus-2026-05-26",
    )
    messages = [
        {"role": "system", "content": "你是排障信息整理助手。不要编造设备检测结果。"},
        {"role": "user", "content": "手机能连上 Wi-Fi，但家里其他设备也不能上网。"}]
    response = chatLLM.with_structured_output(Observation).invoke(messages)
    print(response.model_dump())
