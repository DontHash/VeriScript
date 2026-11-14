package com.veriscript.veriscript_mobile

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
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
        // Progress notification that keeps long batches alive (ProcessingService).
        MethodChannel(engine.dartExecutor.binaryMessenger, "veriscript/background")
            .setMethodCallHandler { call, result ->
                val title = call.argument<String>("title") ?: "VeriScript"
                val text = call.argument<String>("text") ?: ""
                val permille = call.argument<Int>("permille") ?: -1
                when (call.method) {
                    "start" -> {
                        askForNotificationsOnce()
                        ProcessingService.start(applicationContext, title, text, permille)
                        result.success(null)
                    }
                    "update" -> {
                        ProcessingService.update(applicationContext, title, text, permille)
                        result.success(null)
                    }
                    "stop" -> {
                        ProcessingService.stop(applicationContext)
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            }
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
    /** Android 13+: progress notifications need permission; ask once. */
    private fun askForNotificationsOnce() {
        if (Build.VERSION.SDK_INT < 33) return
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        val prefs = getSharedPreferences("veriscript_native", MODE_PRIVATE)
        if (prefs.getBoolean("asked_notifications", false)) return
        prefs.edit().putBoolean("asked_notifications", true).apply()
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 41)
    }

    override fun onDestroy() {
        // The work lives in this engine; once it is gone there is nothing to keep alive.
        ProcessingService.stop(applicationContext)
        cancelled.set(true)
        worker.execute { rapidOcr?.close(); rapidOcr = null }
        worker.shutdown()
        super.onDestroy()
    }
}
