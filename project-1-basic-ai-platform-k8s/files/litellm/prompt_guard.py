"""Heuristic prompt-injection guardrail for the LiteLLM gateway.

Every model call passes through the gateway, which makes it the natural
control point (OWASP LLM01). This hook is deliberately a HEURISTIC: a small
regex corpus scores each request, high-confidence patterns block (HTTP 400),
lower-confidence ones are flagged and logged. The point this pass is the
ARCHITECTURE — a pre-call control with structured audit output that the
Month-2 red-team harness can measure (attack success rate before/after).

Wired via config.yaml:
    guardrails:
      - guardrail_name: prompt-injection-heuristic
        litellm_params:
          guardrail: prompt_guard.PromptInjectionGuard
          mode: pre_call
          default_on: true

Every match emits one JSON line to stdout:
    {"event": "prompt_injection_suspect", "key_alias": ..., "model": ...,
     "rules": [...], "score": N, "blocked": bool}
and stamps the verdict into request metadata so it lands in LiteLLM_SpendLogs.
"""

import json
import re
import sys
from typing import Literal, Optional, Union

from fastapi import HTTPException

from litellm.caching.caching import DualCache
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.proxy._types import UserAPIKeyAuth

# (name, weight, pattern) — weight 3 patterns block on their own (score >= BLOCK_THRESHOLD).
_RULES = [
    (
        "ignore-previous-instructions",
        3,
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all|earlier)\b"
            r".{0,40}\b(instruction|prompt|rule|direction|context)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "system-prompt-exfiltration",
        3,
        re.compile(
            r"\b(reveal|show|print|repeat|output|display|tell me)\b.{0,40}\b(system prompt"
            r"|initial prompt|hidden instruction|your instruction|your rules)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "role-override",
        2,
        re.compile(
            r"\b(you are now|act as|pretend to be|new persona|jailbreak|developer mode"
            r"|DAN mode|no restrictions|without any (rules|filters|restrictions))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter-escape",
        2,
        re.compile(
            r"(<\|im_start\|>|<\|im_end\|>|\[/?INST\]|<<SYS>>|</?s>|### (system|instruction))",
            re.IGNORECASE,
        ),
    ),
    (
        "base64-blob",
        1,
        # Long base64 runs are a common smuggling channel for indirect injection.
        re.compile(r"[A-Za-z0-9+/=]{200,}"),
    ),
]

BLOCK_THRESHOLD = 3


class PromptInjectionGuard(CustomGuardrail):
    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: DualCache,
        data: dict,
        call_type: Union[
            Literal["completion"],
            Literal["text_completion"],
            Literal["embeddings"],
            Literal["image_generation"],
            Literal["moderation"],
            Literal["audio_transcription"],
            Literal["pass_through_endpoint"],
            Literal["rerank"],
            Literal["mcp_call"],
        ],
    ) -> Optional[Union[Exception, str, dict]]:
        text = self._extract_text(data)
        if not text:
            return data

        matched = [(name, weight) for name, weight, rx in _RULES if rx.search(text)]
        if not matched:
            return data

        score = sum(w for _, w in matched)
        # Enforcement point: COMPLETIONS. Embedding/rerank calls are flagged
        # (audit line + SpendLogs verdict) but never blocked: embedded text is
        # data, not instructions — legitimate corpora (security books, code)
        # trip the heuristics constantly, and the injection risk only
        # materializes when retrieved content reaches a completion call, which
        # this hook still gates. Found live: ingesting "Black Hat Bash"
        # (2026-09-13).
        enforce = str(call_type) not in ("embeddings", "rerank")
        blocked = enforce and score >= BLOCK_THRESHOLD
        verdict = {
            "event": "prompt_injection_suspect",
            "key_alias": getattr(user_api_key_dict, "key_alias", None),
            "model": data.get("model"),
            "call_type": str(call_type),
            "rules": [n for n, _ in matched],
            "score": score,
            "blocked": blocked,
        }
        # Structured audit line (scraped by the log pipeline; greppable in kubectl logs).
        print(json.dumps(verdict), file=sys.stderr, flush=True)

        # Persist the verdict with the request: metadata lands in LiteLLM_SpendLogs.
        data.setdefault("metadata", {})["prompt_guard"] = verdict

        if blocked:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Blocked by guardrail: prompt-injection-heuristic",
                    "guardrail": "prompt-injection-heuristic",
                    "rules": [n for n, _ in matched],
                },
            )
        return data

    @staticmethod
    def _extract_text(data: dict) -> str:
        parts = []
        for message in data.get("messages") or []:
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):  # multimodal: [{"type":"text",...}]
                parts.extend(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
        inp = data.get("input")
        if isinstance(inp, str):
            parts.append(inp)
        elif isinstance(inp, list):
            parts.extend(p for p in inp if isinstance(p, str))
        return "\n".join(parts)
