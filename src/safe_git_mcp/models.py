from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Error(Model):
    code: str
    message: str = "Request could not be completed."


class Commit(Model):
    id: str
    date: int
    approved_paths_changed: list[str] = Field(default_factory=list)


class Change(Model):
    path: str
    change_type: str
    patch: str = ""
    binary: bool = False


class BlameLine(Model):
    line_no: int
    commit: str
    text: str


class Result(Model):
    error: Error | None = None
    commits: list[Commit] = Field(default_factory=list)
    files: list[Change] = Field(default_factory=list)
    lines: list[BlameLine] = Field(default_factory=list)
    base: str | None = None
    head: str | None = None
    commit: str | None = None
    parents: list[str] = Field(default_factory=list)
    path: str | None = None
    truncated: bool = False
