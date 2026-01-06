
import pytest
from common.models import JsonSerializableModel, JiraUserStory

def test_json_serializable_model_str():
    class TestModel(JsonSerializableModel):
        name: str
        value: int

    model = TestModel(name="test", value=123)
    json_str = str(model)
    assert '"name": "test"' in json_str
    assert '"value": 123' in json_str

def test_jira_user_story():
    story = JiraUserStory(
        id=1,
        key="TEST-1",
        summary="Summary",
        description="Description",
        acceptance_criteria="AC",
        status="Open"
    )
    assert story.key == "TEST-1"
    assert str(story) is not None
