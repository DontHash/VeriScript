package com.veriscript.veriscript_mobile

import android.content.Context
import ai.onnxruntime.*
import org.json.JSONObject
import org.opencv.android.OpenCVLoader
import org.opencv.core.*
import org.opencv.imgcodecs.Imgcodecs
import org.opencv.imgproc.Imgproc
import java.io.File
import java.nio.FloatBuffer
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.*

/** Curved-page flattening on the phone (docs/TECH_UPGRADE_PLAN.md F1).
 *
 * UVDoc (MIT), exported to ONNX by scripts/export_uvdoc_onnx.py with its
 * weights stored as float16 (cast to float32 when loaded: 15.8 MB in the
 * APK). Port of veriscript/document/dewarp.py `predict_grid` + `apply_grid`:
 * the 45x31 grid is predicted on a 488x712 RGB copy (INTER_AREA, 0..1) and
 * stretched corner to corner over the full page with exact bilinear weights;
 * the page is then sampled bilinearly. The output keeps the page's size.
 * Sampling runs in strips of rows so the maps never hold the whole page. */
class Flattener(private val context: Context) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private var session: OrtSession? = null

    private fun session(): OrtSession = session ?: run {
        val manifest = JSONObject(context.assets.open("uvdoc/manifest.json").bufferedReader().use { it.readText() })
        val expected = manifest.getJSONObject("files")
            .getString("mobile/android/app/src/main/assets/uvdoc/uvdoc_fp16.onnx")
        val file = File(context.cacheDir, "uvdoc/$expected.onnx")
        fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        if (!file.exists() || sha(file.readBytes()) != expected) {
            val bytes = context.assets.open("uvdoc/uvdoc_fp16.onnx").use { it.readBytes() }
            require(sha(bytes) == expected) { "Damaged flattening model" }
            file.parentFile!!.mkdirs()
            file.writeBytes(bytes)
        }
        OrtSession.SessionOptions().use { options ->
            options.setIntraOpNumThreads(2)
            options.setCPUArenaAllocator(false)
            env.createSession(file.path, options)
        }.also { session = it }
    }

    /** The grid, (2, 45, 31) flattened, in [-1, 1]. */
    private fun grid(bgr: Mat): FloatArray {
        val rgb = Mat(); val small = Mat()
        try {
            Imgproc.cvtColor(bgr, rgb, Imgproc.COLOR_BGR2RGB)
            Imgproc.resize(rgb, small, Size(488.0, 712.0), 0.0, 0.0, Imgproc.INTER_AREA)
            val pixels = ByteArray(712 * 488 * 3).also { small.get(0, 0, it) }
            val input = FloatArray(pixels.size)
            val plane = 712 * 488
            for (i in 0 until plane) for (c in 0..2)
                input[c * plane + i] = (pixels[i * 3 + c].toInt() and 255) / 255f
            OnnxTensor.createTensor(env, FloatBuffer.wrap(input), longArrayOf(1, 3, 712, 488)).use { t ->
                session().run(mapOf("image" to t)).use { result ->
                    val out = (result[0] as OnnxTensor).floatBuffer
                    return FloatArray(out.remaining()).also { out.get(it) }
                }
            }
        } finally { rgb.release(); small.release() }
    }

    fun run(args: Map<*, *>, cancel: AtomicBoolean): Map<String, Any> {
        check(OpenCVLoader.initLocal()) { "OpenCV unavailable" }
        val src = Imgcodecs.imread(args["path"] as String)
        try {
            require(!src.empty()) { "Unable to read the page" }
            require(src.total() <= 30_000_000L) { "Image exceeds the 30 megapixel limit" }
            val g = grid(src)
            check(!cancel.get()) { "Operation cancelled" }
            val h = src.rows(); val w = src.cols(); val gh = 45; val gw = 31
            // align_corners=True: output pixel i sits at grid position i*(g-1)/(n-1).
            fun lo(i: Int, n: Int, g: Int): Pair<Int, Double> {
                val pos = i * ((g - 1).toDouble() / max(1, n - 1))
                val l = min(floor(pos).toInt(), g - 2)
                return l to (pos - l)
            }
            val cols = Array(w) { lo(it, w, gw) }
            val out = Mat(h, w, src.type())
            try {
                val strip = 256
                val rowX = DoubleArray(gw); val rowY = DoubleArray(gw)
                var y0 = 0
                while (y0 < h) {
                    check(!cancel.get()) { "Operation cancelled" }
                    val rows = min(strip, h - y0)
                    val mx = FloatArray(rows * w); val my = FloatArray(rows * w)
                    for (r in 0 until rows) {
                        val (ly, fy) = lo(y0 + r, h, gh)
                        for (j in 0 until gw) {
                            rowX[j] = (1 - fy) * g[ly * gw + j] + fy * g[(ly + 1) * gw + j]
                            rowY[j] = (1 - fy) * g[gh * gw + ly * gw + j] + fy * g[gh * gw + (ly + 1) * gw + j]
                        }
                        for (x in 0 until w) {
                            val (lx, fx) = cols[x]
                            val gx = (1 - fx) * rowX[lx] + fx * rowX[lx + 1]
                            val gyv = (1 - fx) * rowY[lx] + fx * rowY[lx + 1]
                            mx[r * w + x] = ((gx + 1) / 2 * (w - 1)).toFloat()
                            my[r * w + x] = ((gyv + 1) / 2 * (h - 1)).toFloat()
                        }
                    }
                    val mapX = Mat(rows, w, CvType.CV_32F); val mapY = Mat(rows, w, CvType.CV_32F)
                    val part = out.submat(y0, y0 + rows, 0, w)
                    try {
                        mapX.put(0, 0, mx); mapY.put(0, 0, my)
                        Imgproc.remap(src, part, mapX, mapY, Imgproc.INTER_LINEAR, Core.BORDER_CONSTANT, Scalar.all(0.0))
                    } finally { mapX.release(); mapY.release(); part.release() }
                    y0 += rows
                }
                val path = args["out"] as String
                check(Imgcodecs.imwrite(path, out, MatOfInt(Imgcodecs.IMWRITE_JPEG_QUALITY, 95))) { "Unable to save page" }
                return mapOf("path" to path, "width" to w, "height" to h,
                    "note" to "Flattened with the curved-page model; compare with the original before reading.")
            } finally { out.release() }
        } finally { src.release() }
    }

    override fun close() { session?.close(); session = null }
}
