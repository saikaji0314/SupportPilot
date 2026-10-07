"""一些工具函数"""

import json
from pathlib import Path
import uuid
from datetime import datetime, timezone


def run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


# 写入 JSON 文件
def write_json(data: dict, filename: Path | str) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
