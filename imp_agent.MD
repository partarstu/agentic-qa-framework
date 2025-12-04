# Implementation Plan - Multi-Agent Test Case Generation

## Objective
Refactor `agents/test_case_generation/main.py` to implement a multi-agent workflow. The process will be broken down into 3 distinct steps handled by sub-agents, with the main agent acting as the orchestrator.

## Proposed Changes

### 1. Data Models (`common/models.py`)
Define new Pydantic models to support the intermediate data exchange between agents.

*   **`AcceptanceCriteriaItem`**: Represents a single extracted acceptance criterion.
    *   `id`: str (e.g., "AC-1")
    *   `text`: str
*   **`AcceptanceCriteriaList`**: A collection of `AcceptanceCriteriaItem`.
    *   `items`: List[AcceptanceCriteriaItem]
*   **`TestStepsSequence`**: A sequence of test steps for a specific AC.
    *   `ac_id`: str
    *   `steps`: List[TestStep] (Reusing existing `TestStep` model)

### 2. Prompts (`agents/test_case_generation/`)
Create distinct system prompts for each sub-agent.

*   **`ac_extraction_prompt.txt`**: Instructions for extracting and decomposing acceptance criteria from a Jira User Story.
*   **`steps_generation_prompt.txt`**: Instructions for generating detailed test steps from a specific Acceptance Criterion and User Story context.
*   **`test_case_creation_prompt.txt`**: Instructions for formulating a final `TestCase` object (adding metadata like summary, preconditions) from a sequence of steps.

Update `agents/test_case_generation/prompt.py` to include classes for loading these new prompts:
*   `ACExtractionPrompt`
*   `StepsGenerationPrompt`
*   `TestCaseCreationPrompt`

### 3. Agents Implementation (`agents/test_case_generation/main.py`)
Refactor `TestCaseGenerationAgent` to act as the orchestrator and define the sub-agents.

#### Sub-Agents Construction
Inside `TestCaseGenerationAgent`, initialize three `pydantic_ai.Agent` instances (or similar constructs):
1.  **`ac_extractor_agent`**:
    *   Model: `config.TestCaseGenerationAgentConfig.MODEL_NAME`
    *   Output Type: `AcceptanceCriteriaList`
    *   System Prompt: From `ACExtractionPrompt`
2.  **`steps_generator_agent`**:
    *   Model: `config.TestCaseGenerationAgentConfig.MODEL_NAME`
    *   Output Type: `TestStepsSequence`
    *   System Prompt: From `StepsGenerationPrompt`
3.  **`test_case_creator_agent`**:
    *   Model: `config.TestCaseGenerationAgentConfig.MODEL_NAME`
    *   Output Type: `TestCase`
    *   System Prompt: From `TestCaseCreationPrompt`

#### Orchestration Logic (Overriding `run` or `_get_agent_execution_result`)
The main execution flow will be:

1.  **Fetch Context**:
    *   Extract the Jira Issue Key from the user request.
    *   Use the `jira_mcp_server` (or equivalent tool) to fetch the full `JiraUserStory`.
    *   (Optional) Fetch attachments if needed.

2.  **Step 1: AC Extraction**:
    *   Invoke `ac_extractor_agent` with the `JiraUserStory` content.
    *   **Result**: `AcceptanceCriteriaList`.

3.  **Step 2: Steps Generation (Loop)**:
    *   Iterate through each `AcceptanceCriteriaItem` in the list.
    *   Invoke `steps_generator_agent` with the `AcceptanceCriteriaItem` and the context of the `JiraUserStory`.
    *   **Result**: List of `TestStepsSequence`.

4.  **Step 3: Test Case Creation (Loop)**:
    *   Iterate through each `TestStepsSequence`.
    *   Invoke `test_case_creator_agent` with the `TestStepsSequence`, `AcceptanceCriteriaItem`, and `JiraUserStory`.
    *   **Result**: List of `TestCase`.

5.  **Finalize**:
    *   Aggregate all `TestCase` objects into a `GeneratedTestCases` object.
    *   Call the existing `_create_test_cases` method to save them to the Test Management System.
    *   Return the final confirmation message.

## detailed Steps

1.  **Update `common/models.py`**: Add `AcceptanceCriteriaItem`, `AcceptanceCriteriaList`, `TestStepsSequence`.
2.  **Create Prompt Files**: Add the 3 new `.txt` files in `agents/test_case_generation/`.
3.  **Update `agents/test_case_generation/prompt.py`**: Implement the prompt loading classes.
4.  **Refactor `agents/test_case_generation/main.py`**:
    *   Import new models and prompts.
    *   Implement the orchestration logic in `TestCaseGenerationAgent`.
    *   Ensure the `run` method handles the flow sequentially.
    *   Ensure dependencies (like `JiraUserStory`) are passed correctly to sub-agents.
