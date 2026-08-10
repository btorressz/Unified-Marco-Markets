import json
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.config import REDIS_PUBSUB_RETRY_S
from backend.core.event_bus import CHANNEL
from backend.core.redis_runtime import get_redis_runtime

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_connected_clients: set[WebSocket] = set()


async def _get_state_snapshot() -> dict:
    from backend.core.state_store import StateStore
    store = StateStore()
    snapshot = {
        "type": "snapshot",
        "ts": datetime.now(timezone.utc).isoformat(),
        "message": "Connected to Tariff Risk Desk live feed",
    }
    try:
        throttle = store.get_risk_throttle()
        if throttle:
            snapshot["risk_throttle"] = throttle
        idx = store.get_snapshot("index:latest")
        if idx:
            snapshot["index"] = idx
    except Exception:
        pass
    return snapshot


async def _redis_listener(ws: WebSocket):
    runtime = get_redis_runtime()
    while True:
        pubsub = None
        try:
            pubsub = runtime.create_async_pubsub()
            await pubsub.subscribe(runtime.channel(CHANNEL))
            logger.info("WebSocket subscribed to %s", runtime.channel(CHANNEL))

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = message["data"]
                        if isinstance(data, str):
                            event = json.loads(data)
                        else:
                            event = {"data": str(data)}
                        await ws.send_json(event)
                    except WebSocketDisconnect:
                        return
                    except Exception:
                        logger.debug("Failed to forward event to WS client")
                        return
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            runtime.mark_failure(exc)
            logger.debug(
                "Redis pubsub unavailable, retrying in %.1fs",
                REDIS_PUBSUB_RETRY_S,
            )
            await asyncio.sleep(REDIS_PUBSUB_RETRY_S)
        finally:
            await runtime.close_pubsub(pubsub, CHANNEL)


async def _heartbeat(ws: WebSocket):
    while True:
        try:
            await asyncio.sleep(15)
            await ws.send_json({"type": "heartbeat", "ts": datetime.now(timezone.utc).isoformat()})
        except Exception:
            return


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    await ws.accept()
    _connected_clients.add(ws)
    logger.info("WebSocket client connected, total=%d", len(_connected_clients))

    listener_task = None
    heartbeat_task = None
    try:
        snapshot = await _get_state_snapshot()
        await ws.send_json(snapshot)

        listener_task = asyncio.create_task(_redis_listener(ws))
        heartbeat_task = asyncio.create_task(_heartbeat(ws))

        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong", "ts": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("WebSocket error", exc_info=True)
    finally:
        if listener_task:
            listener_task.cancel()
        if heartbeat_task:
            heartbeat_task.cancel()
        _connected_clients.discard(ws)
        logger.info("WebSocket client disconnected, total=%d", len(_connected_clients))
