"""Optional real-browser smoke check. Run against a local server, with Playwright installed.

    python tests/browser_smoke.py

Uses an isolated demo account and saves screenshots under artifacts/.
"""
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("NUTRILENS_TEST_URL", "http://127.0.0.1:8000").rstrip("/")


def main():
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1050}, timezone_id="Asia/Makassar", locale="en-US")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE_URL, wait_until="networkidle")
        page.screenshot(path=str(output / "login-desktop.png"), full_page=True)
        page.locator('[data-action="demo"]').click()
        expect(page.locator(".calorie-card")).to_be_visible()
        page.screenshot(path=str(output / "dashboard-desktop.png"), full_page=True)
        print("Dashboard loaded.")
        # A meal written by another client (like the bot) appears without reload.
        remote_meal = context.request.post(
            f"{BASE_URL}/api/meals",
            headers={"X-Requested-With": "NutriLens"},
            data={"name": "Synced meal", "calories": 200},
        ).json()
        page.evaluate("document.activeElement.blur(); refreshProgress()")
        expect(page.get_by_role("button", name="Synced meal", exact=True)).to_be_visible()
        context.request.delete(
            f"{BASE_URL}/api/meals/{remote_meal['id']}",
            headers={"X-Requested-With": "NutriLens"},
        )
        page.evaluate("refreshProgress()")
        expect(page.get_by_role("button", name="Synced meal", exact=True)).to_have_count(0)
        page.locator('[data-action="add-meal"]').first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.locator("#meal-name").fill("Browser check lunch")
        page.locator("#meal-calories").fill("520")
        page.locator("#meal-protein").fill("32")
        page.locator("#meal-carbs").fill("58")
        page.locator("#meal-fat").fill("17")
        page.locator('#meal-form [type="submit"]').click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        expect(page.get_by_role("button", name="Browser check lunch", exact=True)).to_be_visible()
        page.get_by_role("button", name="Browser check lunch", exact=True).click()
        page.locator("#meal-calories").fill("600")
        page.locator('#meal-form [type="submit"]').click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        meal_card = page.locator(".meal-card").filter(has_text="Browser check lunch")
        expect(meal_card.locator(".meal-calories strong")).to_have_text("600")
        page.get_by_role("button", name="Browser check lunch", exact=True).click()
        page.locator('[data-action="delete-meal"]').click()
        page.locator('[data-action="confirm-delete"]').click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        expect(page.get_by_role("button", name="Browser check lunch", exact=True)).to_have_count(0)
        page.locator('[data-action="chart-days"][data-days="30"]').click()
        expect(page.locator(".chart-column")).to_have_count(30)
        page.locator('[data-action="chart-days"][data-days="7"]').click()
        expect(page.locator(".chart-column")).to_have_count(7)
        page.locator('[data-action="previous-date"]').click()
        expect(page.locator('[data-action="today"]')).to_be_visible()
        page.locator('[data-action="today"]').click()
        expect(page.locator('[data-action="today"]')).to_have_count(0)
        page.locator('[data-action="navigate"][data-page="community"]').first.click()
        expect(page.locator(".community-user").first).to_be_visible()
        page.screenshot(path=str(output / "community-desktop.png"), full_page=True)
        page.locator('[data-action="navigate"][data-page="settings"]').first.click()
        expect(page.locator("#settings-form")).to_be_visible()
        config = context.request.get(f"{BASE_URL}/api/config").json()
        expect(page.locator("#settings-form")).to_contain_text(config["ai_provider_label"])
        expect(page.locator("#settings-form")).to_contain_text(config["photo_privacy_notice"])
        page.screenshot(path=str(output / "settings-desktop.png"), full_page=True)
        page.locator("#calorie-goal").fill("2300")
        page.locator('[name="share_progress"]').uncheck()
        expect(page.locator('[name="share_meals"]')).to_be_disabled()
        page.locator('#settings-form [type="submit"]').click()
        expect(page.locator(".toast")).to_contain_text("saved")
        expect(page.locator("#calorie-goal")).to_have_value("2300")
        page.locator("#goal-mode").select_option("bulk")
        page.locator("#maintenance-calories").fill("2400")
        page.locator("#calorie-adjustment").fill("350")
        expect(page.locator("#calorie-goal")).to_have_value("2750")
        expect(page.locator("#calorie-goal")).to_have_attribute("readonly", "")
        page.locator('#settings-form [type="submit"]').click()
        expect(page.locator('#settings-form [type="submit"]')).to_be_enabled()
        expect(page.locator("#goal-mode")).to_have_value("bulk")
        assert context.request.get(f"{BASE_URL}/api/me").json()["daily_calorie_goal"] == 2750
        page.locator("#goal-mode").select_option("deficit")
        expect(page.locator("#calorie-goal")).to_have_value("2050")
        expect(page.locator("#eating-window-start")).to_be_disabled()
        page.locator('[name="fasting_enabled"]').check()
        page.locator("#eating-window-start").fill("22:00")
        page.locator("#eating-window-end").fill("06:00")
        expect(page.locator("#window-duration")).to_contain_text("16h fasting · 8h eating")
        page.locator('[name="fasting_reminders"]').check()
        page.locator("#fasting-reminder-minutes").fill("15")
        page.locator('[name="remind_window_open"]').uncheck()
        page.locator('#settings-form [type="submit"]').click()
        expect(page.locator('#settings-form [type="submit"]')).to_be_enabled()
        expect(page.locator("#goal-mode")).to_have_value("deficit")
        expect(page.locator("#eating-window-end")).to_have_value("06:00")
        saved = context.request.get(f"{BASE_URL}/api/me").json()
        assert saved["daily_calorie_goal"] == 2050 and saved["fasting_enabled"]
        assert saved["fasting_reminders"] and saved["fasting_reminder_minutes"] == 15
        assert not saved["remind_window_open"] and saved["remind_window_close"]
        page.screenshot(path=str(output / "planning-settings-desktop.png"), full_page=True)
        with page.expect_download() as download_info:
            page.get_by_role("link", name="Export meals as CSV").click()
        assert download_info.value.suggested_filename == "nutrilens-meals.csv"
        page.locator('[data-action="navigate"][data-page="overview"]').first.click()
        expect(page.locator(".calorie-card")).to_be_visible()
        expect(page.locator(".plan-grid")).to_contain_text("Calorie deficit")
        expect(page.locator(".plan-grid")).to_contain_text("2,050")
        expect(page.locator(".fasting-card")).to_contain_text("16h fast / 8h eat")
        expect(page.locator(".fasting-card")).to_contain_text("22:00–06:00")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "dashboard-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
        page.locator(".mobile-add").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.locator('[data-action="meal-tab"][data-tab="photo"]').click()
        expect(page.locator('#meal-form [type="submit"]')).to_be_disabled()
        expect(page.locator(".inline-note")).to_contain_text("Create your own account")
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
        page.locator('.mobile-nav [data-page="settings"]').click()
        expect(page.locator("#settings-form")).to_be_visible()
        page.screenshot(path=str(output / "planning-settings-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile settings overflow"
        page.locator('[name="fasting_enabled"]').uncheck()
        expect(page.locator("#fasting-reminder-minutes")).to_be_disabled()
        page.locator('#settings-form [type="submit"]').click()
        expect(page.locator('#settings-form [type="submit"]')).to_be_enabled()
        assert not context.request.get(f"{BASE_URL}/api/me").json()["fasting_enabled"]
        page.locator('[data-action="logout"]').last.click()
        expect(page.locator("#auth-form")).to_be_visible()
        page.locator('[data-action="auth-tab"][data-tab="register"]').click()
        expect(page.locator("#auth-password")).to_have_attribute("minlength", "10")
        page.screenshot(path=str(output / "register-mobile.png"), full_page=True)
        assert not errors, errors
        print("Browser checks passed: meal CRUD, charts, dates, calorie plans, fasting settings, sharing, CSV, mobile layouts, and logout.")
        browser.close()


if __name__ == "__main__":
    main()
