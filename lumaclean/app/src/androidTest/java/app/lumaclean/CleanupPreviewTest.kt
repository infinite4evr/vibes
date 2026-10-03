package app.lumaclean
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.lumaclean.core.TaskState
import app.lumaclean.data.*
import app.lumaclean.ui.components.*
import app.lumaclean.ui.nav.*
import app.lumaclean.ui.screens.CleanScreen
import app.lumaclean.ui.theme.LumaTheme
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
@RunWith(AndroidJUnit4::class)
class CleanupPreviewTest {
    @get:Rule val ui=createComposeRule()
    @Test fun realScanPreviewCancelThenConfirmDeletesReviewedItem(){
        val app=ApplicationProvider.getApplicationContext<LumaApp>();val c=app.container
        val file=File(app.cacheDir,"cleanup-preview-fixture.tmp").apply{writeText("disposable test bytes")}
        try{
            c.junkTask.restart();ui.waitUntil(30_000){c.junkTask.state.value is TaskState.Done}
            val found=c.junkTask.value!!.groups.flatMap{it.items}.first{it.path==file.path}
            c.junkTask.update{it.copy(groups=listOf(JunkGroup(JunkKind.APP_CACHE,listOf(found))))}
            ui.setContent{LumaTheme(c.settings.current){CompositionLocalProvider(LocalContainer provides c,LocalNavigator provides Navigator(Tab.CLEAN)){CleanScreen()}}}
            ui.onNodeWithText("Clean",useUnmergedTree=true).performClick()
            ui.onNodeWithText("Why: Temporary files this app made",substring=true).assertExists()
            ui.onNodeWithText(file.path,substring=true).assertExists();ui.onNodeWithText("This cannot be undone.",substring=true).assertExists()
            ui.onNodeWithText("Cancel").performClick();assertTrue(file.exists())
            ui.onNodeWithText("Clean",useUnmergedTree=true).performClick();ui.onAllNodesWithText("Clean").onLast().performClick()
            ui.waitUntil(10_000){!file.exists()};assertFalse(file.exists())
        }finally{file.delete()}
    }
}
