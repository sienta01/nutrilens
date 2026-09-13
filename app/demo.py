import secrets
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Meal, User
from app.security import hash_password
from app.services import to_utc


def create_demo(db: Session) -> User:
    """Create a separate, clearly marked sandbox for each demo visitor."""
    group = str(uuid4())
    users = []
    samples = [
        ("Avocado toast & eggs", 420, 21, 38, 21, "breakfast"),
        ("Grilled chicken bowl", 580, 44, 62, 18, "lunch"),
        ("Greek yogurt & berries", 185, 17, 24, 3, "snack"),
        ("Salmon with roasted vegetables", 610, 39, 48, 29, "dinner"),
        ("Overnight oats", 360, 16, 52, 11, "breakfast"),
        ("Tofu & brown rice bowl", 520, 25, 68, 16, "lunch"),
    ]
    for index, name in enumerate(["Alex Morgan", "Jamie Chen", "Sam Rivera"]):
        user = User(
            email=f"demo-{uuid4().hex}@example.com", display_name=name,
            password_hash=hash_password(secrets.token_urlsafe(32)), timezone="Asia/Makassar",
            is_demo=True, demo_group=group, share_progress=True, share_meals=index != 2,
            daily_calorie_goal=2100 if index == 0 else 2200,
        )
        db.add(user)
        db.flush()
        users.append(user)
        today = datetime.now(ZoneInfo(user.timezone)).date()
        for ago in range(30):
            if index == 2 and ago in {3, 9, 15}:
                continue
            entries = [0, 1, 2] if ago == 0 else [4 if ago % 2 else 0, 5 if ago % 3 else 1, 2, 3]
            for slot, recipe_index in enumerate(entries):
                recipe = samples[recipe_index]
                multiplier = 1 + ((ago + index) % 5 - 2) * 0.04
                meal_time = datetime.combine(today - timedelta(days=ago), time([8, 12, 15, 19][slot]))
                db.add(Meal(
                    user_id=user.id, name=recipe[0], calories=round(recipe[1] * multiplier),
                    protein=round(recipe[2] * multiplier), carbs=round(recipe[3] * multiplier),
                    fat=round(recipe[4] * multiplier), meal_type=recipe[5],
                    logged_at=to_utc(meal_time, user), source="demo",
                    notes="Sample meal in your private demo workspace.",
                ))
    db.commit()
    return users[0]
