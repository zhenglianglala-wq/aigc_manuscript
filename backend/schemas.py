from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Brief(Strict):
    description: str = Field(min_length=1, max_length=6000)
    duration_seconds: int = Field(default=30, ge=5, le=120)
    aspect_ratio: Literal['16:9','9:16','1:1'] = '9:16'
    style: str = Field(default='电影感', max_length=200)
    language: str = Field(default='zh', max_length=20)
    audience: str = Field(default='大众', max_length=200)
    must_include: list[str] = Field(default_factory=list, max_length=30)
    must_avoid: list[str] = Field(default_factory=list, max_length=30)
    prompt_profile: Literal['generic_text_to_video','motion_first_image_to_video'] = 'generic_text_to_video'
    @field_validator('must_include','must_avoid')
    @classmethod
    def constraints(cls, items):
        if any(not x.strip() or len(x)>300 for x in items):
            raise ValueError('Constraints must be nonempty and at most 300 characters')
        return items

class NewProject(Strict):
    title: str | None = Field(default=None, max_length=200)
    brief: Brief
class ProjectPatch(Strict):
    base_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1,max_length=200)
    brief: Brief | None = None
class BaseRevision(Strict):
    base_revision: int = Field(ge=1)
class ProfilePatch(Strict):
    display_name: str | None = Field(default=None,min_length=1,max_length=100)
    language: str | None = Field(default=None,min_length=1,max_length=20)
    default_duration_seconds: int | None = Field(default=None,ge=5,le=120)
    default_aspect_ratio: Literal['16:9','9:16','1:1'] | None = None
    default_style: str | None = Field(default=None,min_length=1,max_length=200)
class RunRequest(Strict):
    kind: Literal['expand','timeline','rewrite','check']
    base_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1,max_length=128)
    instruction: str = Field(default='',max_length=6000)
    start_second: int | None = Field(default=None,ge=0)
    end_second: int | None = Field(default=None,ge=1)
    locked_fields: list[Literal['visual','action','camera','dialogue','sound','continuity']] = Field(default_factory=list)
    approval_id: str | None = None
class BeatChanges(Strict):
    visual: str | None = Field(default=None,min_length=1,max_length=3000)
    action: str | None = Field(default=None,min_length=1,max_length=3000)
    camera: str | None = Field(default=None,min_length=1,max_length=1000)
    dialogue: str | None = Field(default=None,max_length=1000)
    sound: str | None = Field(default=None,max_length=1000)
    continuity: str | None = Field(default=None,max_length=1000)
class BeatPatch(BaseRevision):
    changes: BeatChanges
class ConversationNew(Strict):
    title: str = Field(default='创作讨论', min_length=1,max_length=200)
class ReferencePointer(Strict):
    type: Literal['beat','shot','revision','message']
    id: str = Field(min_length=1,max_length=128)
class MessageNew(Strict):
    content: str = Field(min_length=1,max_length=6000)
    idempotency_key: str = Field(min_length=1,max_length=128)
    references: list[ReferencePointer] = Field(default_factory=list,max_length=30)
    intent: Literal['chat','rewrite'] = 'chat'
    start_second: int | None = Field(default=None,ge=0)
    end_second: int | None = Field(default=None,ge=1)
    approval_id: str | None = None
class MemoryNew(Strict):
    scope: Literal['project','user'] = 'project'
    project_id: str | None = None
    content: str = Field(min_length=1,max_length=2000)
    source_message_ids: list[str] = Field(default_factory=list,max_length=30)
    source_revision: int | None = Field(default=None,ge=1)
class MemoryPatch(Strict):
    expected_version: int = Field(ge=1)
    content: str | None = Field(default=None,min_length=1,max_length=2000)
    status: Literal['inactive'] | None = None
class MemoryConfirm(Strict):
    expected_version: int = Field(ge=1)
class ModelPatch(Strict):
    mode: Literal['fixture','openai-compatible'] | None = None
    base_url: str | None = None
    model: str | None = Field(default=None,max_length=200)
    max_output_tokens: int | None = Field(default=None,ge=256,le=32000)
    temperature: float | None = Field(default=None,ge=0,le=2)
    input_price_per_million: float | None = Field(default=None,ge=0)
    output_price_per_million: float | None = Field(default=None,ge=0)
    price_date: str | None = Field(default=None,max_length=40)
class ApprovalNew(Strict):
    project_id: str
    max_calls: int = Field(ge=1,le=100)
    accept_unknown_cost: bool = False
    budget: float | None = Field(default=None,gt=0)
    expires_in_minutes: int = Field(default=60,ge=1,le=1440)
class ReferenceNew(Strict):
    url: str
    title: str = Field(default='',max_length=200)
    prompt: str = Field(default='',max_length=10000)
    notes: str = Field(default='',max_length=6000)
    model: str = Field(default='',max_length=200)
class FeedbackNew(Strict):
    url: str
    model: str = Field(default='',max_length=200)
    actual_prompt: str = Field(default='',max_length=20000)
    rating: int = Field(ge=1,le=5)
    notes: str = Field(default='',max_length=6000)
    revision: int = Field(ge=1)
class Character(Strict):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
class Scene(Character):
    pass
class Story(Strict):
    title: str = Field(min_length=1)
    synopsis: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    characters: list[Character] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    confirmed: bool = False
    @field_validator('characters','scenes')
    @classmethod
    def unique_ids(cls, items):
        if len({x.id for x in items})!=len(items):raise ValueError('Character and scene IDs must be unique')
        return items
class Beat(Strict):
    start_second: int = Field(ge=0)
    end_second: int = Field(ge=1)
    visual: str = Field(min_length=1)
    action: str = Field(min_length=1)
    camera: str = Field(min_length=1)
    dialogue: str = ''
    sound: str = ''
    prompt: str = ''
    character_ids: list[str]
    scene_id: str
    continuity: str = ''
