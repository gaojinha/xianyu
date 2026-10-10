"""本地 AI 网关：让项目直接复用本机 opencode 的模型，无需再配第三方 Key。

需求来源：项目原本要配第三方（或中转）API Key 才能启用 AI 回复。高哥要求直接
复用他本机已有的模型能力（``deepseek-v4.1-flash``，跑在 opencode serve 上）。

opencode serve 暴露的是非标准的会话式 API（建会话 → 发消息 → 取回复），而
``ai_reply_engine`` 走的是标准 OpenAI 协议。这里做一层翻译：对外提供
``/v1/models`` 与 ``/v1/chat/completions``，对内转成 opencode 的会话调用。

设计约束（opencode 是钉钉对话的命脉，务必遵守）：
- 只绑定 127.0.0.1，不对外暴露；
- 只调用 opencode 的 HTTP API，不修改、不重启它；
- 全程超时保护 + 并发上限；失败降级为模板回复，绝不反噬主进程或钉钉。
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

# opencode serve 地址与要用的模型（可用环境变量覆盖）
OPENCODE_BASE = os.getenv("LOCAL_AI_GATEWAY_URL", "http://127.0.0.1:4096").rstrip("/")
OPENCODE_PROVIDER = os.getenv("LOCAL_AI_GATEWAY_PROVIDER", "opencode-go")
OPENCODE_MODEL = os.getenv("LOCAL_AI_GATEWAY_MODEL", "deepseek-v4.1-flash")

# 调用失败时的兜底回复，保证买家至少收到一句话，而不是自动回复直接中断
TEMPLATE_REPLY = os.getenv(
    "LOCAL_AI_GATEWAY_FALLBACK",
    "您好，消息已收到，稍后尽快为您回复～",
)

REQUEST_TIMEOUT = int(os.getenv("LOCAL_AI_GATEWAY_TIMEOUT", "90"))
CONCURRENCY = max(1, int(os.getenv("LOCAL_AI_GATEWAY_CONCURRENCY", "2")))

_cred_cache: Dict[str, Any] = {"username": None, "password": None, "loaded": False}


def _scan_proc_for_credentials() -> Optional[Tuple[str, str]]:
    """从 opencode serve 进程的环境变量里取 Basic 认证凭据。

    密码不落盘、不写配置，随进程在内存里；opencode 重启换密码后，下一次扫描会
    自动取到新的。拿不到就返回 None（调用方会走降级回复）。
    """
    try:
        pids = os.listdir("/proc")
    except Exception:
        return None

    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read()
        except Exception:
            continue
        if b"opencode" not in cmdline or b"serve" not in cmdline:
            continue
        try:
            env = open(f"/proc/{pid}/environ", "rb").read().decode(errors="replace")
        except Exception:
            continue
        pw = re.search(r"OPENCODE_SERVER_PASSWORD=([^\x00]+)", env)
        if not pw:
            continue
        um = re.search(r"OPENCODE_SERVER_USERNAME=([^\x00]+)", env)
        return (um.group(1) if um else "opencode"), pw.group(1)
    return None


def _opencode_credentials() -> Optional[Tuple[str, str]]:
    """取 opencode 凭据：环境变量优先，其次扫描进程，结果缓存。"""
    if _cred_cache.get("password"):
        return str(_cred_cache["username"] or "opencode"), str(_cred_cache["password"] or "")

    username = os.getenv("OPENCODE_SERVER_USERNAME") or "opencode"
    password = os.getenv("OPENCODE_SERVER_PASSWORD")
    if not password:
        found = _scan_proc_for_credentials()
        if found:
            username, password = found

    if password:
        _cred_cache["username"] = username
        _cred_cache["password"] = password
        _cred_cache["loaded"] = True
        return username, password

    _cred_cache["loaded"] = True
    return None


def _flatten_messages(messages: List[Dict[str, Any]]) -> Tuple[str, str]:
    """把 OpenAI 的 messages 拆成 (system, 对话文本)。

    opencode 的消息接口只收一段文本 + 可选的 system。这里把 system 单独抽出，
    其余按角色加"买家/卖家"前缀拼成一段，尽量保留上下文语义。
    """
    system_parts: List[str] = []
    convo: List[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        content = str(content or "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            convo.append(f"卖家：{content}")
        else:
            convo.append(f"买家：{content}")
    return "\n".join(system_parts).strip(), "\n".join(convo).strip()


def _extract_text(message: Dict[str, Any]) -> str:
    """从 opencode 的消息响应里取出正文。"""
    parts = message.get("parts") or []
    chunks = [
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError("opencode 未返回文本内容")
    return text


async def _ask_opencode(user_text: str, system_text: str, model_id: str) -> str:
    """建会话 → 发消息 → 取回复 → 删会话。用完即删，避免污染会话列表。"""
    creds = _opencode_credentials()
    if not creds:
        raise RuntimeError("未找到 opencode serve 凭据")
    username, password = creds
    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode(),
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    body: Dict[str, Any] = {
        "model": {"providerID": OPENCODE_PROVIDER, "modelID": model_id or OPENCODE_MODEL},
        "parts": [{"type": "text", "text": user_text}],
    }
    if system_text:
        body["system"] = system_text

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        async with session.post(f"{OPENCODE_BASE}/session", json={}) as resp:
            created = await resp.json()
        sid = created.get("id") if isinstance(created, dict) else None
        if not sid:
            raise RuntimeError("创建 opencode 会话失败")

        try:
            async with session.post(f"{OPENCODE_BASE}/session/{sid}/message", json=body) as resp:
                message = await resp.json()
            return _extract_text(message if isinstance(message, dict) else {})
        finally:
            try:
                async with session.delete(f"{OPENCODE_BASE}/session/{sid}") as resp:
                    await resp.read()
            except Exception:
                pass


def _openai_response(text: str, model: str) -> Dict[str, Any]:
    """组装标准 OpenAI chat.completion 响应，供 ai_reply_engine 原样解析。"""
    return {
        "id": "chatcmpl-local-" + uuid.uuid4().hex[:16],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or OPENCODE_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.limiter = asyncio.Semaphore(CONCURRENCY)
    logger.info(
        f"本地 AI 网关就绪: model={OPENCODE_MODEL}, provider={OPENCODE_PROVIDER}, "
        f"并发上限={CONCURRENCY}, opencode={OPENCODE_BASE}"
    )
    yield


app = FastAPI(title="xianyu-local-ai-gateway", lifespan=_lifespan)


@app.get("/v1/models")
async def list_models() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": OPENCODE_MODEL, "object": "model", "owned_by": "local-opencode"}],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    """OpenAI 兼容入口：把请求翻译给 opencode，失败则回落模板回复。"""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    model = payload.get("model") or OPENCODE_MODEL
    messages = payload.get("messages") or []
    system_text, user_text = _flatten_messages(messages)

    if not user_text:
        return JSONResponse(_openai_response(TEMPLATE_REPLY, model))

    try:
        async with request.app.state.limiter:
            text = await _ask_opencode(user_text, system_text, model)
    except Exception as exc:
        logger.warning(f"本地 AI 网关调用失败，降级模板回复: {exc}")
        text = TEMPLATE_REPLY

    return JSONResponse(_openai_response(text, model))
