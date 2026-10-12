"""物流报价文本解析路由。

卖家拿到的快递报价常是聊天里的一段非结构化文本（"顺丰 广东 首重12 续重3"），
本路由把它解析成结构化条目，供发货决策和成本估算使用。
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.services.notification_sender import (
    NotificationSendError,
    NotificationSendTimeout,
    NotificationSender,
)

# 常见快递公司关键词，命中即作为承运方；未命中时保留原文由调用方自行判断
_CARRIER_KEYWORDS = (
    "顺丰", "中通", "圆通", "申通", "韵达", "极兔", "京东", "德邦",
    "邮政", "EMS", "ems", "百世", "天天", "宅急送", "丰网", "菜鸟",
)

_FIRST_WEIGHT_RE = re.compile(r"首重[^\d]{0,6}(\d+(?:\.\d+)?)")
_ADDITIONAL_WEIGHT_RE = re.compile(r"续重[^\d]{0,6}(\d+(?:\.\d+)?)")


class QuoteParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    cookie_id: str | None = Field(default=None, min_length=1, max_length=128)


async def _notify_quote_parse_failure(
    db_manager: Any,
    *,
    cookie_id: str,
    user_id: int,
) -> None:
    """Notify the owner about an unparseable quote without exposing its source text."""
    notifications = db_manager.get_account_notifications(
        cookie_id, user_id=user_id, event_type="logistics_quote"
    ) or []
    if not notifications:
        return

    sender = NotificationSender()
    message = (
        "物流报价文本未能识别出有效的首重/续重价格，请检查报价内容并转人工核对。"
    )
    for notification in notifications:
        if not notification.get("enabled", True):
            continue
        request_id = secrets.token_hex(6)
        try:
            audit_id = db_manager.add_notification_delivery_log(
                cookie_id=cookie_id,
                channel_id=notification["channel_id"],
                rule_id=notification.get("id"),
                event_type="logistics_quote",
                source="runtime",
                request_id=request_id,
                status="unknown",
            )
        except Exception as error:
            logger.error(
                "无法创建物流报价通知审计记录，已跳过发送: "
                f"request_id={request_id} error={error}"
            )
            continue

        try:
            await sender.send(
                notification.get("channel_type", ""),
                notification.get("channel_config", ""),
                message,
                request_id=request_id,
            )
            db_manager.update_notification_delivery_log(
                audit_id, user_id, "success"
            )
        except Exception as error:
            unknown = isinstance(error, NotificationSendTimeout) or (
                isinstance(error, NotificationSendError)
                and error.category in {"network", "timeout"}
            )
            try:
                db_manager.update_notification_delivery_log(
                    audit_id,
                    user_id,
                    "unknown" if unknown else "failed",
                    error_code=getattr(error, "code", "notification_send_failed"),
                    error_summary=getattr(
                        error,
                        "public_message",
                        "通知发送失败，请检查渠道配置和网络",
                    ),
                )
            except Exception as audit_error:
                logger.error(
                    "物流报价通知失败审计记录未能保存: "
                    f"request_id={request_id} error={audit_error}"
                )
            logger.error(
                "物流报价通知发送失败: "
                f"request_id={request_id} status={'unknown' if unknown else 'failed'}"
            )


def parse_quote_line(line: str) -> dict[str, Any] | None:
    """解析单行报价；没有首重/续重价格的行视为无效返回 None。"""
    first_match = _FIRST_WEIGHT_RE.search(line)
    additional_match = _ADDITIONAL_WEIGHT_RE.search(line)
    if not first_match and not additional_match:
        return None

    carrier = next((name for name in _CARRIER_KEYWORDS if name in line), "")

    # 区域是承运方之后、"首重"之前的剩余文本（去掉分隔符）
    region = line
    if carrier:
        region = region.split(carrier, 1)[1]
    region = region.split("首重", 1)[0]
    region = re.sub(r"[:：,，、\s]+", " ", region).strip()

    return {
        "carrier": carrier,
        "region": region,
        "first_weight_price": float(first_match.group(1)) if first_match else None,
        "additional_weight_price": float(additional_match.group(1)) if additional_match else None,
        "raw": line.strip(),
    }


def create_logistics_quote_router(
    get_current_user: Callable[..., dict[str, Any]],
    db_manager: Any,
) -> APIRouter:
    router = APIRouter()

    @router.post("/logistics-quote/parse")
    async def parse_quote(
        request: QuoteParseRequest,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """把多行报价文本解析成结构化条目列表。"""
        if request.cookie_id:
            owner_id = db_manager.get_cookie_owner_user(request.cookie_id)
            if owner_id is None or owner_id != current_user.get("id"):
                raise HTTPException(status_code=404, detail="账号不存在")

        quotes = []
        for line in request.text.splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = parse_quote_line(line)
            if parsed:
                quotes.append(parsed)

        if not quotes:
            if request.cookie_id:
                try:
                    await _notify_quote_parse_failure(
                        db_manager,
                        cookie_id=request.cookie_id,
                        user_id=int(current_user["id"]),
                    )
                except Exception as error:
                    logger.error(f"处理物流报价通知失败: {error}")
            raise HTTPException(
                status_code=422,
                detail="未识别到有效报价行，每行需包含首重或续重价格",
            )
        return {"success": True, "quotes": quotes}

    return router
