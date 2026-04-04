"""
WebSocket streaming API endpoints
"""

import json
import logging
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.dependencies import (
    get_stream_service,
    get_pose_service,
    require_auth,
    require_websocket_auth_if_enabled,
)
from src.api.websocket.connection_manager import connection_manager
from src.services.stream_service import StreamService
from src.services.pose_service import PoseService
from src.services.runtime_uptime import utc_now

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response models
class StreamSubscriptionRequest(BaseModel):
    """Request model for stream subscription."""
    
    zone_ids: Optional[List[str]] = Field(
        default=None,
        description="Zones to subscribe to (all zones if not specified)"
    )
    stream_types: List[str] = Field(
        default=["pose_data"],
        description="Types of data to stream"
    )
    min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for streaming"
    )
    max_fps: int = Field(
        default=30,
        ge=1,
        le=60,
        description="Maximum frames per second"
    )
    include_metadata: bool = Field(
        default=True,
        description="Include metadata in stream"
    )


class StreamStatus(BaseModel):
    """Stream status model."""
    
    status: str = Field(..., description="Runtime status (healthy, inactive, unhealthy)")
    message: Optional[str] = Field(default=None, description="Human-readable runtime status detail")
    is_active: bool = Field(..., description="Whether streaming is active")
    connected_clients: int = Field(..., description="Number of connected clients")
    streams: List[Dict[str, Any]] = Field(..., description="Active streams")
    uptime_seconds: float = Field(..., description="Stream uptime in seconds")


# WebSocket endpoints
@router.websocket("/pose")
async def websocket_pose_stream(
    websocket: WebSocket,
    zone_ids: Optional[str] = Query(None, description="Comma-separated zone IDs"),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0),
    max_fps: int = Query(30, ge=1, le=60),
    token: Optional[str] = Query(None, description="Authentication token")
):
    """WebSocket endpoint for real-time pose data streaming."""
    client_id = None
    pose_service = get_pose_service()
    
    try:
        # Accept WebSocket connection
        await websocket.accept()
        if pose_service.is_mock_only_api_surface():
            await websocket.send_json({
                "type": "error",
                "message": pose_service.get_mock_only_reason(),
                "error": "pose_api_mock_only",
                "mock_only_api_surface": True,
                "live_signal_available": False,
            })
            await websocket.close(code=1013)
            return
        
        # Check authentication if enabled
        await require_websocket_auth_if_enabled(token)
        
        # Parse zone IDs
        zone_list = None
        if zone_ids:
            zone_list = [zone.strip() for zone in zone_ids.split(",") if zone.strip()]
        
        # Register client with connection manager
        client_id = await connection_manager.connect(
            websocket=websocket,
            stream_type="pose",
            zone_ids=zone_list,
            min_confidence=min_confidence,
            max_fps=max_fps
        )
        
        logger.info(f"WebSocket client {client_id} connected for pose streaming")
        
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connection_established",
            "client_id": client_id,
            "timestamp": utc_now().isoformat(),
            "config": {
                "zone_ids": zone_list,
                "min_confidence": min_confidence,
                "max_fps": max_fps
            }
        })
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for client messages (ping, config updates, etc.)
                message = await websocket.receive_text()
                data = json.loads(message)
                
                await handle_websocket_message(client_id, data, websocket)
                
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format"
                })
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Internal server error"
                })
    
    except HTTPException as exc:
        await websocket.send_json({
            "type": "error",
            "message": exc.detail,
        })
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        logger.info(f"WebSocket client {client_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if client_id:
            await connection_manager.disconnect(client_id)


@router.websocket("/events")
async def websocket_events_stream(
    websocket: WebSocket,
    event_types: Optional[str] = Query(None, description="Comma-separated event types"),
    zone_ids: Optional[str] = Query(None, description="Comma-separated zone IDs"),
    token: Optional[str] = Query(None, description="Authentication token")
):
    """WebSocket endpoint for real-time event streaming."""
    client_id = None
    
    try:
        await websocket.accept()
        
        await require_websocket_auth_if_enabled(token)
        
        # Parse parameters
        event_list = None
        if event_types:
            event_list = [event.strip() for event in event_types.split(",") if event.strip()]
        
        zone_list = None
        if zone_ids:
            zone_list = [zone.strip() for zone in zone_ids.split(",") if zone.strip()]
        
        # Register client
        client_id = await connection_manager.connect(
            websocket=websocket,
            stream_type="events",
            zone_ids=zone_list,
            event_types=event_list
        )
        
        logger.info(f"WebSocket client {client_id} connected for event streaming")
        
        # Send confirmation
        await websocket.send_json({
            "type": "connection_established",
            "client_id": client_id,
            "timestamp": utc_now().isoformat(),
            "config": {
                "event_types": event_list,
                "zone_ids": zone_list
            }
        })
        
        # Handle messages
        while True:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)
                await handle_websocket_message(client_id, data, websocket)
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in events WebSocket: {e}")
    
    except HTTPException as exc:
        await websocket.send_json({
            "type": "error",
            "message": exc.detail,
        })
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        logger.info(f"Events WebSocket client {client_id} disconnected")
    except Exception as e:
        logger.error(f"Events WebSocket error: {e}")
    finally:
        if client_id:
            await connection_manager.disconnect(client_id)


async def handle_websocket_message(client_id: str, data: Dict[str, Any], websocket: WebSocket):
    """Handle incoming WebSocket messages."""
    message_type = data.get("type")
    
    if message_type == "ping":
        await websocket.send_json({
            "type": "pong",
            "timestamp": utc_now().isoformat()
        })
    
    elif message_type == "update_config":
        # Update client configuration
        config = data.get("config", {})
        await connection_manager.update_client_config(client_id, config)
        
        await websocket.send_json({
            "type": "config_updated",
            "timestamp": utc_now().isoformat(),
            "config": config
        })
    
    elif message_type == "get_status":
        # Send current status
        status = await connection_manager.get_client_status(client_id)
        await websocket.send_json({
            "type": "status",
            "timestamp": utc_now().isoformat(),
            "status": status
        })
    
    else:
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {message_type}"
        })


# HTTP endpoints for stream management
@router.get("/status", response_model=StreamStatus)
async def get_stream_status(
    stream_service: StreamService = Depends(get_stream_service)
):
    """Get current streaming status."""
    try:
        status = await stream_service.get_status()
        connections = await connection_manager.get_connection_stats()
        
        return StreamStatus(
            status=status.get("status", "unknown"),
            message=status.get("message"),
            is_active=status.get("running", False),
            connected_clients=connections.get("total_clients", status["connections"]["active"]),
            streams=[{
                "type": "pose_stream",
                "active": status.get("running", False),
                "buffer_size": status["buffers"]["pose_buffer_size"]
            }],
            uptime_seconds=float(status.get("uptime_seconds", 0.0))
        )
        
    except Exception as e:
        logger.error(f"Error getting stream status: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get stream status: {str(e)}"
        )


@router.post("/start")
async def start_streaming(
    stream_service: StreamService = Depends(get_stream_service),
    current_user: Dict = Depends(require_auth)
):
    """Start the streaming service."""
    try:
        logger.info(f"Starting streaming service by user: {current_user['id']}")
        
        if stream_service.is_active:
            return JSONResponse(
                status_code=200,
                content={
                    "message": "Streaming service is already active",
                    "timestamp": utc_now().isoformat(),
                }
            )
        
        await stream_service.start()
        
        return {
            "message": "Streaming service started successfully",
            "timestamp": utc_now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error starting streaming: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start streaming: {str(e)}"
        )


@router.post("/stop")
async def stop_streaming(
    stream_service: StreamService = Depends(get_stream_service),
    current_user: Dict = Depends(require_auth)
):
    """Stop the streaming service."""
    try:
        logger.info(f"Stopping streaming service by user: {current_user['id']}")

        was_active = stream_service.is_active
        if was_active:
            await stream_service.stop()
        await connection_manager.disconnect_all()

        if not was_active:
            return JSONResponse(
                status_code=200,
                content={
                    "message": "Streaming service is already inactive",
                    "timestamp": utc_now().isoformat(),
                },
            )

        return {
            "message": "Streaming service stopped successfully",
            "timestamp": utc_now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error stopping streaming: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop streaming: {str(e)}"
        )


@router.get("/clients")
async def get_connected_clients(
    current_user: Dict = Depends(require_auth)
):
    """Get list of connected WebSocket clients."""
    try:
        clients = await connection_manager.get_connected_clients()
        
        return {
            "total_clients": len(clients),
            "clients": clients,
            "timestamp": utc_now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting connected clients: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get connected clients: {str(e)}"
        )


@router.delete("/clients/{client_id}")
async def disconnect_client(
    client_id: str,
    current_user: Dict = Depends(require_auth)
):
    """Disconnect a specific WebSocket client."""
    try:
        logger.info(f"Disconnecting client {client_id} by user: {current_user['id']}")
        
        success = await connection_manager.disconnect(client_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Client {client_id} not found"
            )
        
        return {
            "message": f"Client {client_id} disconnected successfully",
            "timestamp": utc_now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disconnecting client: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to disconnect client: {str(e)}"
        )


@router.post("/broadcast")
async def broadcast_message(
    message: Dict[str, Any],
    stream_type: Optional[str] = Query(None, description="Target stream type"),
    zone_ids: Optional[List[str]] = Query(None, description="Target zone IDs"),
    current_user: Dict = Depends(require_auth)
):
    """Broadcast a message to connected WebSocket clients."""
    try:
        logger.info(f"Broadcasting message by user: {current_user['id']}")
        
        # Add metadata to message
        broadcast_data = {
            **message,
            "broadcast_timestamp": utc_now().isoformat(),
            "sender": current_user["id"]
        }
        
        # Broadcast to matching clients
        sent_count = await connection_manager.broadcast(
            data=broadcast_data,
            stream_type=stream_type,
            zone_ids=zone_ids
        )
        
        return {
            "message": "Broadcast sent successfully",
            "recipients": sent_count,
            "timestamp": utc_now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error broadcasting message: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to broadcast message: {str(e)}"
        )


@router.get("/metrics")
async def get_streaming_metrics():
    """Get streaming performance metrics."""
    try:
        metrics = await connection_manager.get_metrics()
        
        return {
            "metrics": metrics,
            "timestamp": utc_now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting streaming metrics: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get streaming metrics: {str(e)}"
        )
