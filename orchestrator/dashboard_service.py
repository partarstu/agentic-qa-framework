# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Dashboard service for aggregating orchestrator state for the Web UI.
"""

from datetime import datetime
from typing import List, Dict, Any

from common import utils
from orchestrator.models import (
    AgentRegistry, AgentStatus, TaskHistory, ErrorHistory,
    ORCHESTRATOR_START_TIME, agent_registry, task_history, error_history
)
from orchestrator.memory_log_handler import memory_log_handler

logger = utils.get_logger("orchestrator_dashboard")


class OrchestratorDashboardService:
    """Service for providing dashboard data to the Web UI."""
    
    def __init__(
        self, 
        registry: AgentRegistry,
        tasks: TaskHistory,
        errors: ErrorHistory
    ):
        self.registry = registry
        self.tasks = tasks
        self.errors = errors

    async def get_summary(self) -> Dict[str, Any]:
        """Returns high-level statistics for the dashboard."""
        cards = await self.registry.get_all_cards()
        total_agents = len(cards)
        available = 0
        busy = 0
        broken = 0
        
        for agent_id in cards.keys():
            status = await self.registry.get_status(agent_id)
            if status == AgentStatus.AVAILABLE:
                available += 1
            elif status == AgentStatus.BUSY:
                busy += 1
            elif status == AgentStatus.BROKEN:
                broken += 1
        
        # Get task counts
        all_tasks = await self.tasks.get_all()
        running_tasks = sum(1 for t in all_tasks if t.status.value == "RUNNING")
        completed_tasks = sum(1 for t in all_tasks if t.status.value == "COMPLETED")
        failed_tasks = sum(1 for t in all_tasks if t.status.value == "FAILED")
        
        # Get error count
        all_errors = await self.errors.get_all()
        
        # Calculate uptime
        uptime_seconds = int((datetime.now() - ORCHESTRATOR_START_TIME).total_seconds())
        
        return {
            "agents_total": total_agents,
            "agents_available": available,
            "agents_busy": busy,
            "agents_broken": broken,
            "tasks_running": running_tasks,
            "tasks_completed": completed_tasks,
            "tasks_failed": failed_tasks,
            "tasks_total": len(all_tasks),
            "errors_total": len(all_errors),
            "orchestrator_start_time": ORCHESTRATOR_START_TIME.isoformat(),
            "uptime_seconds": uptime_seconds,
            "current_time": datetime.now().isoformat()
        }

    async def get_agents_status(self) -> List[Dict[str, Any]]:
        """Returns detailed list of agents with their current state."""
        cards = await self.registry.get_all_cards()
        result = []
        
        for agent_id, card in cards.items():
            status = await self.registry.get_status(agent_id)
            broken_reason, stuck_task_id = await self.registry.get_broken_context(agent_id)
            current_task_id = await self.registry.get_current_task(agent_id)
            
            # Get current task details if available
            current_task_info = None
            if current_task_id:
                task = await self.tasks.get_by_id(current_task_id)
                if task:
                    current_task_info = {
                        "task_id": task.task_id,
                        "description": task.description,
                        "start_time": task.start_time.isoformat()
                    }
            
            result.append({
                "id": agent_id,
                "name": card.name,
                "url": card.url,
                "status": status.value,
                "capabilities": card.capabilities.model_dump() if card.capabilities else None,
                "current_task": current_task_info,
                "broken_reason": broken_reason.value if broken_reason else None,
                "stuck_task_id": stuck_task_id
            })
        
        return result

    async def get_recent_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns recent tasks with their details."""
        tasks = await self.tasks.get_all()
        return [task.to_dict() for task in tasks[:limit]]

    async def get_recent_errors(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Returns recent errors with context."""
        errors = await self.errors.get_recent(limit)
        return [error.to_dict() for error in errors]

    async def get_logs(self, limit: int = 100, level: str | None = None) -> List[Dict[str, Any]]:
        """Returns recent application logs."""
        log_entries = memory_log_handler.get_logs(limit=limit, level=level)
        return [entry.to_dict() for entry in log_entries]


# Global service instance
dashboard_service = OrchestratorDashboardService(
    registry=agent_registry,
    tasks=task_history,
    errors=error_history
)
