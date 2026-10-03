package app.lumaclean
import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.lumaclean.core.Progress
import app.lumaclean.data.*
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID
@RunWith(AndroidJUnit4::class)
class FileSafetyTest {
    private fun fixture(test:(Context,File,RecycleBin,FileOps)->Unit) {
        val app=ApplicationProvider.getApplicationContext<Context>();val id=UUID.randomUUID().toString()
        val root=File(app.getExternalFilesDir(null),"safety-$id").apply{mkdirs()}
        val ctx=object:ContextWrapper(app){override fun getFilesDir()=File(root,"journal").apply{mkdirs()}}
        val bin=RecycleBin(ctx,".LumaClean-Test-$id")
        try{test(ctx,root,bin,FileOps(ctx,FileIndexRepository(),bin))}finally{bin.deleteForever(bin.items.value.map{it.id});root.deleteRecursively()}
    }
    @Test fun cancelledBatchCanRestoreMovedFiles()=fixture {ctx,root,bin,ops->
        val a=File(root,"a.txt").apply{writeText("first")};val b=File(root,"b.txt").apply{writeText("second")}
        runBlocking{val job=launch{val self=currentCoroutineContext()[Job]!!;ops.remove(listOf(a.path,b.path),true,Progress{_,_->self.cancel()})};job.join();assertTrue(job.isCancelled)}
        val reopened=RecycleBin(ctx,File(bin.items.value.single().binPath).parentFile!!.name)
        assertFalse(a.exists());assertTrue(b.exists());reopened.restore(reopened.items.value.map{it.id});assertEquals("first",a.readText())
    }
    @Test fun disconnectedStorageKeepsRestoreRecord()=fixture{ctx,root,bin,_->
        val src=File(root,"card.txt").apply{writeText("keep me")};val item=bin.moveIn(src.path,src.length())!!
        val bytes=File(item.binPath);val hidden=File(root,"disconnected.bin");assertTrue(bytes.renameTo(hidden))
        bin.reconcile();assertFalse(bin.available(item));bin.restore(listOf(item.id));bin.deleteForever(listOf(item.id));bin.purgeOlderThan(0)
        assertEquals(1,RecycleBin(ctx,bytes.parentFile!!.name).items.value.size)
        assertTrue(hidden.renameTo(bytes));assertEquals(listOf(src.path),bin.restore(listOf(item.id)));assertEquals("keep me",src.readText())
    }
    @Test fun cancelledCopyLeavesNoPartialDestination()=fixture{_,root,_,ops->
        val src=File(root,"large.bin").apply{writeBytes(ByteArray(2*1024*1024){7})};val dest=File(root,"dest").apply{mkdirs()}
        runBlocking{val job=launch{val self=currentCoroutineContext()[Job]!!;ops.transfer(listOf(src.path),dest.path,false,Progress{_,_->self.cancel()})};job.join();assertTrue(job.isCancelled)}
        assertEquals(2L*1024*1024,src.length());assertTrue(dest.listFiles()!!.isEmpty())
    }
    @Test fun changingSourceFailsWithoutPublishingCopy()=fixture{_,root,_,ops->
        val src=File(root,"changing.bin").apply{writeBytes(ByteArray(1024*1024){3})};val dest=File(root,"dest").apply{mkdirs()};var changed=false
        val result=runBlocking{ops.transfer(listOf(src.path),dest.path,false,Progress{_,_->if(!changed){changed=true;src.appendBytes(byteArrayOf(5))}})}
        assertEquals(0,result.done);assertEquals(1,result.failed);assertTrue(src.exists());assertTrue(dest.listFiles()!!.isEmpty())
    }
}
