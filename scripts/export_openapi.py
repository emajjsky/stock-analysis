"""导出本轮真实路由快照；不代表响应字段均已生成强类型。"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# app模块含全局实例；导出契约时必须将该实例也隔离到内存，避免打开用户库。
os.environ['WORKSTATION_DB'] = ':memory:'
from backend.app import create_app


if __name__ == "__main__":
    app = create_app(":memory:")
    target = ROOT / "docs/openapi.json"
    target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已导出 {len(app.openapi()['paths'])} 个路径：{target}")
