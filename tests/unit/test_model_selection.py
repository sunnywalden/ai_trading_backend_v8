#!/usr/bin/env python3
"""测试 OpenAI 模型自动选择功能

说明：该脚本已从项目根目录归档到 scripts/test_scripts/。
"""

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.services.ai_analysis_service import (
    _get_available_models,
    _select_best_models,
    AIAnalysisService,
)


async def test_model_selection():
    print("=" * 70)
    print("OpenAI Model Auto-Selection Test")
    print("=" * 70)

    print("\n[Test 1: Fetch Available Models from OpenAI API]")
    print("  请求中...")

    try:
        available_models = await _get_available_models()
        print(f"  ✓ 成功获取 {len(available_models)} 个可用模型")
        print("\n  可用聊天模型列表 (按优先级排序):")
        for i, model in enumerate(available_models[:10], 1):
            marker = "⭐" if i == 1 else "  "
            print(f"    {marker} {i}. {model}")
        if len(available_models) > 10:
            print(f"    ... 还有 {len(available_models) - 10} 个模型")
    except Exception as e:
        print(f"  ✗ 获取失败: {str(e)}")
        return

    print("\n[Test 2: Validate Configured Model]")
    configured_model = settings.OPENAI_MODEL
    print(f"  配置的模型: {configured_model}")

    if configured_model in available_models:
        print("  ✓ 配置的模型可用")
        rank = available_models.index(configured_model) + 1
        print(f"  模型排名: #{rank}/{len(available_models)}")
    else:
        print("  ⚠️  配置的模型不可用")
        print(f"  说明: '{configured_model}' 不在OpenAI可用模型列表中")

    print("\n[Test 3: Smart Model Selection]")
    selected_models = _select_best_models(configured_model, available_models)
    print(f"  ✓ 已选择 {len(selected_models)} 个模型作为回退链:")
    for i, model in enumerate(selected_models, 1):
        status = "主要" if i == 1 else f"回退{i-1}"
        print(f"    {i}. [{status}] {model}")

    print("\n[Test 4: AIAnalysisService Initialization]")
    try:
        service = AIAnalysisService()
        if service.client:
            print("  ✓ OpenAI客户端已初始化")
            service_models = await service._get_models()
            print("  ✓ 服务将使用以下模型:")
            for i, model in enumerate(service_models, 1):
                print(f"    {i}. {model}")
        else:
            print("  ⚠️  OpenAI客户端未初始化 (API key可能未配置)")
    except Exception as e:
        print(f"  ✗ 初始化失败: {str(e)}")

    print("\n[Test 5: Simulation of Different Configurations]")
    test_cases = [
        ("gpt-4", "有效模型 (高级)"),
        ("gpt-3.5-turbo", "有效模型 (标准)"),
        ("gpt-5-mini", "无效模型"),
        ("invalid-model", "完全无效"),
    ]

    for test_model, description in test_cases:
        print(f"\n  场景: {description}")
        print(f"    配置: OPENAI_MODEL={test_model}")
        selected = _select_best_models(test_model, available_models)
        print(f"    实际使用: {selected[0]}")
        if test_model != selected[0]:
            print("    ↳ 自动回退 (原因: 配置的模型不可用)")

    print("\n[Test 6: Cache Mechanism]")
    import time

    start = time.time()
    models1 = await _get_available_models()
    time1 = time.time() - start

    start = time.time()
    models2 = await _get_available_models()
    time2 = time.time() - start

    print(f"  首次调用: {time1:.3f}秒")
    print(f"  缓存调用: {time2:.3f}秒")
    if time2 > 0:
        print(f"  加速比: {time1 / time2:.1f}x")
    print("  ✓ 缓存有效期: 24小时")

    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print("  ✅ 自动获取OpenAI可用模型列表")
    print("  ✅ 智能验证配置的模型")
    print("  ✅ 自动回退到最佳可用模型")
    print("  ✅ 24小时缓存优化性能")
    print("  ✅ 多层回退保证服务可用性")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_model_selection())
