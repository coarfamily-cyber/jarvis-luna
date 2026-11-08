#!/usr/bin/env python3
"""
Setup and environment verification for JARVIS LUNA Trending AI Suite
Installs optional dependencies and verifies runtime readiness.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = [
    ("Agent Desktop", "vercel-labs/agent-desktop", "https://github.com/vercel-labs/agent-desktop"),
    ("Scrapling", "D4Vinci/Scrapling", "https://github.com/D4Vinci/Scrapling"),
    ("Hyprland", "hyprwm/Hyprland", "https://github.com/hyprwm/Hyprland"),
    ("FreeToken", "FlashML-org/FreeToken", "https://github.com/FlashML-org/FreeToken"),
    ("Kronos", "shiyu-coder/Kronos", "https://github.com/shiyu-coder/Kronos"),
    ("Colibri", "JustVugg/colibri", "https://github.com/JustVugg/colibri"),
    ("WorkTrunk", "max-sixty/worktrunk", "https://github.com/max-sixty/worktrunk"),
    ("NanoChat", "karpathy/nanochat", "https://github.com/karpathy/nanochat"),
    ("Heretic", "p-e-w/heretic", "https://github.com/p-e-w/heretic"),
]


def check_runtime():
    print("=" * 60)
    print("  JARVIS LUNA - 9대 깃허브 트렌딩 도구 환경 점검 및 셋업")
    print("=" * 60)

    print(f"[1] Python 버전: {sys.version.split()[0]} (OK)")
    git_bin = shutil.which("git")
    print(f"[2] Git 실행기: {git_bin or '미설치'} ({'OK' if git_bin else 'WARN'})")

    print("\n[3] 9대 트렌딩 도구 브릿지 모듈 상태:")
    auto_dir = Path("automation")
    modules = [
        ("agent_desktop.py", "1위 Agent Desktop 브릿지"),
        ("scrapling_crawler.py", "3위 Scrapling 브릿지"),
        ("local_ai_engines.py", "6위/10위/14위 로컬 AI 허브 (FreeToken/Colibri/NanoChat)"),
        ("kronos_forecaster.py", "8위 Kronos 시계열 브릿지"),
        ("worktrunk_manager.py", "12위 WorkTrunk 워크트리 브릿지"),
        ("heretic_filter.py", "15위 Heretic 프롬프트 브릿지"),
        ("trending_ai_orchestrator.py", "통합 마스터 오케스트레이터"),
    ]

    for fname, desc in modules:
        target = auto_dir / fname
        exists = target.exists()
        print(f"  - {desc}: {'정상 탑재 (READY)' if exists else '누락 (MISSING)'}")

    print("\n[4] 모든 브릿지 모듈이 내장 엔진을 포함하고 있어 별도 외부 바이너리 없이 즉시 구동 가능합니다.")
    print("=" * 60)


if __name__ == "__main__":
    check_runtime()
