from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

os.environ["MY_LIST"] = "a,b,c"

class TestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8")
    my_list: str | list[str]

    @field_validator("my_list", mode="before")
    @classmethod
    def split_it(cls, v):
        if isinstance(v, str):
            return v.split(",")
        return v

print(TestSettings().my_list)
