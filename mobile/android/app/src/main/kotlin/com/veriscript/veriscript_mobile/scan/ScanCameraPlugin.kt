package com.veriscript.veriscript_mobile.scan

import android.content.Context
import android.os.Build
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Phase 0 native entry point. It exposes read-only camera capabilities so the
 * diagnostics screen can verify the device before the CameraX session exists.
 */
class ScanCameraPlugin : FlutterPlugin, MethodChannel.MethodCallHandler {
    private lateinit var context: Context
    private lateinit var channel: MethodChannel

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        channel = MethodChannel(binding.binaryMessenger, "veriscript/scan_camera")
        channel.setMethodCallHandler(this)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel.setMethodCallHandler(null)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "getCapabilities" -> {
                try {
                    result.success(ScanCapabilityProbe.probe(context))
                } catch (error: Exception) {
                    result.error("CAPABILITY_PROBE", error.message ?: "Camera probe failed.", null)
                }
            }
            "getDiagnostics" -> {
                result.success(
                    mapOf(
                        "sdk" to Build.VERSION.SDK_INT,
                        "device" to Build.MODEL,
                        "manufacturer" to Build.MANUFACTURER,
                        "probeVersion" to 1,
                    ),
                )
            }
            else -> result.notImplemented()
        }
    }
}
