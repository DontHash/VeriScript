package com.veriscript.veriscript_mobile

import com.veriscript.veriscript_mobile.scan.ScanCameraPlugin
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : FlutterActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val cancelled = AtomicBoolean(false)
    private val busy = AtomicBoolean(false)
    private var rapidOcr: RapidOcr? = null
    override fun configureFlutterEngine(engine: FlutterEngine) {
        super.configureFlutterEngine(engine)
        engine.plugins.add(ScanCameraPlugin())
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
                        val output = if (call.method == "rapidOcr") {
                            val reader = rapidOcr ?: RapidOcr(applicationContext).also { rapidOcr = it }
                            reader.run(args, cancelled)
                        } else OfflinePages.run(call.method, args, cancelled) { done, total ->
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
        worker.execute { rapidOcr?.close(); rapidOcr = null }
        worker.shutdown()
        super.onDestroy()
    }
}
