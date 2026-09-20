from pydantic import BaseModel, Field


class GroupBody(BaseModel):
    id: str = Field(min_length=1, max_length=30)
    group_name: str = Field(min_length=1, max_length=100)


class GroupUpdateBody(BaseModel):
    group_name: str = Field(min_length=1, max_length=100)


class EmployeeBody(BaseModel):
    id: str = Field(min_length=1, max_length=30)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    group_id: str = Field(min_length=1, max_length=30)


class EmployeeUpdateBody(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    group_id: str = Field(min_length=1, max_length=30)
