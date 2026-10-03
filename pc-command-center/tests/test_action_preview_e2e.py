"""Drive the terminal confirmation UI, checking review content and execution gates."""
import asyncio
import sys
from textual.app import App
from textual.widgets import Button, Static
from pcctl.core.run import Step, py_step
from pcctl.core.action_preview import review, describe
from pcctl.ui.widgets import ConfirmScreen


def test_preview_has_prerequisites_effects_and_rollback(tmp_path):
    step=Step('Example',[sys.executable,'-V'],cwd=str(tmp_path),expected_change='Change setting',prerequisites=('Back up settings',),rollback='Restore settings')
    assert review([step])['ready']
    assert all(x in describe([step]) for x in ('Change setting','Back up settings','Restore settings'))


def test_missing_command_disables_execution_in_real_dialog():
    async def go():
        app=App()
        async with app.run_test(size=(120,45)) as pilot:
            app.push_screen(ConfirmScreen('Preview',[Step('Missing',['pc-test-missing-command'])]))
            await pilot.pause();assert app.screen.query_one('#yes',Button).disabled
            assert 'MISSING' in str(app.screen.query_one('#action-preview',Static).render())
            await pilot.click('#no');await pilot.pause();assert not isinstance(app.screen,ConfirmScreen)
    asyncio.run(go())


def test_cancelled_preview_has_no_side_effects(tmp_path):
    target=tmp_path/'not-created'
    async def go():
        app=App()
        async with app.run_test(size=(120,45)) as pilot:
            app.push_screen(ConfirmScreen('Review',[Step('Create',[sys.executable,'-c',f'open({str(target)!r},"w").close()'],rollback='Delete created file')]))
            await pilot.pause();assert not app.screen.query_one('#yes',Button).disabled
            await pilot.click('#no');assert not target.exists()
    asyncio.run(go())


def test_internal_actions_and_optional_tools_are_not_blocked():
    assert review([py_step('Internal',lambda:'done','Run internal action')])['ready']
    assert review([Step('Optional',['pc-test-missing-command'],optional=True)])['ready']
