from typing import Literal, get_args

ModelName = Literal["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.7-flash",
                    "gemini-3.6-flash", "gemini-3.5-flash"]
MODEL_IDS = get_args(ModelName)
