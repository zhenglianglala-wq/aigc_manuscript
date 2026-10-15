from typing import Literal,Annotated
from pydantic import Field,field_validator,StringConstraints
from backend.schemas import Strict,BaseRevision

class PhotoBrief(Strict):
    description: str = Field(min_length=1,max_length=6000)
    style: str = Field(default='写实摄影',min_length=1,max_length=200)
    aspect_ratio: Literal['1:1','3:2','2:3'] = '1:1'
    must_include: list[str] = Field(default_factory=list,max_length=30)
    must_avoid: list[str] = Field(default_factory=list,max_length=30)
    @field_validator('must_include','must_avoid')
    @classmethod
    def bounded_constraints(cls,values):
        if any(not v or len(v)>300 for v in values):raise ValueError('约束必须非空且最多300字符')
        return values
class PhotoProjectNew(Strict):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    brief: PhotoBrief
class PhotoProjectPatch(BaseRevision):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    brief: PhotoBrief | None = None
class PhotoPrompt(Strict):
    subject: str = Field(min_length=1,max_length=3000)
    environment: str = Field(min_length=1,max_length=3000)
    composition: str = Field(min_length=1,max_length=2000)
    lighting: str = Field(min_length=1,max_length=2000)
    camera: str = Field(default='自然透视，摄影镜头',max_length=2000)
    style: str = Field(default='写实摄影',max_length=2000)
    color: str = Field(min_length=1,max_length=2000)
    mood: str = Field(min_length=1,max_length=2000)
    details: str = Field(default='',max_length=4000)
    negative_constraints: list[str] = Field(default_factory=list,max_length=30)
    compiled_prompt: str = ''
    confirmed: bool = False
    generation_mode: Literal['fixture','openai-compatible'] = 'fixture'
class PhotoPromptChanges(Strict):
    subject: str | None = Field(default=None,min_length=1,max_length=3000)
    environment: str | None = Field(default=None,min_length=1,max_length=3000)
    composition: str | None = Field(default=None,min_length=1,max_length=2000)
    lighting: str | None = Field(default=None,min_length=1,max_length=2000)
    camera: str | None = Field(default=None,min_length=1,max_length=2000)
    style: str | None = Field(default=None,min_length=1,max_length=2000)
    color: str | None = Field(default=None,min_length=1,max_length=2000)
    mood: str | None = Field(default=None,min_length=1,max_length=2000)
    details: str | None = Field(default=None,max_length=4000)
    negative_constraints: list[str] | None = Field(default=None,max_length=30)
class PhotoPromptPatch(BaseRevision):
    changes: PhotoPromptChanges
class PhotoPromptRun(BaseRevision):
    idempotency_key: str = Field(min_length=1,max_length=128)
    instruction: str = Field(default='',max_length=6000)
    approval_id: str | None = None
class PhotoImageRun(BaseRevision):
    direct_prompt: Annotated[str,StringConstraints(strip_whitespace=False,min_length=1,max_length=16000)] | None = None
    confirm_direct_prompt: bool = False
    @field_validator('direct_prompt')
    @classmethod
    def nonblank_direct_prompt(cls,value):
        if value is not None and not value.strip():raise ValueError('直接Prompt不能只有空白')
        return value
    idempotency_key: str = Field(min_length=1,max_length=128)
    approval_id: str | None = None
class PhotoImageSettings(Strict):
    mode: Literal['fixture','openai-compatible'] | None = None
    base_url: str | None = Field(default=None,max_length=2000)
    model: str | None = Field(default=None,max_length=200)
    size: Literal['1024x1024','1536x1024','1024x1536'] | None = None
    response_format: Literal['auto','b64_json','aliyun_url'] | None = None
    estimated_price_per_image: float | None = Field(default=None,ge=0)
    price_date: str | None = Field(default=None,max_length=40)
class PhotoApprovalNew(Strict):
    expected_model_binding: dict[str,str|float|None] | None = Field(default=None,max_length=5)
    photo_project_id: str
    purpose: Literal['prompt','image']
    max_calls: int = Field(ge=1,le=100)
    accept_unknown_cost: bool = False
    budget: float | None = Field(default=None,gt=0)
    expires_in_minutes: int = Field(default=60,ge=1,le=1440)

class PhotoRecoveryRun(Strict):
    idempotency_key: str = Field(min_length=1,max_length=128)
