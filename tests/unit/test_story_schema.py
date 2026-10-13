import pytest
from pydantic import ValidationError
from backend.schemas import Story

@pytest.mark.parametrize("field", ["characters", "scenes"])
def test_duplicate_story_entity_ids_are_rejected(field):
    item = {"id": "one", "name": "人物或场景", "description": "保持一致"}
    story = {"title": "故事", "synopsis": "开始与结束", "characters": [item], "scenes": [item]}
    story[field] = [item, dict(item, name="重复ID")]
    with pytest.raises(ValidationError): Story.model_validate(story)
