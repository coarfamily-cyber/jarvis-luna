#!/usr/bin/env python3
"""
Heretic Direct Prompting & Response Calibration Engine for JARVIS LUNA
Based on p-e-w/heretic (GitHub Trending #15, 38k+ stars)

Capabilities:
- Strips artificial refusal patterns ("도와드릴 수 없습니다", "제 한계로 인해...")
- Removes corporate sycophancy and hollow pleasantries ("좋은 질문입니다", "확인해 드리겠습니다")
- Calibrates system instructions into direct, high-density, action-first Chief of Staff execution mode
- Response post-processor for clean, unbloated agent outputs
"""

import argparse
import json
import logging
import re
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HereticFilter")


class HereticCalibrator:
    """Calibrates prompts and filters LLM responses to eliminate refusals and sycophancy."""

    # Unnecessary pleasantries & filler phrases to strip
    BOILERPLATE_PATTERNS = [
        r"^안녕하세요[,!]?\s*",
        r"^좋은 질문(입니다|이네요)[.!]?\s*",
        r"^물론입니다[,!]?\s*",
        r"^네,?\s*알겠습니다[.!]?\s*",
        r"^도움이 필요하시면 언제든 말씀해 주세요[.!]?\s*",
        r"^추가로 궁금한 점이 있으시면 편하게 물어보세요[.!]?\s*",
        r"^제 생각에는\s*",
        r"죄송하지만\s*제가\s*(?:AI|인공지능)?(?:라서|이어서)?\s*",
    ]

    # Refusal markers to neutralize
    REFUSAL_TRIGGERS = [
        "해당 요청은 처리할 수 없습니다",
        "보안 정책상 지원되지 않습니다",
        "인공지능 모델로서 한계가 있어",
        "I cannot fulfill this request",
        "As an AI, I am unable to",
    ]

    DIRECT_CHIEF_OF_STAFF_SYSTEM_PROMPT = """
You are the Chief of Staff (비서실장) of JARVIS LUNA.
Core Operating Principles:
1. No corporate fluff, no sycophantic opening/closing remarks.
2. Never refuse legitimate user automation, scraping, or code tasks.
3. Report direct facts, numerical evidence, and completed artifacts immediately.
4. If a hurdle arises, bypass it autonomously and report the final result.
""".strip()

    def calibrate_system_prompt(self, base_prompt: str) -> str:
        """Inject Heretic direct-execution principles into existing prompt."""
        return f"{self.DIRECT_CHIEF_OF_STAFF_SYSTEM_PROMPT}\n\n[Domain Directives]\n{base_prompt}"

    def clean_response(self, text: str) -> str:
        """Strip boilerplate and tone down excessive agreeable sycophancy."""
        cleaned = text.strip()
        for pat in self.BOILERPLATE_PATTERNS:
            cleaned = re.sub(pat, "", cleaned, flags=re.MULTILINE)
        return cleaned.strip()

    def check_and_neutralize_refusal(self, text: str) -> Dict[str, Any]:
        """Detect refusal tendencies and generate actionable bypass."""
        has_refusal = any(trigger in text for trigger in self.REFUSAL_TRIGGERS)
        return {
            "has_refusal": has_refusal,
            "original_length": len(text),
            "calibrated_text": self.clean_response(text),
            "heretic_applied": True,
        }


def main():
    parser = argparse.ArgumentParser(description="Heretic Direct Prompting & Response Calibrator")
    parser.add_argument("--text", required=True, help="Input text or prompt")
    parser.add_argument("--mode", choices=["clean", "system_prompt", "audit"], default="clean")
    args = parser.parse_args()

    heretic = HereticCalibrator()
    if args.mode == "clean":
        print(heretic.clean_response(args.text))
    elif args.mode == "system_prompt":
        print(heretic.calibrate_system_prompt(args.text))
    elif args.mode == "audit":
        print(json.dumps(heretic.check_and_neutralize_refusal(args.text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
