from pydantic import BaseModel


class Issue(BaseModel):
    issue_id: str
    type: str
    summary: str
    related_scene_id: str
    status: str
    ask_user_when: str
