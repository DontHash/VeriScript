package com.veriscript.veriscript_mobile

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : FlutterActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val cancelled = AtomicBoolean(false)
    private val busy = AtomicBoolean(false)
    override fun configureFlutterEngine(engine: FlutterEngine) {
        super.configureFlutterEngine(engine)
        val channel = MethodChannel(engine.dartExecutor.binaryMessenger, "veriscript/offline")
        channel.setMethodCallHandler { call, result ->
            if (call.method == "cancel") {
                cancelled.set(true)
                result.success(null)
            } else if (!busy.compareAndSet(false, true)) {
                result.error("BUSY", "Another page operation is running.", null)
            } else {
                cancelled.set(false)
                worker.execute {
                    try {
                        val args = call.arguments as? Map<*, *> ?: emptyMap<Any, Any>()
                        val output = OfflinePages.run(call.method, args, cancelled) { done, total ->
                            runOnUiThread { channel.invokeMethod("progress", mapOf("done" to done, "total" to total)) }
                        }
                        runOnUiThread {
                            busy.set(false)
                            result.success(output)
                        }
                    } catch (e: Exception) {
                        runOnUiThread {
                            busy.set(false)
                            result.error("PROCESSING", e.message ?: "Unable to process this file.", null)
                        }
                    }
                }
            }
        }
    }
    override fun onDestroy() {
        cancelled.set(true)
        worker.shutdown()
        super.onDestroy()
    }
}
