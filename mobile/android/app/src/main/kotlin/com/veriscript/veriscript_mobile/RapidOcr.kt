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

/** Bundled desktop PP-OCR weights. BGR / DB / perspective crops / CTC, no server.
 * The optional desktop PyTorch letterpress reader is deliberately not included.
 * Sessions belong to the activity's single worker and are closed on that worker. */
class RapidOcr(private val context: Context) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val sessions = mutableMapOf<String, OrtSession>()
    private val manifest by lazy {
        JSONObject(context.assets.open("rapidocr/manifest.json").bufferedReader().use { it.readText() })
    }
    private class Arena : AutoCloseable {
        private val mats = mutableListOf<Mat>()
        fun own(m: Mat): Mat { mats.add(m); return m }
        fun mat() = own(Mat())
        override fun close() { mats.asReversed().forEach { it.release() } }
    }
    private fun check(cancel: AtomicBoolean) = check(!cancel.get()) { "Operation cancelled" }
    private fun session(name: String): OrtSession = sessions.getOrPut(name) {
        val rows = manifest.getJSONArray("models")
        val expected = (0 until rows.length()).map { rows.getJSONObject(it) }
            .first { it.getString("file") == name }.getString("sha256")
        val file = File(context.cacheDir, "rapidocr/$expected.onnx")
        fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        if (!file.exists() || sha(file.readBytes()) != expected) {
            val bytes = context.assets.open("rapidocr/$name").use { it.readBytes() }
            require(sha(bytes) == expected) { "Damaged OCR model: $name" }
            file.parentFile!!.mkdirs()
            file.writeBytes(bytes)
        }
        OrtSession.SessionOptions().use { options ->
            options.setIntraOpNumThreads(2)
            options.setInterOpNumThreads(1)
            // Line widths and page sizes change on every call. With the CPU
            // arena and memory patterns on, ONNX Runtime keeps the largest
            // buffers it has seen; on a 2.5 GB emulator the app grew past
            // 1.7 GB and the low-memory killer stopped it (2026-11-15
            // baseline). Off: 16 pages peaked at 1.0 GB. The arena is faster
            // per read but reached 1.38 GB on 3 pages even with bucketed
            // widths, so this preview reader trades speed for not being killed.
            options.setCPUArenaAllocator(false)
            options.setMemoryPatternOptimization(false)
            env.createSession(file.path, options)
        }
    }
    private fun tensor(image: Mat, height: Int, width: Int, arena: Arena): FloatArray {
        val resized = arena.mat()
        Imgproc.resize(image, resized, Size(width.toDouble(), height.toDouble()))
        val pixels = ByteArray(height * width * 3); resized.get(0, 0, pixels)
        return FloatArray(pixels.size).also { out ->
            for (i in 0 until height * width) for (c in 0..2)
                out[c * height * width + i] = (pixels[i * 3 + c].toInt() and 255) / 127.5f - 1f
        }
    }
    private fun infer(session: OrtSession, values: FloatArray, shape: LongArray): Pair<FloatArray, LongArray> =
        inferWith(session, values, shape) { buffer, dims ->
            Pair(FloatArray(buffer.remaining()).also { buffer.get(it) }, dims)
        }

    /** Runs [session] and hands [read] the output without copying it to the
     * Java heap (recognizer outputs are batch x steps x dictionary floats). */
    private fun <R> inferWith(session: OrtSession, values: FloatArray, shape: LongArray,
                              read: (FloatBuffer, LongArray) -> R): R {
        OnnxTensor.createTensor(env, FloatBuffer.wrap(values), shape).use { input ->
            session.run(mapOf(session.inputNames.first() to input)).use { result ->
                val output = result[0] as OnnxTensor
                return read(output.floatBuffer, (output.info as TensorInfo).shape)
            }
        }
    }
    private fun corners(rect: RotatedRect): Array<Point> {
        val points = Array(4) { Point() }; rect.points(points)
        val x = points.sortedBy { it.x }
        val left = x.take(2).sortedBy { it.y }; val right = x.drop(2).sortedBy { it.y }
        return arrayOf(left[0], right[0], right[1], left[1])
    }
    private fun detect(image: Mat, cancel: AtomicBoolean): List<Array<Point>> = Arena().use { a ->
        val ratio = max(1.0, 736.0 / min(image.rows(), image.cols()))
        // numpy.round uses ties-to-even; rint matches it.
        val h = max(32, Math.rint((image.rows() * ratio).toInt() / 32.0).toInt() * 32)
        val w = max(32, Math.rint((image.cols() * ratio).toInt() / 32.0).toInt() * 32)
        require(h.toLong() * w <= 8_000_000L) { "Page is too narrow for OCR; crop it first" }
        val (prob, shape) = infer(session("PP-OCRv6_det_small.onnx"), tensor(image, h, w, a),
            longArrayOf(1, 3, h.toLong(), w.toLong()))
        check(cancel)
        val ph = shape[2].toInt(); val pw = shape[3].toInt()
        val map = a.own(Mat(ph, pw, CvType.CV_32F)); map.put(0, 0, prob)
        val binary = a.own(Mat(ph, pw, CvType.CV_8U))
        binary.put(0, 0, ByteArray(prob.size) { if (prob[it] > .3f) 255.toByte() else 0 })
        val kernel = a.own(Mat.ones(2, 2, CvType.CV_8U)); Imgproc.dilate(binary, binary, kernel)
        val contours = mutableListOf<MatOfPoint>()
        Imgproc.findContours(binary, contours, a.mat(), Imgproc.RETR_LIST, Imgproc.CHAIN_APPROX_SIMPLE)
        val boxes = mutableListOf<Array<Point>>()
        try {
            for (contour in contours.take(1000)) {
                check(cancel)
                Arena().use { local ->
                    val curve = local.own(MatOfPoint2f(*contour.toArray())) as MatOfPoint2f
                    val rect = Imgproc.minAreaRect(curve)
                    if (min(rect.size.width, rect.size.height) < 3) return@use
                    val points = corners(rect).map { Point(it.x.toInt().toDouble(), it.y.toInt().toDouble()) }.toTypedArray()
                    val mask = local.own(Mat.zeros(ph, pw, CvType.CV_8U))
                    val polygon = local.own(MatOfPoint(*points)) as MatOfPoint
                    Imgproc.fillPoly(mask, listOf(polygon), Scalar(1.0))
                    if (Core.mean(map, mask).`val`[0] < .5) return@use
                    val area = abs(Imgproc.contourArea(polygon))
                    val boundary = local.own(MatOfPoint2f(*points)) as MatOfPoint2f
                    val perimeter = Imgproc.arcLength(boundary, true)
                    if (perimeter <= 0) return@use
                    // Rectangle DB expansion. RapidOCR uses an integer polygon
                    // round offset; this analytic equivalent can differ at corners.
                    val distance = area * 1.6 / perimeter
                    val expanded = RotatedRect(rect.center,
                        Size(rect.size.width + 2 * distance, rect.size.height + 2 * distance), rect.angle)
                    if (min(expanded.size.width, expanded.size.height) < 5) return@use
                    val box = corners(expanded).map {
                        Point(Math.rint(it.x / pw * image.cols()).coerceIn(0.0, image.cols() - 1.0),
                            Math.rint(it.y / ph * image.rows()).coerceIn(0.0, image.rows() - 1.0))
                    }.toTypedArray()
                    if (hypot(box[0].x-box[1].x, box[0].y-box[1].y) > 3 &&
                        hypot(box[0].x-box[3].x, box[0].y-box[3].y) > 3) boxes.add(box)
                }
            }
        } finally { contours.forEach { it.release() } }
        // RapidOCR row order: group adjacent top-left y values within 10 pixels.
        val sorted = boxes.sortedWith(compareBy<Array<Point>> { it[0].y }.thenBy { it[0].x })
        val groups = mutableListOf<MutableList<Array<Point>>>()
        var lastY = Double.NEGATIVE_INFINITY
        for (box in sorted) {
            if (box[0].y - lastY >= 10) groups.add(mutableListOf())
            groups.last().add(box); lastY = box[0].y
        }
        groups.flatMap { it.sortedBy { p -> p[0].x } }
    }
    private fun crop(image: Mat, box: Array<Point>, a: Arena): Mat {
        fun dist(i: Int, j: Int) = hypot(box[i].x-box[j].x, box[i].y-box[j].y)
        val w = max(1, max(dist(0,1), dist(2,3)).toInt())
        val h = max(1, max(dist(0,3), dist(1,2)).toInt())
        val src = a.own(MatOfPoint2f(*box)) as MatOfPoint2f
        val dst = a.own(MatOfPoint2f(Point(0.0,0.0),Point(w.toDouble(),0.0),Point(w.toDouble(),h.toDouble()),Point(0.0,h.toDouble()))) as MatOfPoint2f
        val transform = a.own(Imgproc.getPerspectiveTransform(src,dst))
        val out = a.mat()
        Imgproc.warpPerspective(image,out,transform,Size(w.toDouble(),h.toDouble()),Imgproc.INTER_CUBIC,Core.BORDER_REPLICATE)
        if (h.toDouble()/w >= 1.5) Core.rotate(out,out,Core.ROTATE_90_COUNTERCLOCKWISE)
        return out
    }
    /** Probability (0..1) that a horizontal line crop is upside down. */
    private fun upsideDown(image: Mat, a: Arena): Float {
        val clsWidth = min(192, ceil(48.0 * image.cols() / image.rows()).toInt())
        val clsData = FloatArray(3 * 48 * 192)
        val pixels = tensor(image, 48, clsWidth, a)
        for (c in 0..2) for (y in 0 until 48)
            System.arraycopy(pixels, c * 48 * clsWidth + y * clsWidth, clsData, c * 48 * 192 + y * 192, clsWidth)
        val (cls, _) = infer(session("ch_ppocr_mobile_v2.0_cls_mobile.onnx"), clsData, longArrayOf(1, 3, 48, 192))
        return cls[1]
    }

    private fun recognize(crops: List<Mat>, english: Boolean, cancel: AtomicBoolean): List<Triple<String,Double,Boolean>> {
        val rec = session(if (english) "PP-OCRv6_rec_small.onnx" else "devanagari_PP-OCRv5_rec_mobile.onnx")
        // Python splitlines() ignores a terminal newline and CRLF delimiters.
        val dictionary = rec.metadata.customMetadata["character"]!!
            .trimEnd('\r', '\n').split(Regex("\\r?\\n"))
        val alphabet = listOf("") + dictionary + listOf(" ")
        val results = MutableList(crops.size) { Triple("",0.0,false) }
        val flipped = BooleanArray(crops.size)
        for (batch in crops.indices.sortedBy { crops[it].cols().toDouble()/crops[it].rows() }.chunked(6)) {
            check(cancel)
            Arena().use { a ->
                val width = (48 * max(320.0/48, batch.maxOf { crops[it].cols().toDouble()/crops[it].rows() })).toInt()
                require(width <= 16384) { "Text line is too wide; crop it first" }
                val input = FloatArray(batch.size * 3 * 48 * width)
                for ((b,index) in batch.withIndex()) {
                    val image = crops[index]
                    if (english) {
                        if (upsideDown(image, a) > .9f) {
                            Core.rotate(image,image,Core.ROTATE_180)
                            flipped[index] = true
                        }
                    }
                    val resizedW = min(width, ceil(48.0*image.cols()/image.rows()).toInt())
                    val pixels = tensor(image,48,resizedW,a)
                    for(c in 0..2) for(y in 0 until 48)
                        System.arraycopy(pixels,c*48*resizedW+y*resizedW,input,b*3*48*width+c*48*width+y*width,resizedW)
                }
                inferWith(rec,input,longArrayOf(batch.size.toLong(),3,48,width.toLong())) { output, shape ->
                    val steps = shape[1].toInt(); val chars = shape[2].toInt()
                    require(chars == alphabet.size) { "OCR dictionary does not match model" }
                    for ((b,index) in batch.withIndex()) {
                        val text = StringBuilder(); var confidence = 0.0; var count = 0; var last = -1
                        for (t in 0 until steps) {
                            val offset = (b*steps+t)*chars
                            var best = 0
                            var bestValue = output.get(offset)
                            for(c in 1 until chars) {
                                val value = output.get(offset+c)
                                if(value>bestValue) { best=c; bestValue=value }
                            }
                            if(best != 0 && best != last) {
                                text.append(alphabet[best]); confidence += bestValue; count++
                            }
                            last=best
                        }
                        results[index] = Triple(text.toString(), if(count>0) confidence/count else 0.0, flipped[index])
                    }
                }
            }
        }
        return results
    }
    fun run(args: Map<*, *>, cancel: AtomicBoolean): List<Map<String,Any>> {
        check(OpenCVLoader.initLocal()) { "OpenCV unavailable" }
        check(cancel)
        return Arena().use { a ->
            val original = a.own(Imgcodecs.imread(args["path"] as String))
            require(!original.empty()) { "Unable to read OCR image" }
            require(original.total() <= 30_000_000L) { "Image exceeds the 30 megapixel limit" }
            // Match RapidOCR's bounded resize and black vertical letterbox.
            // Narrow digit-validation crops otherwise expand to huge detector tensors.
            var resizedW = original.cols()
            var resizedH = original.rows()
            fun resizeBound(factor: Double) {
                resizedW = max(32, Math.rint((resizedW * factor).toInt() / 32.0).toInt() * 32)
                resizedH = max(32, Math.rint((resizedH * factor).toInt() / 32.0).toInt() * 32)
            }
            if (max(resizedW, resizedH) > 2000) resizeBound(2000.0 / max(resizedW, resizedH))
            if (min(resizedW, resizedH) < 30) resizeBound(30.0 / min(resizedW, resizedH))
            require(resizedW.toLong() * resizedH <= 30_000_000L) { "Text crop exceeds the OCR size limit" }
            val resized = a.mat()
            Imgproc.resize(original, resized, Size(resizedW.toDouble(), resizedH.toDouble()))
            val ratioW = original.cols().toDouble() / resizedW
            val ratioH = original.rows().toDouble() / resizedH
            val padding = if (resizedH <= 30 || resizedW.toDouble() / resizedH > 8)
                abs(max(resizedW / 8, 30) * 2 - resizedH) / 2 else 0
            val image = if (padding > 0) a.mat().also {
                Core.copyMakeBorder(resized, it, padding, padding, 0, 0, Core.BORDER_CONSTANT, Scalar.all(0.0))
            } else resized
            val boxes = detect(image,cancel)
            // Detect on the bounded copy (fast), but cut each line from the
            // full-resolution page: small print keeps its strokes instead of
            // being read from a 2000 px thumbnail (docs/TECH_UPGRADE_PLAN.md C1).
            val fromOriginal = padding == 0 && (ratioW > 1.0 || ratioH > 1.0)
            val crops = boxes.map { box ->
                if (fromOriginal) crop(original, box.map {
                    Point((it.x * ratioW).coerceIn(0.0, original.cols() - 1.0),
                        (it.y * ratioH).coerceIn(0.0, original.rows() - 1.0))
                }.toTypedArray(), a)
                else crop(image, box, a)
            }
            val texts = recognize(crops,args["language"]=="en",cancel)
            check(cancel)
            boxes.indices.filter { texts[it].second >= .5 && texts[it].first.isNotEmpty() }.map { i ->
                val p=boxes[i]
                val x=(p.minOf { it.x } * ratioW).coerceIn(0.0, original.cols().toDouble())
                val y=((p.minOf { it.y } - padding) * ratioH).coerceIn(0.0, original.rows().toDouble())
                val right=(p.maxOf { it.x } * ratioW).coerceIn(x, original.cols().toDouble())
                val bottom=((p.maxOf { it.y } - padding) * ratioH).coerceIn(y, original.rows().toDouble())
                val width = hypot(p[1].x-p[0].x, p[1].y-p[0].y)
                val height = hypot(p[3].x-p[0].x, p[3].y-p[0].y)
                // Crop/classifier rotations must remain visible to the page
                // orientation selector, even when the recognizer reads them.
                val angle = Math.toDegrees(atan2(p[1].y-p[0].y,p[1].x-p[0].x)) +
                    (if (height / width >= 1.5) 90.0 else 0.0) +
                    (if (texts[i].third) 180.0 else 0.0)
                mapOf("text" to texts[i].first, "confidence" to texts[i].second,
                    "bbox" to listOf(x,y,right-x,bottom-y),
                    "angle" to angle,
                    "backend" to "rapidocr-3.9.2-port")
            }
        }
    }
    override fun close() { sessions.values.forEach { it.close() }; sessions.clear() }
}
