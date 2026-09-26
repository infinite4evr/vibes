package app.lumaclean.core

import android.os.SystemClock
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** The lifecycle of one background job. [value] is the latest result, kept while a refresh runs. */
sealed interface TaskState<out T> {
    val value: T?

    data object Idle : TaskState<Nothing> {
        override val value: Nothing? get() = null
    }

    data class Running<T>(val progress: Float?, val message: String, override val value: T?) : TaskState<T>

    data class Done<T>(override val value: T, val finishedAt: Long) : TaskState<T>

    data class Failed<T>(val message: String, override val value: T?) : TaskState<T>
}

/** Handed to long work so it can report what it is doing. Updates are throttled for the UI. */
class Progress(private val onReport: (Float?, String) -> Unit) {
    private var last = 0L

    fun report(fraction: Float?, message: String, force: Boolean = false) {
        val now = SystemClock.uptimeMillis()
        if (force || now - last >= 80) {
            last = now
            onReport(fraction?.coerceIn(0f, 1f), message)
        }
    }

    /** A view of this progress that maps 0..1 into [from]..[to] of the parent. */
    fun slice(from: Float, to: Float) = Progress { f, m -> onReport(f?.let { from + (to - from) * it }, m) }

    companion object {
        val None = Progress { _, _ -> }
    }
}

/**
 * A restartable, cancellable background job whose state outlives any screen.
 * Screens only observe [state]; the work runs in the app-wide scope.
 */
class Task<T>(
    private val scope: CoroutineScope,
    private val work: suspend Progress.() -> T,
) {
    private val _state = MutableStateFlow<TaskState<T>>(TaskState.Idle)
    val state: StateFlow<TaskState<T>> = _state.asStateFlow()

    private var job: Job? = null
    private var generation = 0
    private var lastDone: TaskState.Done<T>? = null

    val isRunning: Boolean get() = job?.isActive == true
    val value: T? get() = _state.value.value

    /** Starts the job unless it is already running or has a result. */
    fun ensure() {
        val s = _state.value
        if (s is TaskState.Idle || s is TaskState.Failed) start()
    }

    /** Starts the job unless it is already running. */
    fun start() {
        if (!isRunning) restart()
    }

    fun restart() {
        job?.cancel()
        val gen = ++generation
        val previous = _state.value.value
        _state.value = TaskState.Running(null, "Starting…", previous)
        job = scope.launch {
            val progress = Progress { f, m -> if (gen == generation) _state.value = TaskState.Running(f, m, previous) }
            try {
                val result = withContext(Dispatchers.IO) { progress.work() }
                if (gen == generation) {
                    val done = TaskState.Done(result, System.currentTimeMillis())
                    lastDone = done
                    _state.value = done
                }
            } catch (e: CancellationException) {
                if (gen == generation) _state.value = lastDone ?: TaskState.Idle
                throw e
            } catch (t: Throwable) {
                if (gen == generation) _state.value = TaskState.Failed(t.message ?: t.javaClass.simpleName, previous)
            }
        }
    }

    fun cancel() {
        job?.cancel()
    }

    /** Adjusts the finished result in place, e.g. after the user deleted some of it. */
    fun update(transform: (T) -> T) {
        val s = _state.value
        if (s is TaskState.Done) {
            val done = s.copy(value = transform(s.value))
            lastDone = done
            _state.value = done
        }
    }

    fun reset() {
        job?.cancel()
        generation++
        lastDone = null
        _state.value = TaskState.Idle
    }
}

data class UiMessage(
    val text: String,
    val actionLabel: String? = null,
    val action: (() -> Unit)? = null,
)

data class OperationState(val title: String, val progress: Float?, val message: String)

/**
 * One blocking user action at a time (clean, delete, move, compress…), shown as a progress
 * dialog by the root screen. It keeps running if the user leaves the screen.
 */
class Operations(
    private val scope: CoroutineScope,
    private val messages: MutableSharedFlow<UiMessage>,
) {
    private val _state = MutableStateFlow<OperationState?>(null)
    val state: StateFlow<OperationState?> = _state.asStateFlow()
    private var job: Job? = null

    fun run(title: String, work: suspend Progress.() -> UiMessage?) {
        if (job?.isActive == true) {
            messages.tryEmit(UiMessage("Please wait for the current action to finish"))
            return
        }
        _state.value = OperationState(title, null, "Preparing…")
        job = scope.launch {
            try {
                val progress = Progress { f, m -> _state.value = OperationState(title, f, m) }
                val result = withContext(Dispatchers.IO) { progress.work() }
                result?.let { messages.tryEmit(it) }
            } catch (e: CancellationException) {
                messages.tryEmit(UiMessage("$title cancelled"))
            } catch (t: Throwable) {
                messages.tryEmit(UiMessage("$title failed: ${t.message ?: t.javaClass.simpleName}"))
            } finally {
                _state.value = null
            }
        }
    }

    fun cancel() {
        job?.cancel()
    }
}
