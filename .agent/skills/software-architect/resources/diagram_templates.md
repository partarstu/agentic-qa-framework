# Mermaid Diagram Templates

This file contains templates for common architecture diagrams used in implementation plans.

---

## Component Diagram

Use for showing modules, their responsibilities, and dependencies.

```mermaid
graph TB
    subgraph "Orchestrator Layer"
        ORCH[Orchestrator<br/>FastAPI Service]
    end
    
    subgraph "Agent Layer"
        AGENT_A[Agent A<br/>Specialized Task]
        AGENT_B[Agent B<br/>Specialized Task]
    end
    
    subgraph "Common Layer"
        COMMON[Common Utilities]
        MODELS[Shared Models]
    end
    
    subgraph "External Services"
        LLM[LLM Provider]
        MCP[MCP Servers]
        DB[(Database)]
    end
    
    ORCH --> AGENT_A
    ORCH --> AGENT_B
    AGENT_A --> COMMON
    AGENT_B --> COMMON
    AGENT_A --> MODELS
    AGENT_B --> MODELS
    AGENT_A --> LLM
    AGENT_B --> LLM
    AGENT_A -.-> MCP
    AGENT_B -.-> MCP
    ORCH --> DB
    
    classDef service fill:#e1f5fe,stroke:#01579b
    classDef agent fill:#e8f5e9,stroke:#1b5e20
    classDef common fill:#fff3e0,stroke:#e65100
    classDef external fill:#fce4ec,stroke:#880e4f
    
    class ORCH service
    class AGENT_A,AGENT_B agent
    class COMMON,MODELS common
    class LLM,MCP,DB external
```

---

## Sequence Diagram

Use for showing interactions between components over time.

```mermaid
sequenceDiagram
    participant User
    participant Orchestrator
    participant Agent
    participant LLM
    participant Tool
    
    User->>Orchestrator: Submit Task
    activate Orchestrator
    
    Orchestrator->>Agent: Delegate Task
    activate Agent
    
    loop ReAct Loop
        Agent->>LLM: Reason about task
        LLM-->>Agent: Thought + Action
        
        alt Tool Required
            Agent->>Tool: Execute tool
            Tool-->>Agent: Tool result
        end
        
        Agent->>Agent: Update observations
    end
    
    Agent-->>Orchestrator: Task Result
    deactivate Agent
    
    Orchestrator-->>User: Final Response
    deactivate Orchestrator
```

---

## Data Flow Diagram

Use for showing how data moves through the system.

```mermaid
flowchart LR
    subgraph Input
        REQ[API Request]
        FILE[File Upload]
    end
    
    subgraph Processing
        VAL[Validation<br/>Pydantic]
        TRANSFORM[Transform<br/>Business Logic]
        ENRICH[Enrichment<br/>LLM Processing]
    end
    
    subgraph Output
        RESP[API Response]
        STORE[Storage]
        NOTIFY[Notification]
    end
    
    REQ --> VAL
    FILE --> VAL
    VAL --> TRANSFORM
    TRANSFORM --> ENRICH
    ENRICH --> RESP
    ENRICH --> STORE
    ENRICH --> NOTIFY
    
    style VAL fill:#e3f2fd
    style TRANSFORM fill:#e8f5e9
    style ENRICH fill:#fff8e1
```

---

## State Machine Diagram

Use for showing agent or task states and transitions.

```mermaid
stateDiagram-v2
    [*] --> Pending: Task Created
    
    Pending --> Running: Agent Picked Up
    Running --> Completed: Success
    Running --> Failed: Error
    Running --> Running: Iteration
    
    Failed --> Pending: Retry
    Failed --> [*]: Max Retries
    
    Completed --> [*]
    
    note right of Running
        Agent is actively
        processing the task
    end note
```

---

## Class Diagram

Use for showing class relationships and inheritance.

```mermaid
classDiagram
    class AgentBase {
        <<abstract>>
        +agent_card: AgentCard
        +execute_task(task)* Result
        #get_thinking_budget() int
        #get_max_requests_per_task() int
    }
    
    class PromptBase {
        <<abstract>>
        +system_prompt: str
        +format_prompt(context)* str
    }
    
    class SpecificAgent {
        +tools: list
        +execute_task(task) Result
        -_call_tool(name, args) Any
    }
    
    class SpecificPrompt {
        +template_path: Path
        +format_prompt(context) str
    }
    
    class BaseModel {
        <<pydantic>>
        +model_validate()
        +model_dump()
    }
    
    class AgentResult {
        +llm_comments: str
        +data: Any
    }
    
    AgentBase <|-- SpecificAgent
    PromptBase <|-- SpecificPrompt
    BaseModel <|-- AgentResult
    SpecificAgent --> SpecificPrompt : uses
    SpecificAgent --> AgentResult : produces
```

---

## Deployment Diagram

Use for showing infrastructure and deployment topology.

```mermaid
graph TB
    subgraph "Google Cloud Platform"
        subgraph "Cloud Run"
            ORCH_SVC[Orchestrator Service]
            AGENT_SVC_1[Agent Service 1]
            AGENT_SVC_2[Agent Service 2]
        end
        
        subgraph "Supporting Services"
            SECRETS[Secret Manager]
            LOGGING[Cloud Logging]
            STORAGE[Cloud Storage]
        end
    end
    
    subgraph "External"
        USER[User/Client]
        LLM_API[LLM API]
    end
    
    USER --> ORCH_SVC
    ORCH_SVC --> AGENT_SVC_1
    ORCH_SVC --> AGENT_SVC_2
    AGENT_SVC_1 --> LLM_API
    AGENT_SVC_2 --> LLM_API
    
    ORCH_SVC -.-> SECRETS
    AGENT_SVC_1 -.-> SECRETS
    AGENT_SVC_2 -.-> SECRETS
    
    ORCH_SVC -.-> LOGGING
    ORCH_SVC -.-> STORAGE
```

---

## Error Handling Flow

Use for showing how errors propagate and are handled.

```mermaid
flowchart TD
    START[Operation Start] --> TRY{Try Operation}
    
    TRY -->|Success| SUCCESS[Return Result]
    TRY -->|Failure| CLASSIFY{Classify Error}
    
    CLASSIFY -->|Retryable| RETRY{Retry Count?}
    CLASSIFY -->|Non-Retryable| LOG_ERROR[Log Error]
    
    RETRY -->|< Max| BACKOFF[Exponential Backoff]
    RETRY -->|>= Max| FALLBACK{Fallback Available?}
    
    BACKOFF --> TRY
    
    FALLBACK -->|Yes| USE_FALLBACK[Use Fallback]
    FALLBACK -->|No| LOG_ERROR
    
    USE_FALLBACK --> SUCCESS
    LOG_ERROR --> RAISE[Raise Exception]
    
    style SUCCESS fill:#c8e6c9
    style RAISE fill:#ffcdd2
```

---

## Usage Notes

1. **Copy the diagram that fits your use case**
2. **Modify labels and connections** to match your implementation
3. **Keep diagrams focused** - one concern per diagram
4. **Use consistent styling** with the `classDef` and `style` directives
5. **Test in a Mermaid renderer** before including in the plan

### Mermaid Live Editor

Test diagrams at: https://mermaid.live/
