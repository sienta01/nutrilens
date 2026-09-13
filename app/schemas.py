from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Choose a valid IANA time zone, such as Asia/Makassar.")
    return value


Password = Annotated[str, StringConstraints(strip_whitespace=False)]


class Register(InputModel):
    email: EmailStr = Field(max_length=254)
    password: Password = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=60)
    timezone: str = "UTC"
    _zone = field_validator("timezone")(validate_timezone)


class Login(InputModel):
    email: EmailStr = Field(max_length=254)
    password: Password = Field(min_length=1, max_length=128)


class SettingsUpdate(InputModel):
    display_name: str | None = Field(None, min_length=1, max_length=60)
    daily_calorie_goal: int | None = Field(None, ge=1, le=20000)
    protein_goal: int | None = Field(None, ge=1, le=2000)
    carbs_goal: int | None = Field(None, ge=1, le=4000)
    fat_goal: int | None = Field(None, ge=1, le=2000)
    timezone: str | None = None
    share_progress: bool | None = None
    share_meals: bool | None = None
    goal_mode: Literal["custom", "maintain", "bulk", "deficit"] | None = None
    maintenance_calories: int | None = Field(None, ge=1, le=20000)
    calorie_adjustment: int | None = Field(None, ge=0, le=2000)
    fasting_enabled: bool | None = None
    eating_window_start: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    eating_window_end: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    fasting_reminders: bool | None = None
    remind_window_open: bool | None = None
    remind_window_close: bool | None = None
    fasting_reminder_minutes: int | None = Field(None, ge=0, le=120)

    @model_validator(mode="after")
    def reject_null(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Settings cannot be null.")
        if self.timezone is not None:
            validate_timezone(self.timezone)
        return self


MealType = Literal["breakfast", "lunch", "dinner", "snack"]


def validate_logged_at(value: datetime | None) -> datetime | None:
    if value is not None and not 1970 <= value.year <= 2100:
        raise ValueError("Meal dates must be between 1970 and 2100.")
    return value


class MealCreate(InputModel):
    name: str = Field(min_length=1, max_length=120)
    calories: float = Field(ge=0, le=20000)
    protein: float = Field(0, ge=0, le=2000)
    carbs: float = Field(0, ge=0, le=4000)
    fat: float = Field(0, ge=0, le=2000)
    meal_type: MealType = "snack"
    logged_at: datetime | None = None
    notes: str = Field("", max_length=2000)
    _logged_date = field_validator("logged_at")(validate_logged_at)


class MealUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    calories: float | None = Field(None, ge=0, le=20000)
    protein: float | None = Field(None, ge=0, le=2000)
    carbs: float | None = Field(None, ge=0, le=4000)
    fat: float | None = Field(None, ge=0, le=2000)
    meal_type: MealType | None = None
    logged_at: datetime | None = None
    notes: str | None = Field(None, max_length=2000)
    _logged_date = field_validator("logged_at")(validate_logged_at)

    @model_validator(mode="after")
    def reject_null(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Meal fields cannot be null.")
        return self
