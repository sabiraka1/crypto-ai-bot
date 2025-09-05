"""
Orchestrator - Main coordinator of all trading loops and processes.

Responsibilities:
- Manage lifecycle of background loops (eval, exits, reconcile, watchdog, settlement)
- Coordinate trace_id propagation
- Handle pause/resume/stop operations
- Emit orchestration events
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from crypto_ai_bot.core.application import events_topics as EVT
from crypto_ai_bot.core.application.ports import (
    BrokerPort,
    EventBusPort,
    MetricsPort,
    StoragePort,
    DeadMansSwitchPort,
)
from crypto_ai_bot.core.application.use_cases.execute_trade import ExecuteTrade
from crypto_ai_bot.core.application.use_cases.eval_and_execute import EvalAndExecute
from crypto_ai_bot.core.application.use_cases.partial_fills import SettlementService
from crypto_ai_bot.core.application.reconciliation.balances import BalanceReconciliation
from crypto_ai_bot.core.application.reconciliation.positions import PositionReconciliation
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.domain.risk.manager import RiskManager
from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import generate_trace_id

_log = get_logger(__name__)


# ============= TYPES =============

class LoopState(Enum):
    """State of a background loop"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class LoopSpec:
    """Specification for a background loop"""
    name: str
    interval_sec: float
    enabled: bool
    runner: Callable[[], Awaitable[None]]
    task: Optional[asyncio.Task[None]] = None
    state: LoopState = LoopState.IDLE
    last_run: Optional[datetime] = None
    error_count: int = 0
    
    @property
    def is_alive(self) -> bool:
        return self.task is not None and not self.task.done()


class OrchestratorState(Enum):
    """State of the orchestrator"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"


# ============= MAIN ORCHESTRATOR =============

@dataclass
class Orchestrator:
    """
    Main coordinator of all trading processes.
    Manages background loops and coordinates their execution.
    """
    
    # Dependencies (properly typed)
    symbol: str
    storage: StoragePort
    broker: BrokerPort
    event_bus: EventBusPort
    risk_manager: RiskManager
    metrics: MetricsPort
    settings: Settings
    
    # Use cases
    execute_trade: ExecuteTrade
    eval_and_execute: EvalAndExecute
    protective_exits: ProtectiveExits
    health_checker: HealthChecker
    settlement_service: SettlementService
    balance_reconciliation: BalanceReconciliation
    position_reconciliation: PositionReconciliation
    
    # Optional services
    dead_mans_switch: Optional[DeadMansSwitchPort] = None
    
    # Internal state
    _loops: dict[str, LoopSpec] = field(default_factory=dict)
    _state: OrchestratorState = OrchestratorState.IDLE
    _start_time: Optional[datetime] = None
    
    def __post_init__(self) -> None:
        """Initialize loop specifications from settings"""
        self._initialize_loops()
    
    def _initialize_loops(self) -> None:
        """Create loop specifications from settings"""
        s = self.settings
        
        self._loops = {
            "eval": LoopSpec(
                name="eval",
                interval_sec=s.intervals.EVAL,
                enabled=s.EVAL_ENABLED,
                runner=self._eval_loop
            ),
            "exits": LoopSpec(
                name="exits",
                interval_sec=s.intervals.EXITS,
                enabled=s.EXITS_ENABLED,
                runner=self._exits_loop
            ),
            "reconcile": LoopSpec(
                name="reconcile",
                interval_sec=s.intervals.RECONCILE,
                enabled=s.RECONCILE_ENABLED,
                runner=self._reconcile_loop
            ),
            "watchdog": LoopSpec(
                name="watchdog",
                interval_sec=s.intervals.WATCHDOG,
                enabled=s.WATCHDOG_ENABLED,
                runner=self._watchdog_loop
            ),
            "settlement": LoopSpec(
                name="settlement",
                interval_sec=s.intervals.SETTLEMENT,
                enabled=s.SETTLEMENT_ENABLED,
                runner=self._settlement_loop
            ),
        }
    
    # ========== PUBLIC API ==========
    
    async def start(self) -> None:
        """Start all enabled loops"""
        if self._state not in (OrchestratorState.IDLE, OrchestratorState.STOPPED):
            _log.warning(
                f"Cannot start orchestrator in state {self._state}",
                extra={"symbol": self.symbol, "state": self._state.value}
            )
            return
        
        self._state = OrchestratorState.STARTING
        self._start_time = datetime.utcnow()
        trace_id = generate_trace_id()
        
        _log.info(
            f"Starting orchestrator",
            extra={"symbol": self.symbol, "trace_id": trace_id}
        )
        
        # Start all enabled loops
        for spec in self._loops.values():
            if spec.enabled:
                spec.task = asyncio.create_task(
                    self._loop_runner(spec),
                    name=f"orch-{self.symbol}-{spec.name}"
                )
                spec.state = LoopState.RUNNING
        
        self._state = OrchestratorState.RUNNING
        
        # Publish started event
        await self._publish_event(
            EVT.ORCH_STARTED,
            {"symbol": self.symbol, "loops": list(self._loops.keys())},
            trace_id
        )
        
        _log.info(
            f"Orchestrator started",
            extra={
                "symbol": self.symbol,
                "trace_id": trace_id,
                "enabled_loops": [name for name, spec in self._loops.items() if spec.enabled]
            }
        )
    
    async def stop(self) -> None:
        """Stop all loops"""
        if self._state != OrchestratorState.RUNNING:
            _log.warning(
                f"Cannot stop orchestrator in state {self._state}",
                extra={"symbol": self.symbol, "state": self._state.value}
            )
            return
        
        self._state = OrchestratorState.STOPPING
        trace_id = generate_trace_id()
        
        _log.info(
            f"Stopping orchestrator",
            extra={"symbol": self.symbol, "trace_id": trace_id}
        )
        
        # Cancel all loop tasks
        for spec in self._loops.values():
            if spec.task and not spec.task.done():
                spec.task.cancel()
                spec.state = LoopState.STOPPED
        
        # Wait for all tasks to complete
        tasks = [spec.task for spec in self._loops.values() if spec.task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self._state = OrchestratorState.STOPPED
        
        # Publish stopped event
        await self._publish_event(
            EVT.ORCH_STOPPED,
            {"symbol": self.symbol, "reason": "manual"},
            trace_id
        )
        
        _log.info(
            f"Orchestrator stopped",
            extra={"symbol": self.symbol, "trace_id": trace_id}
        )
    
    async def pause(self) -> None:
        """Pause all loops (keep tasks running but skip execution)"""
        if self._state != OrchestratorState.RUNNING:
            _log.warning(
                f"Cannot pause orchestrator in state {self._state}",
                extra={"symbol": self.symbol, "state": self._state.value}
            )
            return
        
        self._state = OrchestratorState.PAUSED
        trace_id = generate_trace_id()
        
        # Mark all loops as paused
        for spec in self._loops.values():
            if spec.state == LoopState.RUNNING:
                spec.state = LoopState.PAUSED
        
        # Publish paused event
        await self._publish_event(
            EVT.ORCH_PAUSED,
            {"symbol": self.symbol, "reason": "manual"},
            trace_id
        )
        
        _log.info(
            f"Orchestrator paused",
            extra={"symbol": self.symbol, "trace_id": trace_id}
        )
    
    async def resume(self) -> None:
        """Resume paused loops"""
        if self._state != OrchestratorState.PAUSED:
            _log.warning(
                f"Cannot resume orchestrator in state {self._state}",
                extra={"symbol": self.symbol, "state": self._state.value}
            )
            return
        
        self._state = OrchestratorState.RUNNING
        trace_id = generate_trace_id()
        
        # Resume all paused loops
        for spec in self._loops.values():
            if spec.state == LoopState.PAUSED:
                spec.state = LoopState.RUNNING
        
        # Publish resumed event
        await self._publish_event(
            EVT.ORCH_RESUMED,
            {"symbol": self.symbol, "reason": "manual"},
            trace_id
        )
        
        _log.info(
            f"Orchestrator resumed",
            extra={"symbol": self.symbol, "trace_id": trace_id}
        )
    
    def status(self) -> dict[str, Any]:
        """Get current status of orchestrator and all loops"""
        return {
            "state": self._state.value,
            "symbol": self.symbol,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "uptime_seconds": (datetime.utcnow() - self._start_time).total_seconds() if self._start_time else 0,
            "loops": {
                name: {
                    "enabled": spec.enabled,
                    "state": spec.state.value,
                    "interval_sec": spec.interval_sec,
                    "is_alive": spec.is_alive,
                    "last_run": spec.last_run.isoformat() if spec.last_run else None,
                    "error_count": spec.error_count
                }
                for name, spec in self._loops.items()
            }
        }
    
    async def run_once(self) -> dict[str, Any]:
        """
        Execute one full cycle of all processes.
        Used for testing or manual execution.
        """
        trace_id = generate_trace_id()
        start_time = datetime.utcnow()
        results = {}
        
        _log.info(
            f"Running single orchestration cycle",
            extra={"symbol": self.symbol, "trace_id": trace_id}
        )
        
        # Publish cycle started
        await self._publish_event(
            EVT.ORCH_CYCLE_STARTED,
            {"symbol": self.symbol},
            trace_id
        )
        
        # 1. Evaluation and execution
        if self.settings.EVAL_ENABLED:
            try:
                await self.eval_and_execute.execute(trace_id=trace_id)
                results["eval"] = "success"
                self.metrics.increment("orchestrator.step.success", labels={"step": "eval", "symbol": self.symbol})
            except Exception as e:
                _log.error(
                    f"Eval step failed",
                    extra={"symbol": self.symbol, "trace_id": trace_id, "error": str(e)},
                    exc_info=True
                )
                results["eval"] = f"error: {str(e)}"
                self.metrics.increment("orchestrator.step.error", labels={"step": "eval", "symbol": self.symbol})
        
        # 2. Protective exits
        if self.settings.EXITS_ENABLED:
            try:
                await self.protective_exits.check_and_execute(self.symbol, trace_id)
                results["exits"] = "success"
                self.metrics.increment("orchestrator.step.success", labels={"step": "exits", "symbol": self.symbol})
            except Exception as e:
                _log.error(
                    f"Exits step failed",
                    extra={"symbol": self.symbol, "trace_id": trace_id, "error": str(e)},
                    exc_info=True
                )
                results["exits"] = f"error: {str(e)}"
                self.metrics.increment("orchestrator.step.error", labels={"step": "exits", "symbol": self.symbol})
        
        # 3. Reconciliation
        if self.settings.RECONCILE_ENABLED:
            try:
                await self.position_reconciliation.reconcile(self.symbol, trace_id)
                await self.balance_reconciliation.reconcile(self.symbol, trace_id)
                results["reconcile"] = "success"
                self.metrics.increment("orchestrator.step.success", labels={"step": "reconcile", "symbol": self.symbol})
            except Exception as e:
                _log.error(
                    f"Reconcile step failed",
                    extra={"symbol": self.symbol, "trace_id": trace_id, "error": str(e)},
                    exc_info=True
                )
                results["reconcile"] = f"error: {str(e)}"
                self.metrics.increment("orchestrator.step.error", labels={"step": "reconcile", "symbol": self.symbol})
        
        # 4. Health check / Watchdog
        if self.settings.WATCHDOG_ENABLED:
            try:
                await self.health_checker.check(self.symbol, trace_id)
                if self.dead_mans_switch:
                    await self.dead_mans_switch.ping()
                results["watchdog"] = "success"
                self.metrics.increment("orchestrator.step.success", labels={"step": "watchdog", "symbol": self.symbol})
            except Exception as e:
                _log.error(
                    f"Watchdog step failed",
                    extra={"symbol": self.symbol, "trace_id": trace_id, "error": str(e)},
                    exc_info=True
                )
                results["watchdog"] = f"error: {str(e)}"
                self.metrics.increment("orchestrator.step.error", labels={"step": "watchdog", "symbol": self.symbol})
        
        # 5. Settlement
        if self.settings.SETTLEMENT_ENABLED:
            try:
                await self.settlement_service.settle_partial_fills(self.symbol, trace_id)
                results["settlement"] = "success"
                self.metrics.increment("orchestrator.step.success", labels={"step": "settlement", "symbol": self.symbol})
            except Exception as e:
                _log.error(
                    f"Settlement step failed",
                    extra={"symbol": self.symbol, "trace_id": trace_id, "error": str(e)},
                    exc_info=True
                )
                results["settlement"] = f"error: {str(e)}"
                self.metrics.increment("orchestrator.step.error", labels={"step": "settlement", "symbol": self.symbol})
        
        # Calculate duration
        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        # Record metrics
        self.metrics.histogram(
            "orchestrator.cycle.duration_ms",
            duration_ms,
            labels={"symbol": self.symbol}
        )
        
        # Publish cycle completed
        await self._publish_event(
            EVT.ORCH_CYCLE_COMPLETED,
            {
                "symbol": self.symbol,
                "duration_ms": duration_ms,
                "results": results
            },
            trace_id
        )
        
        _log.info(
            f"Orchestration cycle completed",
            extra={
                "symbol": self.symbol,
                "trace_id": trace_id,
                "duration_ms": duration_ms,
                "results": results
            }
        )
        
        return {
            "symbol": self.symbol,
            "trace_id": trace_id,
            "duration_ms": duration_ms,
            "results": results
        }
    
    # ========== INTERNAL METHODS ==========
    
    async def _loop_runner(self, spec: LoopSpec) -> None:
        """Generic runner for background loops"""
        loop = asyncio.get_event_loop()
        
        while self._state in (OrchestratorState.RUNNING, OrchestratorState.PAUSED):
            # Skip if paused
            if self._state == OrchestratorState.PAUSED or spec.state == LoopState.PAUSED:
                await asyncio.sleep(spec.interval_sec)
                continue
            
            trace_id = generate_trace_id()
            start_time = loop.time()
            
            try:
                # Run the loop function
                await spec.runner()
                spec.last_run = datetime.utcnow()
                spec.error_count = 0
                
                # Record metrics
                duration_ms = (loop.time() - start_time) * 1000
                self.metrics.histogram(
                    "orchestrator.loop.duration_ms",
                    duration_ms,
                    labels={"loop": spec.name, "symbol": self.symbol}
                )
                self.metrics.increment(
                    "orchestrator.loop.success",
                    labels={"loop": spec.name, "symbol": self.symbol}
                )
                
            except asyncio.CancelledError:
                _log.info(
                    f"Loop {spec.name} cancelled",
                    extra={"symbol": self.symbol, "trace_id": trace_id}
                )
                break
                
            except Exception as e:
                spec.error_count += 1
                _log.error(
                    f"Loop {spec.name} failed",
                    extra={
                        "symbol": self.symbol,
                        "trace_id": trace_id,
                        "error": str(e),
                        "error_count": spec.error_count
                    },
                    exc_info=True
                )
                
                self.metrics.increment(
                    "orchestrator.loop.error",
                    labels={"loop": spec.name, "symbol": self.symbol}
                )
                
                # Mark as failed if too many errors
                if spec.error_count >= 5:
                    spec.state = LoopState.FAILED
                    _log.error(
                        f"Loop {spec.name} marked as failed after {spec.error_count} errors",
                        extra={"symbol": self.symbol}
                    )
                    break
            
            # Wait for next iteration
            await asyncio.sleep(spec.interval_sec)
    
    async def _eval_loop(self) -> None:
        """Evaluation and execution loop"""
        trace_id = generate_trace_id()
        await self.eval_and_execute.execute(trace_id=trace_id)
    
    async def _exits_loop(self) -> None:
        """Protective exits loop"""
        trace_id = generate_trace_id()
        await self.protective_exits.check_and_execute(self.symbol, trace_id)
    
    async def _reconcile_loop(self) -> None:
        """Reconciliation loop"""
        trace_id = generate_trace_id()
        await self.position_reconciliation.reconcile(self.symbol, trace_id)
        await self.balance_reconciliation.reconcile(self.symbol, trace_id)
    
    async def _watchdog_loop(self) -> None:
        """Health check and DMS ping loop"""
        trace_id = generate_trace_id()
        await self.health_checker.check(self.symbol, trace_id)
        if self.dead_mans_switch:
            await self.dead_mans_switch.ping()
    
    async def _settlement_loop(self) -> None:
        """Settlement loop for partial fills"""
        trace_id = generate_trace_id()
        await self.settlement_service.settle_partial_fills(self.symbol, trace_id)
    
    async def _publish_event(
        self,
        topic: str,
        payload: dict[str, Any],
        trace_id: str
    ) -> None:
        """Publish event to event bus"""
        try:
            payload["trace_id"] = trace_id
            payload["timestamp"] = datetime.utcnow().isoformat()
            await self.event_bus.publish(topic, payload, trace_id)
        except Exception as e:
            _log.error(
                f"Failed to publish event {topic}",
                extra={"trace_id": trace_id, "error": str(e)},
                exc_info=True
            )


# ============= FACTORY =============

def create_orchestrator(
    symbol: str,
    storage: StoragePort,
    broker: BrokerPort,
    event_bus: EventBusPort,
    risk_manager: RiskManager,
    metrics: MetricsPort,
    settings: Settings,
    execute_trade: ExecuteTrade,
    eval_and_execute: EvalAndExecute,
    protective_exits: ProtectiveExits,
    health_checker: HealthChecker,
    settlement_service: SettlementService,
    balance_reconciliation: BalanceReconciliation,
    position_reconciliation: PositionReconciliation,
    dead_mans_switch: Optional[DeadMansSwitchPort] = None
) -> Orchestrator:
    """Factory to create orchestrator with all dependencies"""
    return Orchestrator(
        symbol=symbol,
        storage=storage,
        broker=broker,
        event_bus=event_bus,
        risk_manager=risk_manager,
        metrics=metrics,
        settings=settings,
        execute_trade=execute_trade,
        eval_and_execute=eval_and_execute,
        protective_exits=protective_exits,
        health_checker=health_checker,
        settlement_service=settlement_service,
        balance_reconciliation=balance_reconciliation,
        position_reconciliation=position_reconciliation,
        dead_mans_switch=dead_mans_switch
    )


# ============= EXPORT =============

__all__ = [
    "Orchestrator",
    "OrchestratorState",
    "LoopState",
    "LoopSpec",
    "create_orchestrator",
]