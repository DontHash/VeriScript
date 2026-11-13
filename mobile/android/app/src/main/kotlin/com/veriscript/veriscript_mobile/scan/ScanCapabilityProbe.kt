package com.veriscript.veriscript_mobile.scan

import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.os.Build
import android.util.Size

/**
 * Read-only Phase 0 probe. It never opens the camera and never modifies 3A.
 * The result is JSON-safe for Flutter's StandardMethodCodec.
 */
object ScanCapabilityProbe {
    fun probe(context: Context): Map<String, Any?> {
        val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val cameras = manager.cameraIdList.mapNotNull { id ->
            runCatching { readCamera(manager, id) }
                .getOrElse { error -> mapOf("id" to id, "error" to (error.message ?: "probe failed")) }
        }
        val selected = cameras.firstOrNull { it["facing"] == "back" } ?: cameras.firstOrNull()
        return mapOf(
            "probeVersion" to 1,
            "device" to Build.MODEL,
            "manufacturer" to Build.MANUFACTURER,
            "sdk" to Build.VERSION.SDK_INT,
            "cameras" to cameras,
            "selected" to selected,
        )
    }

    private fun readCamera(manager: CameraManager, id: String): Map<String, Any?> {
        val c = manager.getCameraCharacteristics(id)
        val map = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val jpegSizes = map?.getOutputSizes(ImageFormat.JPEG)
            ?.sortedByDescending { it.width.toLong() * it.height.toLong() }
            ?.take(40)
            ?.map { size ->
                mapOf(
                    "width" to size.width,
                    "height" to size.height,
                    "megapixels" to round(size.width.toDouble() * size.height / 1_000_000.0),
                )
            }
            ?: emptyList()
        val capabilities = c.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)
            ?.map { capabilityName(it) }
            ?: emptyList()
        val aeRange = c.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_RANGE)
        val aeStep = c.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_STEP)
        val aeStepValue = aeStep?.toDouble() ?: 0.0
        val aeMinIndex = aeRange?.lower ?: 0
        val aeMaxIndex = aeRange?.upper ?: 0
        val active = c.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)
        val pixelArray = c.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE)
        val sensitivity = c.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
        val exposure = c.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
        return mapOf(
            "id" to id,
            "facing" to facingName(c.get(CameraCharacteristics.LENS_FACING)),
            "hardwareLevel" to hardwareLevelName(c.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)),
            "capabilities" to capabilities,
            "manualSensor" to capabilities.contains("MANUAL_SENSOR"),
            "manualPostProcessing" to capabilities.contains("MANUAL_POST_PROCESSING"),
            "raw" to capabilities.contains("RAW"),
            "flash" to (c.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true),
            "sensorOrientation" to (c.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0),
            // Camera2 reports an index range; expose both the EV range and the
            // raw indices so the Phase 1 control loop can clamp correctly.
            "aeMin" to aeMinIndex * aeStepValue,
            "aeMax" to aeMaxIndex * aeStepValue,
            "aeMinIndex" to aeMinIndex,
            "aeMaxIndex" to aeMaxIndex,
            "aeStep" to aeStepValue,
            "afModes" to (c.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES)?.toList() ?: emptyList()),
            "awbModes" to (c.get(CameraCharacteristics.CONTROL_AWB_AVAILABLE_MODES)?.toList() ?: emptyList()),
            "focalLengths" to (c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.map { it.toDouble() } ?: emptyList()),
            "pixelArray" to pixelArray?.let { sizeMap(it) },
            "activeArray" to active?.let {
                mapOf("left" to it.left, "top" to it.top, "right" to it.right, "bottom" to it.bottom)
            },
            "sensitivityRange" to sensitivity?.let { rangeMap(it.lower, it.upper) },
            "exposureTimeRangeNs" to exposure?.let { rangeMap(it.lower, it.upper) },
            "jpegSizes" to jpegSizes,
        )
    }

    private fun sizeMap(size: Size) = mapOf("width" to size.width, "height" to size.height)
    private fun rangeMap(lower: Number, upper: Number) = mapOf("min" to lower, "max" to upper)
    private fun round(value: Double) = (value * 100).toInt() / 100.0

    private fun facingName(value: Int?): String = when (value) {
        CameraCharacteristics.LENS_FACING_BACK -> "back"
        CameraCharacteristics.LENS_FACING_FRONT -> "front"
        CameraCharacteristics.LENS_FACING_EXTERNAL -> "external"
        else -> "unknown"
    }

    private fun hardwareLevelName(value: Int?): String = when (value) {
        CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY -> "LEGACY"
        CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED -> "LIMITED"
        CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_FULL -> "FULL"
        CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_3 -> "LEVEL_3"
        CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL -> "EXTERNAL"
        else -> "UNKNOWN"
    }

    private fun capabilityName(value: Int): String = when (value) {
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE -> "BACKWARD_COMPATIBLE"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR -> "MANUAL_SENSOR"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_POST_PROCESSING -> "MANUAL_POST_PROCESSING"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW -> "RAW"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_DEPTH_OUTPUT -> "DEPTH_OUTPUT"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA -> "LOGICAL_MULTI_CAMERA"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_CONSTRAINED_HIGH_SPEED_VIDEO -> "CONSTRAINED_HIGH_SPEED_VIDEO"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING -> "YUV_REPROCESSING"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_PRIVATE_REPROCESSING -> "PRIVATE_REPROCESSING"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_READ_SENSOR_SETTINGS -> "READ_SENSOR_SETTINGS"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE -> "BURST_CAPTURE"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MOTION_TRACKING -> "MOTION_TRACKING"
        else -> "CAP_$value"
    }
}
