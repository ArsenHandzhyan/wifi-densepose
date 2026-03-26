"""
Hardware interface service for WiFi-DensePose API
"""

import logging
import asyncio
import math
import shutil
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from src.config.settings import Settings
from src.config.domains import DomainConfig
from src.core.router_interface import RouterInterface

logger = logging.getLogger(__name__)


class HardwareService:
    """Service for hardware interface operations."""
    
    def __init__(self, settings: Settings, domain_config: DomainConfig):
        """Initialize hardware service."""
        self.settings = settings
        self.domain_config = domain_config
        self.logger = logging.getLogger(__name__)
        
        # Router interfaces
        self.router_interfaces: Dict[str, RouterInterface] = {}
        
        # Service state
        self.is_running = False
        self.last_error = None
        
        # Data collection statistics
        self.stats = {
            "total_samples": 0,
            "successful_samples": 0,
            "failed_samples": 0,
            "average_sample_rate": 0.0,
            "last_sample_time": None,
            "connected_routers": 0
        }
        
        # Background tasks
        self.collection_task = None
        self.monitoring_task = None
        
        # Data buffers
        self.recent_samples = []
        self.max_recent_samples = 1000

    def _live_collection_available(self) -> bool:
        """True when at least one router exposes a real collector backend."""
        return any(getattr(interface, "live_collection_available", False) for interface in self.router_interfaces.values())

    def _collection_mode(self) -> str:
        if self.settings.mock_hardware:
            return "mock"
        if self._live_collection_available():
            return "live"
        return "disabled_unimplemented"
    
    async def initialize(self):
        """Initialize the hardware service."""
        await self.start()
    
    async def start(self):
        """Start the hardware service."""
        if self.is_running:
            return
        
        try:
            self.logger.info("Starting hardware service...")
            
            # Initialize router interfaces
            await self._initialize_routers()
            
            self.is_running = True
            
            # Start background tasks
            if not self.settings.mock_hardware and self._live_collection_available():
                self.collection_task = asyncio.create_task(self._data_collection_loop())
            elif not self.settings.mock_hardware:
                self.logger.warning(
                    "Hardware service started without collection loop: live CSI backend is not implemented in RouterInterface"
                )
            
            self.monitoring_task = asyncio.create_task(self._monitoring_loop())
            
            self.logger.info("Hardware service started successfully")
            
        except Exception as e:
            self.last_error = str(e)
            self.logger.error(f"Failed to start hardware service: {e}")
            raise
    
    async def stop(self):
        """Stop the hardware service."""
        self.is_running = False
        
        # Cancel background tasks
        if self.collection_task:
            self.collection_task.cancel()
            try:
                await self.collection_task
            except asyncio.CancelledError:
                pass
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect from routers
        await self._disconnect_routers()
        
        self.logger.info("Hardware service stopped")
    
    async def _initialize_routers(self):
        """Initialize router interfaces."""
        try:
            # Get router configurations from domain config
            routers = self.domain_config.get_all_routers()
            
            for router_config in routers:
                if not router_config.enabled:
                    continue
                
                router_id = router_config.router_id
                
                # Create router interface
                router_interface = RouterInterface(
                    router_id=router_id,
                    host=router_config.ip_address,
                    port=22,  # Default SSH port
                    username="admin",  # Default username
                    password="admin",  # Default password
                    interface=router_config.interface,
                    mock_mode=self.settings.mock_hardware
                )
                
                # Connect to router (always connect, even in mock mode)
                await router_interface.connect()
                
                self.router_interfaces[router_id] = router_interface
                self.logger.info(f"Router interface initialized: {router_id}")
            
            self.stats["connected_routers"] = len(self.router_interfaces)
            
            if not self.router_interfaces:
                self.logger.warning("No router interfaces configured")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize routers: {e}")
            raise
    
    async def _disconnect_routers(self):
        """Disconnect from all routers."""
        for router_id, interface in self.router_interfaces.items():
            try:
                await interface.disconnect()
                self.logger.info(f"Disconnected from router: {router_id}")
            except Exception as e:
                self.logger.error(f"Error disconnecting from router {router_id}: {e}")
        
        self.router_interfaces.clear()
        self.stats["connected_routers"] = 0
    
    async def _data_collection_loop(self):
        """Background loop for data collection."""
        try:
            while self.is_running:
                start_time = time.time()
                
                # Collect data from all routers
                await self._collect_data_from_routers()
                
                # Calculate sleep time to maintain polling interval
                elapsed = time.time() - start_time
                sleep_time = max(0, self.settings.hardware_polling_interval - elapsed)
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                
        except asyncio.CancelledError:
            self.logger.info("Data collection loop cancelled")
        except Exception as e:
            self.logger.error(f"Error in data collection loop: {e}")
            self.last_error = str(e)
    
    async def _monitoring_loop(self):
        """Background loop for hardware monitoring."""
        try:
            while self.is_running:
                # Monitor router connections
                await self._monitor_router_health()
                
                # Update statistics
                self._update_sample_rate_stats()
                
                # Wait before next check
                await asyncio.sleep(30)  # Check every 30 seconds
                
        except asyncio.CancelledError:
            self.logger.info("Monitoring loop cancelled")
        except Exception as e:
            self.logger.error(f"Error in monitoring loop: {e}")
    
    async def _collect_data_from_routers(self):
        """Collect CSI data from all connected routers."""
        for router_id, interface in self.router_interfaces.items():
            try:
                # Get CSI data from router
                csi_data = await interface.get_csi_data()
                
                if csi_data is not None:
                    # Process the collected data
                    await self._process_collected_data(router_id, csi_data)
                    
                    self.stats["successful_samples"] += 1
                    self.stats["last_sample_time"] = datetime.now().isoformat()
                else:
                    self.stats["failed_samples"] += 1
                
                self.stats["total_samples"] += 1
                
            except Exception as e:
                self.logger.error(f"Error collecting data from router {router_id}: {e}")
                self.stats["failed_samples"] += 1
                self.stats["total_samples"] += 1
    
    async def _process_collected_data(self, router_id: str, csi_data: np.ndarray):
        """Process collected CSI data."""
        try:
            # Create sample metadata
            metadata = {
                "router_id": router_id,
                "timestamp": datetime.now().isoformat(),
                "sample_rate": self.stats["average_sample_rate"],
                "data_shape": csi_data.shape if hasattr(csi_data, 'shape') else None
            }
            
            # Add to recent samples buffer
            sample = {
                "router_id": router_id,
                "timestamp": metadata["timestamp"],
                "data": csi_data,
                "metadata": metadata
            }
            
            self.recent_samples.append(sample)
            
            # Maintain buffer size
            if len(self.recent_samples) > self.max_recent_samples:
                self.recent_samples.pop(0)
            
            # Notify other services (this would typically be done through an event system)
            # For now, we'll just log the data collection
            self.logger.debug(f"Collected CSI data from {router_id}: shape {csi_data.shape if hasattr(csi_data, 'shape') else 'unknown'}")
            
        except Exception as e:
            self.logger.error(f"Error processing collected data: {e}")
    
    async def _monitor_router_health(self):
        """Monitor health of router connections."""
        healthy_routers = 0
        
        for router_id, interface in self.router_interfaces.items():
            try:
                is_healthy = await interface.check_health()
                
                if is_healthy:
                    healthy_routers += 1
                else:
                    self.logger.warning(f"Router {router_id} is unhealthy")
                    
                    # Try to reconnect if not in mock mode
                    if not self.settings.mock_hardware:
                        try:
                            await interface.reconnect()
                            self.logger.info(f"Reconnected to router {router_id}")
                        except Exception as e:
                            self.logger.error(f"Failed to reconnect to router {router_id}: {e}")
                
            except Exception as e:
                self.logger.error(f"Error checking health of router {router_id}: {e}")
        
        self.stats["connected_routers"] = healthy_routers
    
    def _update_sample_rate_stats(self):
        """Update sample rate statistics."""
        if len(self.recent_samples) < 2:
            return
        
        # Calculate sample rate from recent samples
        recent_count = min(100, len(self.recent_samples))
        recent_samples = self.recent_samples[-recent_count:]
        
        if len(recent_samples) >= 2:
            # Calculate time differences
            time_diffs = []
            for i in range(1, len(recent_samples)):
                try:
                    t1 = datetime.fromisoformat(recent_samples[i-1]["timestamp"])
                    t2 = datetime.fromisoformat(recent_samples[i]["timestamp"])
                    diff = (t2 - t1).total_seconds()
                    if diff > 0:
                        time_diffs.append(diff)
                except Exception:
                    continue
            
            if time_diffs:
                avg_interval = sum(time_diffs) / len(time_diffs)
                self.stats["average_sample_rate"] = 1.0 / avg_interval if avg_interval > 0 else 0.0
    
    async def get_router_status(self, router_id: str) -> Dict[str, Any]:
        """Get status of a specific router."""
        if router_id not in self.router_interfaces:
            raise ValueError(f"Router {router_id} not found")
        
        interface = self.router_interfaces[router_id]
        
        try:
            is_healthy = await interface.check_health()
            status = await interface.get_status()
            
            return {
                "router_id": router_id,
                "healthy": is_healthy,
                "connected": status.get("connected", False),
                "live_collection_available": status.get("live_collection_available", False),
                "collection_backend": status.get("collection_backend"),
                "last_data_time": status.get("last_data_time"),
                "error_count": status.get("error_count", 0),
                "configuration": status.get("configuration", {})
            }
            
        except Exception as e:
            return {
                "router_id": router_id,
                "healthy": False,
                "connected": False,
                "error": str(e)
            }
    
    async def get_all_router_status(self) -> List[Dict[str, Any]]:
        """Get status of all routers."""
        statuses = []
        
        for router_id in self.router_interfaces:
            try:
                status = await self.get_router_status(router_id)
                statuses.append(status)
            except Exception as e:
                statuses.append({
                    "router_id": router_id,
                    "healthy": False,
                    "error": str(e)
                })
        
        return statuses
    
    async def get_recent_data(self, router_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent CSI data samples."""
        samples = self.recent_samples[-limit:] if limit else self.recent_samples
        
        if router_id:
            samples = [s for s in samples if s["router_id"] == router_id]
        
        # Convert numpy arrays to lists for JSON serialization
        result = []
        for sample in samples:
            sample_copy = sample.copy()
            if isinstance(sample_copy["data"], np.ndarray):
                sample_copy["data"] = sample_copy["data"].tolist()
            result.append(sample_copy)
        
        return result
    
    async def get_status(self) -> Dict[str, Any]:
        """Get service status."""
        collection_mode = self._collection_mode()
        if self.is_running and not self.last_error:
            status = "healthy" if collection_mode in {"mock", "live"} else "degraded"
        else:
            status = "unhealthy"
        return {
            "status": status,
            "running": self.is_running,
            "last_error": self.last_error,
            "live_csi_collection_available": self._live_collection_available(),
            "collection_backend": collection_mode,
            "collection_loop_active": bool(self.collection_task and not self.collection_task.done()),
            "statistics": self.stats.copy(),
            "configuration": {
                "mock_hardware": self.settings.mock_hardware,
                "wifi_interface": self.settings.wifi_interface,
                "polling_interval": self.settings.hardware_polling_interval,
                "buffer_size": self.settings.csi_buffer_size
            },
            "routers": await self.get_all_router_status()
        }
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get service metrics."""
        total_samples = self.stats["total_samples"]
        success_rate = self.stats["successful_samples"] / max(1, total_samples)
        
        return {
            "hardware_service": {
                "total_samples": total_samples,
                "successful_samples": self.stats["successful_samples"],
                "failed_samples": self.stats["failed_samples"],
                "success_rate": success_rate,
                "average_sample_rate": self.stats["average_sample_rate"],
                "connected_routers": self.stats["connected_routers"],
                "last_sample_time": self.stats["last_sample_time"]
            }
        }
    
    async def reset(self):
        """Reset service state."""
        self.stats = {
            "total_samples": 0,
            "successful_samples": 0,
            "failed_samples": 0,
            "average_sample_rate": 0.0,
            "last_sample_time": None,
            "connected_routers": len(self.router_interfaces)
        }
        
        self.recent_samples.clear()
        self.last_error = None
        
        self.logger.info("Hardware service reset")
    
    async def trigger_manual_collection(self, router_id: Optional[str] = None) -> Dict[str, Any]:
        """Manually trigger data collection."""
        if not self.is_running:
            raise RuntimeError("Hardware service is not running")
        
        results = {}
        
        if router_id:
            # Collect from specific router
            if router_id not in self.router_interfaces:
                raise ValueError(f"Router {router_id} not found")
            
            interface = self.router_interfaces[router_id]
            try:
                csi_data = await interface.get_csi_data()
                if csi_data is not None:
                    await self._process_collected_data(router_id, csi_data)
                    results[router_id] = {"success": True, "data_shape": csi_data.shape if hasattr(csi_data, 'shape') else None}
                else:
                    results[router_id] = {"success": False, "error": "No data received"}
            except Exception as e:
                results[router_id] = {"success": False, "error": str(e)}
        else:
            # Collect from all routers
            await self._collect_data_from_routers()
            results = {"message": "Manual collection triggered for all routers"}
        
        return results

    async def record_live_csi_capture(
        self,
        *,
        label: str,
        duration_sec: float,
        out_dir: str | None = None,
    ) -> Dict[str, Any]:
        """Capture one short live CSI clip via the canonical recording service."""
        from src.services.csi_prediction_service import csi_prediction_service
        from src.services.csi_recording_service import csi_recording_service

        if not csi_prediction_service._running:
            if not csi_prediction_service.binary_model:
                if not csi_prediction_service.load_model():
                    raise RuntimeError("Failed to load runtime CSI model for live capture")
            try:
                await csi_prediction_service.start_udp_listener()
                asyncio.create_task(csi_prediction_service.prediction_loop(interval=2.0))
            except OSError as exc:
                if "Address already in use" not in str(exc):
                    raise RuntimeError(f"Failed to start CSI UDP listener: {exc}") from exc

        chunk_sec = max(1, int(math.ceil(float(duration_sec))))
        started = await csi_recording_service.start_recording(
            label=label,
            chunk_sec=chunk_sec,
            with_video=False,
            voice_prompt=False,
            skip_preflight=False,
        )
        if not started.get("ok"):
            raise RuntimeError(str(started.get("error") or "Failed to start live CSI capture"))

        try:
            await asyncio.sleep(float(duration_sec))
        finally:
            stopped = await csi_recording_service.stop_recording(
                voice_prompt=False,
                reason="training_live_csi_capture",
            )

        if not stopped.get("ok"):
            raise RuntimeError(str(stopped.get("error") or "Failed to stop live CSI capture"))

        chunk = dict(stopped.get("last_chunk") or {})
        data_path = str(chunk.get("data_path") or "").strip()
        summary_path = str(chunk.get("summary_path") or "").strip()
        if not data_path or not summary_path:
            raise RuntimeError("Live CSI capture completed without data_path/summary_path")

        if out_dir:
            target_dir = Path(out_dir).expanduser().resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            copied_data = target_dir / Path(data_path).name
            copied_summary = target_dir / Path(summary_path).name
            shutil.copy2(data_path, copied_data)
            shutil.copy2(summary_path, copied_summary)
            data_path = str(copied_data)
            summary_path = str(copied_summary)

        return {
            "label": chunk.get("label") or label,
            "data_path": data_path,
            "summary_path": summary_path,
            "duration_sec": chunk.get("duration_sec"),
            "packet_count": chunk.get("packet_count"),
            "nodes_active": chunk.get("nodes_active"),
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        try:
            collection_mode = self._collection_mode()
            if self.is_running and not self.last_error:
                status = "healthy" if collection_mode in {"mock", "live"} else "degraded"
            else:
                status = "unhealthy"
            
            # Check router health
            healthy_routers = 0
            total_routers = len(self.router_interfaces)
            
            for router_id, interface in self.router_interfaces.items():
                try:
                    if await interface.check_health():
                        healthy_routers += 1
                except Exception:
                    pass
            
            return {
                "status": status,
                "message": self.last_error if self.last_error else (
                    "Hardware service is running in mock mode"
                    if collection_mode == "mock"
                    else "Hardware service is running with live collection enabled"
                    if collection_mode == "live"
                    else "Hardware service is up, but real CSI collection is not implemented in RouterInterface"
                ),
                "connected_routers": f"{healthy_routers}/{total_routers}",
                "metrics": {
                    "total_samples": self.stats["total_samples"],
                    "success_rate": (
                        self.stats["successful_samples"] / max(1, self.stats["total_samples"])
                    ),
                    "average_sample_rate": self.stats["average_sample_rate"]
                }
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Health check failed: {str(e)}"
            }
    
    async def is_ready(self) -> bool:
        """Check if service is ready."""
        return self.is_running and len(self.router_interfaces) > 0 and (
            self.settings.mock_hardware or self._live_collection_available()
        )
