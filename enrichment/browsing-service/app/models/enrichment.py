from pydantic import BaseModel, Field


class BrowseEnrichRequest(BaseModel):
    username: str
    interests: list[str] = Field(default_factory=list, max_length=3)
    location: str | None = None


class ProfileEnrichRequest(BaseModel):
    username: str
    url: str


class EventResult(BaseModel):
    title: str
    date: str
    location: str = ""
    url: str
    description: str = ""


class CommunityResult(BaseModel):
    name: str
    subscriber_count: int = 0
    description: str = ""
    url: str


class MeetupResult(BaseModel):
    name: str
    date: str = ""
    location: str = ""
    url: str
    attendees: int = 0


class BrowseEnrichResponse(BaseModel):
    username: str
    events: list[EventResult] = Field(default_factory=list)
    communities: list[CommunityResult] = Field(default_factory=list)
    meetups: list[MeetupResult] = Field(default_factory=list)
    status: str = "completed"
