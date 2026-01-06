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
from orchestrator.memory_log_handler import memory_log_handler, LogEntry

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

    async def get_logs(self, limit: int = 100, level: str | None = None,
                       task_id: str | None = None, agent_id: str | None = None) -> List[Dict[str, Any]]:
        """Returns recent application logs.
        
        When task_id or agent_id is provided, returns only agent execution logs
        from task artifacts. When neither is provided, returns orchestrator logs only.
        """
        result_entries: List[LogEntry] = []
        
        # If task_id is provided, return only agent logs from that specific task
        if task_id:
            task_record = await self.tasks.get_by_id(task_id)
            if task_record and task_record.agent_logs:
                result_entries = self._parse_agent_logs(
                    task_record.agent_logs, task_id, task_record.agent_id
                )
        
        # If agent_id is provided (and no task_id), return agent logs from all tasks of this agent
        elif agent_id:
            all_tasks = await self.tasks.get_all()
            # Filter tasks for this agent
            agent_tasks = [t for t in all_tasks if t.agent_id == agent_id]
            for task in agent_tasks:  # Check all tasks for this agent
                if task.agent_logs:
                    result_entries.extend(
                        self._parse_agent_logs(task.agent_logs, task.task_id, agent_id)
                    )
        
        # If neither task_id nor agent_id is provided, return orchestrator logs only
        else:
            result_entries = memory_log_handler.get_logs(limit=limit, level=level)
        
        # Filter by level if specified and we have agent logs
        if level and (task_id or agent_id):
            level_upper = level.upper()
            result_entries = [log for log in result_entries if log.level == level_upper]
        
        # Sort by timestamp
        result_entries.sort(key=lambda x: x.timestamp)
        
        # Apply limit - take the last 'limit' items (most recent)
        limited_logs = result_entries[-limit:]
        
        return [entry.to_dict() for entry in limited_logs]

    def _parse_agent_logs(self, raw_logs: List[str], task_id: str, agent_id: str) -> List[LogEntry]:
        """Parse raw agent log strings into LogEntry objects.
           We'll try to extract timestamp/level if possible, otherwise use placeholders.
        """
        entries = []
        for log_chunk in raw_logs:
            # Agent logs might be one big string or lines
            lines = log_chunk.splitlines()
            for line in lines:
                if not line.strip(): continue
                
                # Simple parsing logic - can be improved if agent log format is known
                # Default values
                timestamp = datetime.now().isoformat()
                level = "INFO"
                logger_name = f"agent.{agent_id}"
                message = line
                
                # Simple heuristic: "2023-..." at start
                parts = line.split(" - ", 3)
                if len(parts) >= 3:
                     # Attempt to parse: timestamp - name - level - message
                     # or: timestamp - level - message
                     try:
                         # Just check if first part looks like date?
                         # For now, just keep the line as message and use task completion time? 
                         # Actually, using current time for historical logs is confusing.
                         # Ideally agent logs have timestamps. 
                         pass
                     except:
                         pass
                
                # If the line contains typical log levels
                if "ERROR" in line: level = "ERROR"
                elif "WARNING" in line: level = "WARNING"
                elif "DEBUG" in line: level = "DEBUG"
                
                entries.append(LogEntry(
                    timestamp=timestamp, 
                    level=level, 
                    logger_name=logger_name, 
                    message=message,
                    task_id=task_id,
                    agent_id=agent_id
                ))
        return entries


# Global service instance
dashboard_service = OrchestratorDashboardService(
    registry=agent_registry,
    tasks=task_history,
    errors=error_history
)
