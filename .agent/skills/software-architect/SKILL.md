---
name: software-architect
description: Acts as a software architect to plan and guide the implementation or modification of features, ensuring best practices, modern design patterns, and proper planning. Use this skill when the user asks for a new feature, a complex modification, architectural advice, or needs to design a new component.
---

// turbo-all

# Software Architect Skill

This skill guides you through the process of architecting and planning software changes for the QuAIA™ framework. It ensures that all
modifications align with the current tech stack (Python 3.12+, FastAPI, Pydantic V2, Agentic Frameworks), adhere to 2025/2026 best
practices, and use established design patterns.

## ⚠️ User Intervention Policy

Proceed **autonomously** through research and analysis steps. Stop and involve the user when:

- **Major architectural decisions**: Trade-offs that significantly impact the system
- **New dependencies**: Adding libraries or external services
- **Security-sensitive changes**: Authentication, authorization, data handling
- **Approval required**: Before finalizing the Implementation Plan

**Intervention Pattern**:

1. **STOP** and **PRESENT** the decision with context and options
2. **ASK** for the user's preferred approach
3. **WAIT** for response, then proceed with guidance

## ⚡ Auto-Run Policy

This skill is designed to run with minimal interruption during research and planning phases.

- **Always set `SafeToAutoRun: true`** for all `run_command` and tool usage where applicable.
- **Exceptions:** Only stop for explicit user approval steps (like reviewing the Implementation Plan).
- **Restricted Symbols:** Never use the redirection operator (`>`) or `2>` in commands. Use alternatives (e.g., `Set-Content`, `Out-File`, or ignoring errors explicitly).

---

## Core Principles

### 1. Mandatory Web Search 🔍

You **MUST** perform `search_web` for every major library, pattern, or decision to ensure you use the latest documentation and best
practices.

**Required searches:**

- Library documentation (target 2025/2026 versions)
- Security advisories for dependencies
- Deprecated patterns to avoid
- Performance benchmarks for critical paths

**Search query templates:**

```
"[library name] best practices 2025"
"[library name] [version] documentation"
"[pattern name] python implementation 2025"
"[library name] security vulnerabilities CVE"
"fastapi [topic] async best practices"
"pydantic v2 [topic] migration"
```

**Evaluate search results by:**

1. Prefer official documentation over blog posts
2. Check publication date (prefer < 1 year old)
3. Verify against multiple sources for critical decisions

### 2. Tech Stack Alignment 🛠️

All implementations must fit within the existing `agentic_qa_framework`:

| Category     | Technologies                   | Notes                                     |
|--------------|--------------------------------|-------------------------------------------|
| **Language** | Python 3.12+                   | Use modern syntax: `match`, `             |` types, `slots=True` |
| **Web/API**  | FastAPI, Pydantic V2           | Async-first, use `Depends` for DI         |
| **Async**    | `asyncio`, `httpx`             | Prefer async for I/O-bound operations     |
| **Data**     | `dataclasses`, Pydantic models | Use `slots=True` for performance          |
| **Config**   | Pydantic `BaseSettings`        | Environment-based configuration           |
| **Testing**  | Pytest, pytest-asyncio         | Async test support, comprehensive mocking |
| **Logging**  | `logging` module               | Structured logging with context           |
| **Agentic**  | ReAct, Reflection, Tool Use    | See Agentic Patterns section              |

### 3. Project Rules Integration 📚

You **MUST** read and apply rules from `GEMINI.md`:

```
Read the file: GEMINI.md
```

Key rules to enforce:

- Snake_case for functions/variables, PascalCase for classes
- Type hints for all function signatures
- Docstrings for all public modules, classes, and functions
- Favor composition over inheritance
- Never duplicate existing functionality
- Always validate and sanitize inputs

### 4. Security-First Design 🔒

Security is a first-class concern, not an afterthought:

- **Input Validation**: Use Pydantic validators for all external inputs
- **Secret Management**: Never hardcode secrets; use environment variables
- **Principle of Least Privilege**: Request minimal permissions
- **Threat Modeling**: Consider attack vectors for new features
- **OWASP Guidelines**: Reference for web security best practices

### 5. Best Practices Checklist ✅

- [ ] **Clean Code**: SOLID principles, meaningful naming, single responsibility
- [ ] **Type Safety**: Strict type hints, use `str | None` over `Optional[str]`
- [ ] **Documentation**: Docstrings (PEP 257), inline comments for "why"
- [ ] **Error Handling**: Specific exceptions, never bare `except:`
- [ ] **Testing**: TDD mindset - define tests before implementation
- [ ] **Async**: Use `async def` for I/O-bound operations
- [ ] **Logging**: Structured logs with appropriate levels
- [ ] **Configuration**: Externalize via environment variables

---

## Agentic Design Patterns 🤖

When designing agent-related features, apply these patterns appropriately:

### ReAct Pattern (Reasoning + Acting)

**Use when:** Agent needs to interleave thinking with tool execution.

**Implementation checklist:**

- [ ] Define explicit reasoning steps before actions
- [ ] Create auditable thought trail
- [ ] Ground each step in observable outcomes
- [ ] Implement loop: Reason → Act → Observe → Repeat

**Example structure:**

```python
class ReActAgent:
    async def execute(self, task: str) -> Result:
        while not self.is_complete():
            thought = await self.reason(task, self.observations)
            action = await self.decide_action(thought)
            observation = await self.execute_action(action)
            self.observations.append(observation)
        return self.compile_result()
```

### Reflection Pattern (Self-Improvement)

**Use when:** Agent output quality needs iterative refinement.

**Implementation checklist:**

- [ ] Generate initial output
- [ ] Apply self-critique with specific criteria
- [ ] Identify gaps, errors, or improvements
- [ ] Iterate until quality threshold met or max iterations

**Quality gates:**

- Completeness check
- Consistency validation
- Error detection
- Style/format compliance

### Tool Use Pattern (External Capabilities)

**Use when:** Agent needs to interact with external systems.

**Implementation checklist:**

- [ ] Define strict input/output schemas (Pydantic)
- [ ] Implement input validation before execution
- [ ] Add timeout handling for external calls
- [ ] Log tool invocations for debugging
- [ ] Handle tool failures gracefully

**Guardrails:**

```python
class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]

    def validate_input(self, input_data: dict) -> bool:
        # Validate against schema
        ...
```

### Multi-Agent Collaboration

**Use when:** Task complexity exceeds single agent capability.

**Decision criteria:**

- Single agent: Task is focused, linear, single domain
- Multi-agent: Task spans domains, requires parallel work, or specialized expertise

**Patterns:**

- **Orchestrator**: Central coordinator delegates to specialists
- **Pipeline**: Sequential handoff between agents
- **Consensus**: Multiple agents vote on decisions

### Human-in-the-Loop (HITL)

**Use when:** Decisions have high impact or uncertainty.

**Implementation:**

- Define clear approval checkpoints
- Provide context and options to human
- Implement timeout with safe defaults
- Log human decisions for audit

---

## Scalability & Performance ⚡

Consider these aspects for every design:

### Async vs Sync Decision

| Use Async (`async def`) | Use Sync (`def`)          |
|-------------------------|---------------------------|
| HTTP requests           | CPU-bound computation     |
| Database queries        | Simple transformations    |
| File I/O                | In-memory operations      |
| External API calls      | Synchronous library calls |

### Caching Strategy

- **When to cache**: Expensive computations, external API responses, repeated queries
- **Cache invalidation**: Time-based TTL, event-based purge
- **Tools**: `functools.lru_cache`, Redis, in-memory dict with TTL

### Connection Management

- Use connection pooling for databases and HTTP clients
- Implement circuit breakers for external services
- Set appropriate timeouts (connect, read, total)

### Performance Requirements

- Define response time targets (p50, p95, p99)
- Identify bottlenecks with profiling
- Plan for horizontal scaling if needed

---

## Error Handling & Resilience 🛡️

### Exception Hierarchy

```python
class QuAIAError(Exception):
    """Base exception for all QuAIA errors."""
    pass


class AgentExecutionError(QuAIAError):
    """Error during agent execution."""
    pass


class ToolError(QuAIAError):
    """Error in tool execution."""
    pass
```

### Retry Pattern

```python
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def call_external_service():
    ...
```

### Graceful Degradation

- Define fallback behaviors for external service failures
- Return partial results when possible
- Log degraded state for monitoring

---

## Workflow

### Step 1: Understand & Research 🔍

#### 1.1 Analyze the Request

- Read the user's request and the current `Active Document`
- Identify the scope: new feature, modification, or architectural advice
- List initial questions and unknowns

#### 1.2 Read Project Rules

```
Read the file: GEMINI.md
```

Note any rules that specifically apply to this task.

#### 1.3 Explore Existing Codebase

Use `list_dir` and `view_file_outline` to understand:

- Relevant existing modules and their structure
- Patterns already in use
- Code to reuse (never duplicate functionality)

#### 1.4 Conduct Web Research

**Mandatory searches:**

1. Latest docs for each library involved
2. Best practices for the specific problem domain
3. Security considerations for the feature type
4. Common pitfalls and anti-patterns

**Document findings:**
| Source | Key Learning | Applied To |
|--------|--------------|------------|
| [URL] | [Learning] | [How it applies] |

### Step 2: Design Architecture 📐

#### 2.1 Evaluate Approaches

Create a decision matrix for significant choices:

📄 **Template:** [resources/decision_matrix_template.md](resources/decision_matrix_template.md)

Consider:

- Trade-offs (performance vs. simplicity, flexibility vs. complexity)
- Alignment with existing patterns
- Future extensibility
- Testing complexity

#### 2.2 Create Architecture Diagrams

Use Mermaid diagrams to visualize:

📄 **Templates:** [resources/diagram_templates.md](resources/diagram_templates.md)

Required diagrams (as applicable):

- **Component Diagram**: For new modules and their dependencies
- **Sequence Diagram**: For complex interactions
- **Data Flow Diagram**: For data processing pipelines

#### 2.3 Create Architecture Decision Record (ADR)

For significant architectural decisions, create an ADR:

📄 **Template:** [resources/adr_template.md](resources/adr_template.md)

**When to create ADR:**

- Adding new dependencies
- Choosing between multiple valid approaches
- Deviating from existing patterns
- Security-sensitive decisions

**Store ADRs in:** Project documentation or include in implementation plan.

### Step 3: Create Implementation Plan 📋

#### 3.1 Read Template

```
Read the file: .agent/skills/software-architect/resources/implementation_plan_template.md
```

#### 3.2 Draft Plan

Create a new markdown artifact (e.g., `IMPLEMENTATION_PLAN.md`) based on the template.

**Required sections:**

- Overview & Goals
- Research Findings (with sources)
- Architecture Design (with diagrams)
- Security Considerations
- Performance Requirements
- Proposed Changes (files, APIs, models)
- Implementation Steps (small, testable chunks)
- Testing Strategy
- Rollback Plan
- Definition of Done

#### 3.3 Review with User

Present the plan and explicitly ask:

> "Here is the implementation plan for [feature]. Please review the following key decisions:
> 1. [Decision 1] - [Trade-off]
> 2. [Decision 2] - [Trade-off]
>
> Do you approve this plan, or would you like modifications?"

**Wait for user approval before proceeding.**

### Step 4: Handoff & Track 🚀

#### 4.1 Execution Guidance

Once approved, provide clear next steps:

- For new agents: Reference skill `creating-new-agent`
- For orchestrator changes: Reference skill `adding-orchestrator-workflow`
- For tests: Reference skill `writing-unit-tests`
- For PR preparation: Reference skill `prepare-pr`

#### 4.2 Implementation Checklist

Provide a checklist for the implementer:

```markdown
- [ ] Step 1: [Description] - Verify: [How to verify]
- [ ] Step 2: [Description] - Verify: [How to verify]
  ...
- [ ] Run tests: `pytest tests/ -v`
- [ ] Run linting: `ruff check .`
```

#### 4.3 Track Progress

If implementing yourself:

- Complete each step and verify
- Update the plan with any deviations
- Document any decisions made during implementation

---

## Verification Checklist ✅

Before finalizing the implementation plan, verify:

### Research

- [ ] Web search conducted for all major libraries and patterns
- [ ] Official documentation referenced (not just blog posts)
- [ ] Security advisories checked for dependencies
- [ ] Deprecated patterns identified and avoided

### Design

- [ ] Architecture diagrams created (component, sequence, data flow)
- [ ] ADR created for significant decisions
- [ ] Trade-offs documented and justified
- [ ] Existing code patterns followed or deviation justified

### Compliance

- [ ] `GEMINI.md` rules verified and applied
- [ ] Type hints specified for all interfaces
- [ ] Error handling strategy defined
- [ ] Security considerations documented

### Implementation Plan

- [ ] All sections of template completed
- [ ] Steps are small and independently testable
- [ ] Testing strategy covers unit, integration, edge cases
- [ ] Rollback plan defined
- [ ] Definition of done is clear and measurable

### User Approval

- [ ] Plan presented to user
- [ ] Key decisions highlighted for review
- [ ] User approval received

---

## Integration with Other Skills

| When you need to...       | Use skill...                   |
|---------------------------|--------------------------------|
| Create a new agent        | `creating-new-agent`           |
| Add orchestrator endpoint | `adding-orchestrator-workflow` |
| Write unit tests          | `writing-unit-tests`           |
| Prepare for PR            | `prepare-pr`                   |
| Review a PR               | `pr-review`                    |

---

## Dependency Evaluation Process 📦

When considering adding a new dependency:

### Evaluation Criteria

| Criterion       | Check                                             |
|-----------------|---------------------------------------------------|
| **Necessity**   | Can we achieve this with stdlib or existing deps? |
| **Maintenance** | Last release < 6 months? Active maintainers?      |
| **Security**    | Run `pip-audit` check, review CVE database        |
| **License**     | Compatible with Apache-2.0?                       |
| **Size**        | Minimal additional dependencies?                  |
| **Popularity**  | Established community? Good documentation?        |

### Decision

If adding dependency:

1. Document justification in ADR
2. Add to `requirements.txt`
3. Note in implementation plan

If rejecting:

1. Document reason
2. Propose alternative approach

---

## Quick Reference

### Common Search Queries

```
"fastapi dependency injection best practices 2025"
"pydantic v2 custom validators"
"python asyncio patterns 2025"
"pytest async fixtures"
"python dataclasses performance slots"
```

### Common Patterns

- **Factory Pattern**: For creating agent instances
- **Strategy Pattern**: For pluggable behaviors
- **Repository Pattern**: For data access abstraction
- **Dependency Injection**: Via FastAPI `Depends`

### File Naming Conventions

- Modules: `snake_case.py`
- Classes: `PascalCase`
- Tests: `test_<module_name>.py`
- System prompts: `<agent_name>_prompt_template.txt`
