"""Terminal app: every error opens the error dialog with "Create GitHub issue"."""
import asyncio

import pytest

pytest.importorskip("textual")

from pcctl.core.bugreport import is_error_text  # noqa: E402
from pcctl.core.run import Step  # noqa: E402
from pcctl.ui.app import PcApp  # noqa: E402
from pcctl.ui.widgets import ErrorScreen, TaskScreen  # noqa: E402


def test_is_error_text():
    assert is_error_text("Couldn't change it: denied")
    assert is_error_text("Error: boom")
    assert is_error_text("Upload failed")
    assert not is_error_text("Checking firmware…")
    assert not is_error_text("Automatic security updates are already on.")


def test_error_notification_opens_dialog_and_repeats_fold():
    async def go():
        app = PcApp()
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.notify("Couldn't find ubuntu-setup/setup.sh.", severity="warning")
            await pilot.pause()
            assert isinstance(app.screen, ErrorScreen)
            assert app.screen.query_one("#issue").label.plain == "Create GitHub issue"
            assert app.screen.rep.url().startswith("https://github.com/infinite4evr/vibes/issues/new?")
            app.notify("Something else failed")
            await pilot.pause()
            assert app.screen.count == 2
            app.screen.dismiss(None)
            await pilot.pause()
            app.notify("All good.")
            await pilot.pause()
            assert not isinstance(app.screen, ErrorScreen)
    asyncio.run(go())


def test_failed_action_opens_dialog():
    async def go():
        app = PcApp()
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.push_screen(TaskScreen("Broken thing", [Step("Fail on purpose", ["bash", "-c", "echo nope; exit 3"])]))
            for _ in range(50):
                await pilot.pause(0.05)
                if isinstance(app.screen, ErrorScreen):
                    break
            assert isinstance(app.screen, ErrorScreen)
            assert "Fail on purpose" in app.screen.rep.error and "nope" in app.screen.rep.error
    asyncio.run(go())
