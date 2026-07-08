from pydantic import BaseModel, Field


class StoryBible(BaseModel):
    story_bible_id: str
    project_id: str
    world_canvas_id: str
    active_framework_id: str
    main_character_ids: list[str] = Field(default_factory=list)
    relationship_ids: list[str] = Field(default_factory=list)
    version_id: str
