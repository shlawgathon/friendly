from pydantic import BaseModel, Field


class DeepEnrichRequest(BaseModel):
    username: str
    instagram_url: str
    interests: list[str] = Field(default_factory=list)
    max_highlights: int = 3
    scroll_depth: int = 20


class VibeCompareRequest(BaseModel):
    username_a: str
    username_b: str
    instagram_url_a: str
    instagram_url_b: str


class VibeFingerprint(BaseModel):
    aesthetic_tags: list[str] = Field(default_factory=list)
    color_palette: list[str] = Field(default_factory=list)
    mood: str = ""
    energy: float = Field(default=0.5, ge=0.0, le=1.0)
    content_themes: list[str] = Field(default_factory=list)


class DeepInsight(BaseModel):
    type: str  # 'highlight' or 'deep_post'
    content: str = ""
    source_url: str = ""
    interests_found: list[str] = Field(default_factory=list)


class DeepEnrichResponse(BaseModel):
    username: str
    insights: list[DeepInsight] = Field(default_factory=list)
    vibe: VibeFingerprint = Field(default_factory=VibeFingerprint)
    discovered_interests: list[str] = Field(default_factory=list)
    status: str = "completed"


class VibeCompareResponse(BaseModel):
    username_a: str
    username_b: str
    similarity_score: float = 0.0
    shared_aesthetics: list[str] = Field(default_factory=list)
    shared_themes: list[str] = Field(default_factory=list)
    vibe_a: VibeFingerprint = Field(default_factory=VibeFingerprint)
    vibe_b: VibeFingerprint = Field(default_factory=VibeFingerprint)
    status: str = "completed"
