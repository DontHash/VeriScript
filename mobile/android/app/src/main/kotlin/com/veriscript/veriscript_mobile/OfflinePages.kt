package com.veriscript.veriscript_mobile

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.graphics.pdf.PdfRenderer
import android.media.MediaMetadataRetriever
import android.os.ParcelFileDescriptor
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import androidx.exifinterface.media.ExifInterface
import org.opencv.android.OpenCVLoader
import org.opencv.android.Utils
import org.opencv.core.*
import org.opencv.imgproc.Imgproc
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.*

/** Native, bundled image/video work. No network, server, Python or model download.
 * Mats are scoped per frame; only one best candidate bitmap is retained. */
object OfflinePages {
    private class Arena : AutoCloseable {
        private val mats = mutableListOf<Mat>()
        fun own(mat: Mat): Mat { mats.add(mat); return mat }
        fun mat() = own(Mat())
        override fun close() { mats.asReversed().forEach { it.release() } }
    }
    private fun check(cancel: AtomicBoolean) { check(!cancel.get()) { "Operation cancelled" } }
    private fun arg(args: Map<*, *>, key: String) = args[key] as? String ?: error("Missing $key")
    private fun dimensions(bitmap: Bitmap, path: String, note: String = "") = mapOf(
        "path" to path, "width" to bitmap.width, "height" to bitmap.height, "note" to note)
    private fun save(bitmap: Bitmap, path: String, quality: Int = 95) {
        File(path).outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.JPEG, quality, it)) { "Unable to save page" } }
    }
    /** Cheap validation for a just-captured photo: dimensions, file size and a
     * ~512px luma sample. It deliberately does not decode the full image. */
    private fun jpegInfo(path: String): Map<String, Any> {
        val file = File(path)
        require(file.isFile) { "Captured photo is missing" }
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(path, bounds)
        require(bounds.outWidth > 0 && bounds.outHeight > 0) { "Captured photo is not a valid JPEG" }
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / sample > 512) sample *= 2
        val options = BitmapFactory.Options().apply {
            inSampleSize = sample
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val bitmap = BitmapFactory.decodeFile(path, options) ?: error("Could not decode captured photo")
        try {
            val pixels = IntArray(bitmap.width * bitmap.height)
            bitmap.getPixels(pixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
            var sum = 0.0
            var dark = 0
            var bright = 0
            for (pixel in pixels) {
                val r = (pixel shr 16) and 0xff
                val g = (pixel shr 8) and 0xff
                val b = pixel and 0xff
                val luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
                sum += luma
                if (luma < 8.0) dark++
                if (luma > 247.0) bright++
            }
            val count = pixels.size.coerceAtLeast(1)
            return mapOf(
                "path" to path,
                "width" to bounds.outWidth,
                "height" to bounds.outHeight,
                "bytes" to file.length(),
                "sampleWidth" to bitmap.width,
                "sampleHeight" to bitmap.height,
                "meanLuma" to sum / count,
                "darkFraction" to dark.toDouble() / count,
                "brightFraction" to bright.toDouble() / count,
            )
        } finally {
            bitmap.recycle()
        }
    }
    /** Blur and glare measures for a just-captured photo (docs/TECH_UPGRADE_PLAN.md C3).
     * Port of evals/harness/eval_capture_quality.py `measures`: a grey copy
     * with a 1024 px long side (INTER_AREA, as the reference). */
    private fun captureQuality(path: String): Map<String, Any> = Arena().use { a ->
        val bitmap = load(path, maxSide = 5000)
        val g8: Mat
        try { g8 = gray(rgb(bitmap, a), a) } finally { bitmap.recycle() }
        val scale = 1024.0 / max(g8.cols(), g8.rows())
        val small = if (scale < 1) a.mat().also {
            Imgproc.resize(g8, it, Size(), scale, scale, Imgproc.INTER_AREA)
        } else g8
        val g = a.mat(); small.convertTo(g, CvType.CV_32F)
        val gx = a.mat(); val gy = a.mat(); val mag = a.mat(); val lap = a.mat()
        Imgproc.Sobel(g, gx, CvType.CV_32F, 1, 0, 3)
        Imgproc.Sobel(g, gy, CvType.CV_32F, 0, 1, 3)
        Core.magnitude(gx, gy, mag)
        Imgproc.Laplacian(g, lap, CvType.CV_32F, 3)
        val n = (mag.total()).toInt()
        val m = FloatArray(n).also { mag.get(0, 0, it) }
        val l = FloatArray(n).also { lap.get(0, 0, it) }
        val sorted = m.copyOf().also { it.sort() }
        // numpy's default percentile: linear interpolation between neighbours
        val pos = (n - 1) * 0.9
        val lo = floor(pos).toInt()
        val cut = sorted[lo] + (sorted[min(lo + 1, n - 1)] - sorted[lo]) * (pos - lo)
        val edgeMag = ArrayList<Float>(); val edgeLap = ArrayList<Float>()
        for (i in 0 until n) if (m[i] > cut) { edgeMag.add(m[i]); edgeLap.add(abs(l[i])) }
        fun median(v: List<Float>): Double {
            val s = v.sorted(); val k = s.size
            return if (k % 2 == 1) s[k / 2].toDouble() else (s[k / 2 - 1].toDouble() + s[k / 2]) / 2
        }
        val sharpness = if (edgeMag.isEmpty()) 0.0 else median(edgeLap) / (median(edgeMag) + 1e-6)
        val lap1 = a.mat(); Imgproc.Laplacian(g, lap1, CvType.CV_32F)
        val mean = MatOfDouble(); val std = MatOfDouble()
        Core.meanStdDev(lap1, mean, std)
        val lapVar = std.get(0, 0)[0].pow(2)
        mean.release(); std.release()
        val bright = a.mat(); Imgproc.threshold(small, bright, 244.0, 255.0, Imgproc.THRESH_BINARY)
        val labels = a.mat(); val stats = a.mat(); val centroids = a.mat()
        val count = Imgproc.connectedComponentsWithStats(bright, labels, stats, centroids, 8)
        var largest = 0.0
        for (i in 1 until count) largest = max(largest, stats.get(i, Imgproc.CC_STAT_AREA)[0])
        mapOf("sharpness" to sharpness, "lapvar" to lapVar, "glare" to largest / n,
              "width" to small.cols(), "height" to small.rows())
    }
    /** Finger cleanup for book pages (docs/TECH_UPGRADE_PLAN.md F3).
     * Port of veriscript/document/fingers.py `finger_mask` + `clean_fingers`
     * on an RGB page: skin-coloured regions touching the left, right or
     * bottom edge (small, shallow, short edge contact, smooth inside) are
     * filled with the median paper colour around them; ink (black-hat) and
     * every colourless pixel are never changed. Returns the regions blanked. */
    private fun cleanFingers(page: Mat, a: Arena): Int {
        val h = page.rows(); val w = page.cols(); val n = h * w
        val ycc = a.mat(); Imgproc.cvtColor(page, ycc, Imgproc.COLOR_RGB2YCrCb)
        val px = ByteArray(n * 3).also { ycc.get(0, 0, it) }
        val chroma = FloatArray(n)
        val skin = ByteArray(n)
        for (i in 0 until n) {
            val y = px[i * 3].toInt() and 255
            val cr = px[i * 3 + 1].toInt() and 255
            val cb = px[i * 3 + 2].toInt() and 255
            val c = hypot((cr - 128).toDouble(), (cb - 128).toDouble()).toFloat()
            chroma[i] = c
            if (cr in 136..175 && cb in 80..130 && c >= 12f && y > 40) skin[i] = 1
        }
        val scale = max(h, w) / 1000.0
        val k = max(3, (5 * scale).roundToInt() or 1)
        val mask = a.own(Mat(h, w, CvType.CV_8U)); mask.put(0, 0, skin)
        Imgproc.morphologyEx(mask, mask, Imgproc.MORPH_OPEN, a.own(Mat.ones(k, k, CvType.CV_8U)))
        Imgproc.morphologyEx(mask, mask, Imgproc.MORPH_CLOSE, a.own(Mat.ones(2 * k + 1, 2 * k + 1, CvType.CV_8U)))
        val labels = a.mat(); val stats = a.mat(); val centroids = a.mat()
        val count = Imgproc.connectedComponentsWithStats(mask, labels, stats, centroids, 8)
        val grey = gray(page, a)
        val blurred = a.mat(); Imgproc.GaussianBlur(grey, blurred, Size(0.0, 0.0), max(1.0, scale))
        val gx = a.mat(); val gy = a.mat(); val grad = a.mat()
        Imgproc.Sobel(blurred, gx, CvType.CV_32F, 1, 0); Imgproc.Sobel(blurred, gy, CvType.CV_32F, 0, 1)
        Core.magnitude(gx, gy, grad)
        val keep = a.own(Mat.zeros(h, w, CvType.CV_8U))
        val ex = .02 * w; val ey = .02 * h
        val bandX = max(1, ex.toInt()); val bandY = max(1, ey.toInt())
        var kept = 0
        for (i in 1 until count) {
            val x = stats.get(i, Imgproc.CC_STAT_LEFT)[0].toInt(); val y = stats.get(i, Imgproc.CC_STAT_TOP)[0].toInt()
            val bw = stats.get(i, Imgproc.CC_STAT_WIDTH)[0].toInt(); val bh = stats.get(i, Imgproc.CC_STAT_HEIGHT)[0].toInt()
            val area = stats.get(i, Imgproc.CC_STAT_AREA)[0]
            if (area < .0008 * n || area > .15 * n) continue
            val left = x <= ex; val right = x + bw >= w - ex; val bottom = y + bh >= h - ey
            if (!(left || right || bottom)) continue
            if ((left && bw > .30 * w) || (right && bw > .30 * w) || (bottom && !(left || right) && bh > .30 * h)) continue
            val region = a.mat(); Core.compare(labels, Scalar(i.toDouble()), region, Core.CMP_EQ)
            fun rowsTouched(r: Rect): Int { val m = a.mat(); Core.reduce(a.own(region.submat(r)), m, 1, Core.REDUCE_MAX); return Core.countNonZero(m) }
            fun colsTouched(r: Rect): Int { val m = a.mat(); Core.reduce(a.own(region.submat(r)), m, 0, Core.REDUCE_MAX); return Core.countNonZero(m) }
            val contact = maxOf(
                if (left) rowsTouched(Rect(0, 0, bandX, h)).toDouble() / h else 0.0,
                if (right) rowsTouched(Rect(w - bandX, 0, bandX, h)).toDouble() / h else 0.0,
                if (bottom) colsTouched(Rect(0, h - bandY, w, bandY)).toDouble() / w else 0.0)
            if (contact > .20) continue
            val inner = a.mat(); Imgproc.erode(region, inner, a.own(Mat.ones(2 * k + 1, 2 * k + 1, CvType.CV_8U)))
            if (Core.countNonZero(inner) > 50 && Core.mean(grad, inner).`val`[0] > 25.0) continue
            Core.bitwise_or(keep, region, keep)
            kept++
        }
        if (kept == 0) return 0
        val grow = max(1, (3 * scale).roundToInt())
        Imgproc.dilate(keep, keep, a.own(Mat.ones(2 * grow + 1, 2 * grow + 1, CvType.CV_8U)))
        val kb = max(15, (15 * scale).roundToInt() or 1)
        val blackhat = a.mat()
        Imgproc.morphologyEx(grey, blackhat, Imgproc.MORPH_BLACKHAT, a.own(Imgproc.getStructuringElement(Imgproc.MORPH_RECT, Size(kb.toDouble(), kb.toDouble()))))
        val keepPx = ByteArray(n).also { keep.get(0, 0, it) }
        val bhPx = ByteArray(n).also { blackhat.get(0, 0, it) }
        for (i in 0 until n) {
            if (keepPx[i].toInt() == 0) continue
            if ((bhPx[i].toInt() and 255) > 35 || chroma[i] < 6f) keepPx[i] = 0
        }
        keep.put(0, 0, keepPx)
        if (Core.countNonZero(keep) == 0) return 0
        // Fill: the median paper colour in a ring around the blanked area.
        val ringM = a.mat(); Imgproc.dilate(keep, ringM, a.own(Mat.ones(25, 25, CvType.CV_8U)))
        val ringPx = ByteArray(n).also { ringM.get(0, 0, it) }
        val greyPx = ByteArray(n).also { grey.get(0, 0, it) }
        val ring = (0 until n).filter { ringPx[it].toInt() != 0 && keepPx[it].toInt() == 0 }
        val rgbPx = ByteArray(n * 3).also { page.get(0, 0, it) }
        val sample = if (ring.isNotEmpty()) {
            val g = ring.map { greyPx[it].toInt() and 255 }.sorted()
            val mid = if (g.size % 2 == 1) g[g.size / 2].toDouble() else (g[g.size / 2 - 1] + g[g.size / 2]) / 2.0
            ring.filter { (greyPx[it].toInt() and 255) > mid }
        } else emptyList()
        val from = if (sample.size >= 20) sample else (0 until n).filter { keepPx[it].toInt() == 0 }
        fun median(c: Int): Double {
            val v = from.map { rgbPx[it * 3 + c].toInt() and 255 }.sorted()
            return if (v.size % 2 == 1) v[v.size / 2].toDouble() else (v[v.size / 2 - 1] + v[v.size / 2]) / 2.0
        }
        page.setTo(Scalar(floor(median(0)), floor(median(1)), floor(median(2))), keep)
        val parts = a.mat()
        return Imgproc.connectedComponents(keep, parts) - 1
    }
    /** Same-page fingerprint for batch capture (docs/TECH_UPGRADE_PLAN.md C4).
     * Port of evals/harness/eval_batch_helpers.py `fingerprint`: a grey copy
     * with a 1024 px long side (INTER_AREA), the central 80%, histogram
     * equalised, then a 16x16 difference hash as 64 hex digits. */
    private fun pageFingerprint(path: String): String = Arena().use { a ->
        val bitmap = load(path, maxSide = 5000)
        val g8: Mat
        try { g8 = gray(rgb(bitmap, a), a) } finally { bitmap.recycle() }
        val scale = 1024.0 / max(g8.cols(), g8.rows())
        val small = if (scale < 1) a.mat().also {
            Imgproc.resize(g8, it, Size(), scale, scale, Imgproc.INTER_AREA)
        } else g8
        val h = small.rows(); val w = small.cols()
        val y0 = (h * 0.1).toInt(); val x0 = (w * 0.1).toInt()
        val centre = a.own(small.submat(Rect(x0, y0, w - 2 * x0, h - 2 * y0)))
        val eq = a.mat(); Imgproc.equalizeHist(centre, eq)
        val grid = a.mat(); Imgproc.resize(eq, grid, Size(17.0, 16.0), 0.0, 0.0, Imgproc.INTER_AREA)
        val v = ByteArray(17 * 16).also { grid.get(0, 0, it) }
        val out = StringBuilder()
        var nibble = 0
        for (i in 0 until 256) {
            val r = i / 16; val c = i % 16
            val bit = if ((v[r * 17 + c + 1].toInt() and 255) > (v[r * 17 + c].toInt() and 255)) 1 else 0
            nibble = (nibble shl 1) or bit
            if (i % 4 == 3) { out.append("0123456789abcdef"[nibble]); nibble = 0 }
        }
        out.toString()
    }
    /** Longest side kept through import, alignment and enhancement.
     * 4096 keeps a 12 MP photo (4032x3024) at full size: an A4 page filling
     * the frame stays near 300 DPI. The old 2500 px limit left about 170 DPI
     * for OCR (docs/TECH_UPGRADE_PLAN.md, C1). */
    private const val WORKING_MAX_SIDE = 4096
    private fun load(path: String, maxSide: Int = WORKING_MAX_SIDE): Bitmap {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(path, bounds)
        require(bounds.outWidth > 0 && bounds.outHeight > 0) { "Unsupported or damaged image" }
        require(bounds.outWidth.toLong() * bounds.outHeight <= 30_000_000L) { "Image exceeds the 30 megapixel limit" }
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / sample > 5000) sample *= 2
        val decoded = BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample })
            ?: error("Could not decode image")
        val matrix = Matrix()
        val orientation = ExifInterface(path).getAttributeInt(ExifInterface.TAG_ORIENTATION, 1)
        when (orientation) {
            2 -> matrix.setScale(-1f, 1f)
            3 -> matrix.setRotate(180f)
            4 -> matrix.setScale(1f, -1f)
            5 -> { matrix.setRotate(90f); matrix.postScale(-1f, 1f) }
            6 -> matrix.setRotate(90f)
            7 -> { matrix.setRotate(-90f); matrix.postScale(-1f, 1f) }
            8 -> matrix.setRotate(-90f)
        }
        var bitmap = if (matrix.isIdentity) decoded else Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
        if (bitmap !== decoded) decoded.recycle()
        val scale = min(1.0, maxSide.toDouble() / max(bitmap.width, bitmap.height))
        if (scale < 1) {
            val resized = Bitmap.createScaledBitmap(bitmap, (bitmap.width * scale).roundToInt(), (bitmap.height * scale).roundToInt(), true)
            bitmap.recycle(); bitmap = resized
        }
        return bitmap
    }
    private fun rgb(bitmap: Bitmap, arena: Arena): Mat {
        val rgba = arena.mat(); Utils.bitmapToMat(bitmap, rgba)
        val result = arena.mat(); Imgproc.cvtColor(rgba, result, Imgproc.COLOR_RGBA2RGB)
        return result
    }
    private fun bitmap(mat: Mat): Bitmap = Bitmap.createBitmap(mat.cols(), mat.rows(), Bitmap.Config.ARGB_8888)
        .also { Utils.matToBitmap(mat, it) }
    private fun gray(image: Mat, arena: Arena): Mat = arena.mat().also { Imgproc.cvtColor(image, it, Imgproc.COLOR_RGB2GRAY) }
    private fun enhanced(image: Mat, arena: Arena, enlarge: Boolean): Mat {
        val input = gray(image,arena)
        val small = arena.mat()
        Imgproc.resize(input,small,Size(max(1,input.cols()/4).toDouble(),max(1,input.rows()/4).toDouble()),0.0,0.0,Imgproc.INTER_AREA)
        val backgroundSmall = arena.mat(); Imgproc.medianBlur(small,backgroundSmall,11)
        val background = arena.mat(); Imgproc.resize(backgroundSmall,background,input.size(),0.0,0.0,Imgproc.INTER_CUBIC)
        val smooth = arena.mat(); Imgproc.GaussianBlur(background,smooth,Size(0.0,0.0),13.7)
        val values = ByteArray(smooth.total().toInt()); smooth.get(0,0,values)
        val histogram = IntArray(256); values.forEach { histogram[it.toInt() and 255]++ }
        var target=255; var count=0
        for(i in histogram.indices) { count+=histogram[i]; if(count>=values.size*.9) { target=i; break } }
        val src = arena.mat(); input.convertTo(src,CvType.CV_32F)
        val bg = arena.mat(); smooth.convertTo(bg,CvType.CV_32F); Core.max(bg,Scalar(1.0),bg)
        val flat = arena.mat(); Core.divide(src,bg,flat,target.toDouble()); flat.convertTo(flat,CvType.CV_8U)
        val clean = arena.mat(); Imgproc.bilateralFilter(flat,clean,5,40.0,5.0)
        val blurred = arena.mat(); Imgproc.GaussianBlur(clean,blurred,Size(0.0,0.0),1.1)
        val sharp = arena.mat(); Core.addWeighted(clean,1.25,blurred,-.25,0.0,sharp)
        val factor = if(enlarge && min(sharp.cols(),sharp.rows())<1000) min(2.0,min(5000.0/max(sharp.cols(),sharp.rows()),sqrt(12_500_000.0/(sharp.total())))) else 1.0
        val output = arena.mat()
        Imgproc.resize(sharp,output,Size((sharp.cols()*factor).roundToInt().toDouble(),(sharp.rows()*factor).roundToInt().toDouble()),0.0,0.0,Imgproc.INTER_LANCZOS4)
        return output
    }
    private fun resized(image: Mat, side: Int, arena: Arena): Mat {
        val factor = min(1.0, side.toDouble() / max(image.cols(), image.rows()))
        return arena.mat().also { Imgproc.resize(image, it, Size(image.cols()*factor, image.rows()*factor)) }
    }
    private fun ordered(points: Array<Point>): Array<Point> {
        val cx = points.sumOf { it.x }/4; val cy = points.sumOf { it.y }/4
        val cyclic = points.sortedBy { atan2(it.y-cy,it.x-cx) }
        val first = cyclic.indices.minBy { cyclic[it].x + cyclic[it].y }
        return Array(4) { cyclic[(first+it)%4] }
    }
    private fun warp(image: Mat, quad: Array<Point>, arena: Arena): Mat {
        fun distance(a: Point,b: Point) = hypot(a.x-b.x,a.y-b.y)
        val width = max(distance(quad[0],quad[1]),distance(quad[3],quad[2])).roundToInt()
        val height = max(distance(quad[0],quad[3]),distance(quad[1],quad[2])).roundToInt()
        require(width >= 60 && height >= 60 && width <= 6000 && height <= 6000 && width.toLong()*height <= 16_800_000L) { "Crop is too small or too large" }
        val src = arena.own(MatOfPoint2f(*quad))
        val dst = arena.own(MatOfPoint2f(Point(0.0,0.0),Point(width-1.0,0.0),Point(width-1.0,height-1.0),Point(0.0,height-1.0)))
        val transform = arena.own(Imgproc.getPerspectiveTransform(src,dst))
        return arena.mat().also { Imgproc.warpPerspective(image,it,transform,Size(width.toDouble(),height.toDouble())) }
    }
    private fun paper(image: Mat, arena: Arena, spread: Boolean = false): Mat? {
        val hsv = arena.mat(); Imgproc.cvtColor(image,hsv,Imgproc.COLOR_RGB2HSV)
        val sat = arena.mat(); val value = arena.mat()
        Core.extractChannel(hsv,sat,1); Core.extractChannel(hsv,value,2)
        val bright = arena.mat(); Imgproc.threshold(value,bright,0.0,255.0,Imgproc.THRESH_BINARY+Imgproc.THRESH_OTSU)
        val saturation = ByteArray((sat.total()).toInt()); sat.get(0,0,saturation)
        val brightness = ByteArray(saturation.size); bright.get(0,0,brightness)
        val histogram = IntArray(256); var total = 0
        for (i in saturation.indices) if (brightness[i].toInt() != 0) {
            histogram[saturation[i].toInt() and 255]++; total++
        }
        if (total == 0) return null
        var percentile = 0; var cumulative = 0
        for (i in histogram.indices) {
            cumulative += histogram[i]
            if (cumulative > (total-1)*.85) { percentile = i; break }
        }
        val limit = min(120.0,percentile*1.4)
        val guard = arena.mat(); Core.inRange(sat,Scalar(0.0),Scalar(limit),guard)
        val mask = arena.mat(); Core.bitwise_and(bright,guard,mask)
        val k = max(7,min(image.rows(),image.cols())/48)
        val kernel = arena.own(Imgproc.getStructuringElement(Imgproc.MORPH_RECT,Size(k.toDouble(),k.toDouble())))
        Imgproc.morphologyEx(mask,mask,Imgproc.MORPH_CLOSE,kernel)
        val labels = arena.mat(); val stats = arena.mat(); val centroids = arena.mat()
        val count = Imgproc.connectedComponentsWithStats(mask,labels,stats,centroids)
        if (count < 2) return null
        val best = (1 until count).maxBy { stats.get(it,Imgproc.CC_STAT_AREA)[0] }
        if (stats.get(best,Imgproc.CC_STAT_AREA)[0] < .12 * mask.total()) return null
        val result = arena.mat(); Core.compare(labels,Scalar(best.toDouble()),result,Core.CMP_EQ)
        if (spread) {
            // A dark gutter separates two equally valid sheets. Keep both rather
            // than treating the largest connected component as the whole book.
            for (label in 1 until count) {
                if (label == best || stats.get(label,Imgproc.CC_STAT_AREA)[0] < .12*mask.total()) continue
                val component = arena.mat(); Core.compare(labels,Scalar(label.toDouble()),component,Core.CMP_EQ)
                Core.bitwise_or(result,component,result)
            }
        }
        Imgproc.morphologyEx(result,result,Imgproc.MORPH_CLOSE,kernel)
        return result
    }
    private data class View(val image: Mat,val cropped: Boolean,val alignment: Double)
    private fun pageView(image: Mat, arena: Arena, spread: Boolean = false): View {
        val small = resized(image,960,arena)
        val scale = small.cols().toDouble()/image.cols()
        val g = gray(small,arena); val blur = arena.mat(); Imgproc.GaussianBlur(g,blur,Size(5.0,5.0),0.0)
        val edges = arena.mat(); Imgproc.Canny(blur,edges,40.0,120.0)
        val kernel = arena.own(Imgproc.getStructuringElement(Imgproc.MORPH_RECT,Size(5.0,5.0)))
        Imgproc.morphologyEx(edges,edges,Imgproc.MORPH_CLOSE,kernel)
        val contours = mutableListOf<MatOfPoint>(); val hierarchy = arena.mat()
        Imgproc.findContours(edges,contours,hierarchy,Imgproc.RETR_EXTERNAL,Imgproc.CHAIN_APPROX_SIMPLE)
        contours.forEach { arena.own(it) }
        for (contour in contours.sortedByDescending { Imgproc.contourArea(it) }.take(8)) {
            if (spread) break // A single sheet contour must not discard its neighbour.
            val area = Imgproc.contourArea(contour)/g.total()
            if (area < .25 || area > .98) continue
            val curve = arena.own(MatOfPoint2f(*contour.toArray())) as MatOfPoint2f
            val poly = arena.own(MatOfPoint2f()) as MatOfPoint2f
            Imgproc.approxPolyDP(curve,poly,.025*Imgproc.arcLength(curve,true),true)
            if (poly.total() != 4L) continue
            val polygon = arena.own(MatOfPoint(*poly.toArray())) as MatOfPoint
            if (!Imgproc.isContourConvex(polygon)) continue
            val quad = ordered(poly.toArray().map { Point(it.x/scale,it.y/scale) }.toTypedArray())
            fun d(a: Int,b: Int) = hypot(quad[a].x-quad[b].x,quad[a].y-quad[b].y)
            val top = d(0,1); val bottom = d(3,2); val left = d(0,3); val right = d(1,2)
            val aspect = max(top,bottom)/max(left,right)
            val alignment = min(top,bottom)/max(top,bottom)*min(left,right)/max(left,right)
            if (min(max(top,bottom),max(left,right)) < 100 || aspect !in .35..2.5 || alignment < .55) continue
            return View(warp(image,quad,arena),true,alignment)
        }
        val mask = paper(small,arena,spread) ?: return View(image,false,.5)
        val box = Imgproc.boundingRect(mask)
        val x = max(0,(box.x/scale - image.cols()*.02).toInt())
        val y = max(0,(box.y/scale - image.rows()*.02).toInt())
        val right = min(image.cols(),((box.x+box.width)/scale+image.cols()*.02).toInt())
        val bottom = min(image.rows(),((box.y+box.height)/scale+image.rows()*.02).toInt())
        if ((right-x).toDouble()*(bottom-y) > image.total()*.92) return View(image,false,.5)
        return View(arena.own(image.submat(Rect(x,y,right-x,bottom-y))),true,.5)
    }
    private fun deskew(image: Mat,arena: Arena): Mat {
        val g = gray(resized(image,960,arena),arena)
        val edges = arena.mat(); Imgproc.Canny(g,edges,50.0,150.0)
        val lines = arena.mat(); Imgproc.HoughLinesP(edges,lines,1.0,Math.PI/180,60,g.cols()/4.0,20.0)
        val angles = (0 until lines.rows()).mapNotNull { i ->
            val l = lines.get(i,0); val angle = atan2(l[3]-l[1],l[2]-l[0])*180/Math.PI
            if (abs(angle) <= 8) angle else null
        }.sorted()
        if (angles.size < 3) return image
        val angle = angles[angles.size/2]
        if (abs(angle) < .25) return image
        val rotation = arena.own(Imgproc.getRotationMatrix2D(Point(image.cols()/2.0,image.rows()/2.0),angle,1.0))
        val cosine = abs(cos(angle*Math.PI/180)); val sine = abs(sin(angle*Math.PI/180))
        val width = ceil(image.cols()*cosine+image.rows()*sine)
        val height = ceil(image.rows()*cosine+image.cols()*sine)
        rotation.put(0,2,rotation.get(0,2)[0]+(width-image.cols())/2)
        rotation.put(1,2,rotation.get(1,2)[0]+(height-image.rows())/2)
        return arena.mat().also { Imgproc.warpAffine(image,it,rotation,Size(width,height),Imgproc.INTER_LINEAR,Core.BORDER_CONSTANT,Scalar(255.0,255.0,255.0)) }
    }
    private data class Features(val detail: FloatArray,val sharp: Double,val density: Double)
    private fun features(image: Mat,arena: Arena): Features {
        val small = arena.mat(); Imgproc.resize(image,small,Size(224.0,224.0))
        val g = gray(small,arena); val floating = arena.mat(); g.convertTo(floating,CvType.CV_32F)
        val blur = arena.mat(); Imgproc.GaussianBlur(floating,blur,Size(0.0,0.0),5.0)
        val detail = arena.mat(); Core.subtract(floating,blur,detail)
        val array = FloatArray(224*224); detail.get(0,0,array)
        val lap = arena.mat(); Imgproc.Laplacian(g,lap,CvType.CV_32F)
        val mean = arena.own(MatOfDouble()) as MatOfDouble; val std = arena.own(MatOfDouble()) as MatOfDouble
        Core.meanStdDev(lap,mean,std)
        val edges = arena.mat(); Imgproc.Canny(g,edges,40.0,100.0)
        return Features(array,std.toArray()[0].pow(2),Core.countNonZero(edges)/edges.total().toDouble())
    }
    private fun same(a: Features?,b: Features?,threshold: Double,arena: Arena): Boolean {
        if (a == null || b == null) return false
        val left = arena.own(Mat(224,224,CvType.CV_32F)); left.put(0,0,a.detail)
        val right = arena.own(Mat(224,224,CvType.CV_32F)); right.put(0,0,b.detail)
        val m = arena.own(MatOfDouble()) as MatOfDouble; val s = arena.own(MatOfDouble()) as MatOfDouble
        Core.meanStdDev(left,m,s); if (s.toArray()[0] < 1) return false
        Core.meanStdDev(right,m,s); if (s.toArray()[0] < 1) return false
        Imgproc.GaussianBlur(left,left,Size(0.0,0.0),1.5); Imgproc.GaussianBlur(right,right,Size(0.0,0.0),1.5)
        val padded = arena.mat(); Core.copyMakeBorder(right,padded,10,10,10,10,Core.BORDER_REPLICATE)
        val scores = arena.mat(); Imgproc.matchTemplate(padded,left,scores,Imgproc.TM_CCOEFF_NORMED)
        val value = Core.minMaxLoc(scores).maxVal
        return value.isFinite() && value >= threshold
    }
    private fun split(view: Mat,layout: String,arena: Arena): List<Pair<String,Mat>> {
        val maskSmall = paper(resized(view,1600,arena),arena,layout != "single")
        val mask = maskSmall?.let { arena.mat().also { m -> Imgproc.resize(it,m,view.size(),0.0,0.0,Imgproc.INTER_NEAREST) } }
        val box = mask?.let { Imgproc.boundingRect(it) } ?: Rect(0,0,view.cols(),view.rows())
        if (layout == "single" || layout == "auto" && box.width.toDouble()/box.height <= 1.15) {
            return listOf("single" to view)
        }
        val g = gray(view,arena)
        val band = arena.own(g.submat(Rect(0,(view.rows()*.15).toInt(),view.cols(),(view.rows()*.7).toInt())))
        val profile = arena.mat(); Core.reduce(band,profile,0,Core.REDUCE_AVG,CvType.CV_32F)
        Imgproc.GaussianBlur(profile,profile,Size(0.0,0.0),3.0)
        val lo = box.x+(box.width*.26).toInt(); val hi = min(view.cols(),box.x+(box.width*.78).toInt())
        val values = (lo until hi).map { profile.get(0,it)[0] }
        var cut = box.x+box.width/2
        if (values.isNotEmpty()) {
            val base = values.sorted()[values.size/2]
            // The gutter is a broad dark band, not a sharp local minimum.
            // Picking a narrow valley can instead split through a text column.
            val candidate = lo+values.indices.minBy { values[it] }
            val radius = (box.width*.06).toInt()+20
            if (base-profile.get(0,candidate)[0] >= 12 &&
                profile.get(0,max(box.x,candidate-radius))[0]-profile.get(0,candidate)[0] >= 8 &&
                profile.get(0,min(view.cols()-1,candidate+radius))[0]-profile.get(0,candidate)[0] >= 8)
                cut = candidate
        }
        val parts = mutableListOf<Pair<String,Mat>>()
        for ((side,range) in listOf("left" to (0 to cut),"right" to (cut to view.cols()))) {
            val x0 = range.first; val x1 = range.second
            if (x1-x0 < 60) continue
            var rect = Rect(x0,0,x1-x0,view.rows())
            if (mask != null) {
                val sideMask = arena.own(mask.submat(rect))
                if (Core.countNonZero(sideMask) < 60) continue
                val bounds = Imgproc.boundingRect(sideMask)
                if (bounds.width < max(60,(view.cols()*.08).toInt()) || bounds.height < 80) continue
                val left = max(x0,x0+bounds.x-(view.cols()*.02).toInt())
                val right = min(x1,x0+bounds.x+bounds.width+(view.cols()*.02).toInt())
                val top = max(0,bounds.y-(view.rows()*.02).toInt())
                val bottom = min(view.rows(),bounds.y+bounds.height+(view.rows()*.02).toInt())
                rect = Rect(left,top,right-left,bottom-top)
            }
            parts.add(side to arena.own(view.submat(rect)))
        }
        return parts
    }
    private data class Candidate(val bitmap: Bitmap,val features: Features,val score: Double,val time: Double)
    private fun video(path: String,out: String,layout: String,cancel: AtomicBoolean,progress: (Int,Int)->Unit,
                      fingers: Boolean = false): Map<String,Any> {
        require(layout in listOf("single","spread","auto")) { "Unknown book layout" }
        val decoder = MediaMetadataRetriever()
        val pages = mutableListOf<Map<String,Any>>()
        val warnings = mutableListOf("Review page order and completeness: automatic capture can miss pages.")
        var candidate: Candidate? = null
        var previous: Features? = null
        var saved: Features? = null
        var capped = false
        var pageLimit = false
        File(out).mkdirs()
        fun flush() {
            val best = candidate ?: return
            candidate = null
            try { Arena().use { arena ->
                if (same(best.features,saved,.97,arena)) return@use
                val view = rgb(best.bitmap,arena)
                var parts = split(view,layout,arena)
                if (parts.size == 2 && min(parts[0].second.cols(),parts[1].second.cols()) < .6*max(parts[0].second.cols(),parts[1].second.cols())) {
                    val narrow = parts.minBy { it.second.cols() }
                    warnings.add("${narrow.first} side at ${best.time}s is mostly covered; re-record that page.")
                    parts = parts.filter { it !== narrow }
                }
                if (pages.size+parts.size > 150) { capped = true; pageLimit = true; return@use }
                saved = best.features
                for ((side,image) in parts) {
                    check(cancel)
                    val id = pages.size
                    val filename = "$out/capture_${id.toString().padStart(4,'0')}.jpg"
                    val blanked = if (fingers) cleanFingers(image, arena) else 0
                    if (blanked > 0) warnings.add("Page ${id + 1}: fingers at the page edge were blanked; check the margins.")
                    val page = bitmap(image)
                    try { save(page,filename) } finally { page.recycle() }
                    pages.add(mapOf("path" to filename,"width" to image.cols(),"height" to image.rows(),
                        "side" to side,"timestamp" to best.time,"id" to id,"score" to best.score))
                }
            } } finally { best.bitmap.recycle() }
        }
        try {
            decoder.setDataSource(path)
            val duration = decoder.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: error("Video duration unavailable")
            val width = decoder.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toLongOrNull() ?: 0
            val height = decoder.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toLongOrNull() ?: 0
            require(duration > 0 && width*height in 1..30_000_000L) { "Invalid video or frame size exceeds 30 megapixels" }
            val end = min(duration,600_000L)
            capped = duration > end
            if (capped) warnings.add("Stopped at the 10-minute limit. The book may be incomplete.")
            var stableSince = 0.0
            var timestamp = 0L
            while (timestamp < end && !pageLimit && pages.size < 150) {
                check(cancel)
                val frame = decoder.getScaledFrameAtTime(timestamp*1000,MediaMetadataRetriever.OPTION_CLOSEST,1600,1600)
                    ?: error("Video decoding failed; use an H.264 MP4")
                try { Arena().use { arena ->
                    val spread = layout == "spread" || layout == "auto" && frame.width.toDouble()/frame.height > 1.15
                    val view = pageView(rgb(frame,arena),arena,spread)
                    val current = features(view.image,arena)
                    val time = timestamp/1000.0
                    if (!same(current,previous,.78,arena)) { flush(); stableSince = time }
                    previous = current
                    if (time-stableSince >= .75 && current.sharp >= 35 && current.density >= .008) {
                        val score = ln(1+current.sharp)*view.alignment
                        if (candidate == null || score > candidate!!.score) {
                            candidate?.bitmap?.recycle()
                            candidate = Candidate(bitmap(view.image),current,score,time)
                        }
                    }
                } } finally { frame.recycle() }
                progress(timestamp.toInt(),end.toInt())
                timestamp += 250
                if (pages.size >= 150) { capped = true; break }
            }
            check(cancel); flush()
            require(pages.isNotEmpty()) { "No steady readable pages found. Hold each spread still for 1–2 seconds in good light." }
            if (pages.size >= 150 || pageLimit) warnings.add("Reached the page limit. The book may be incomplete.")
            return mapOf("pages" to pages,"warnings" to warnings,"capped" to capped)
        } finally { candidate?.bitmap?.recycle(); decoder.release() }
    }
    private fun textPdf(out: String,title: String,pages: List<String>,cancel: AtomicBoolean) {
        val document = PdfDocument()
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.BLACK; textSize = 13f; typeface = Typeface.create("sans-serif",Typeface.NORMAL) }
        var pageNumber = 0
        try {
            for ((index,text) in pages.withIndex()) {
                val content = if (index == 0) "$title\n\n$text" else text
                val layout = StaticLayout.Builder.obtain(content,0,content.length,paint,499)
                    .setAlignment(Layout.Alignment.ALIGN_NORMAL).setLineSpacing(3f,1f).setIncludePad(false).build()
                var startLine = 0
                while (startLine < layout.lineCount) {
                    check(cancel)
                    val y = layout.getLineTop(startLine)
                    var endLine = startLine+1
                    while (endLine < layout.lineCount && layout.getLineBottom(endLine)-y <= 746) endLine++
                    if (layout.getLineBottom(endLine-1)-y > 746 && endLine > startLine+1) endLine--
                    val page = document.startPage(PdfDocument.PageInfo.Builder(595,842,++pageNumber).create())
                    page.canvas.save(); page.canvas.translate(48f,48f-y)
                    page.canvas.clipRect(0f,y.toFloat(),499f,layout.getLineBottom(endLine-1).toFloat())
                    layout.draw(page.canvas); page.canvas.restore(); document.finishPage(page)
                    startLine = endLine
                }
            }
            File(out).outputStream().use { document.writeTo(it) }
        } finally { document.close() }
    }
    fun run(method: String,args: Map<*, *>,cancel: AtomicBoolean,progress: (Int,Int)->Unit): Any? {
        check(OpenCVLoader.initLocal()) { "Bundled image engine could not load" }
        check(cancel)
        when(method) {
            "video" -> return video(arg(args,"path"),arg(args,"out"),arg(args,"layout"),cancel,progress,
                args["cleanFingers"] == true)
            "jpegInfo" -> return jpegInfo(arg(args,"path"))
            "captureQuality" -> return captureQuality(arg(args,"path"))
            "pageFingerprint" -> return pageFingerprint(arg(args,"path"))
            "textPdf" -> { textPdf(arg(args,"out"),arg(args,"title"),(args["pages"] as List<*>).map { it as String },cancel); return null }
            "pdfInfo", "pdfPage" -> {
                ParcelFileDescriptor.open(File(arg(args,"path")),ParcelFileDescriptor.MODE_READ_ONLY).use { fd ->
                    PdfRenderer(fd).use { renderer ->
                        require(renderer.pageCount <= 150) { "PDF import is limited to 150 pages; split the file first" }
                        if(method == "pdfInfo") return mapOf("pages" to renderer.pageCount)
                        val index = (args["index"] as Number).toInt()
                        require(index in 0 until renderer.pageCount)
                        renderer.openPage(index).use { page ->
                            val scale = 2000.0/max(page.width,page.height)
                            val image = Bitmap.createBitmap(max(1,(page.width*scale).toInt()),max(1,(page.height*scale).toInt()),Bitmap.Config.ARGB_8888)
                            try { image.eraseColor(Color.WHITE); page.render(image,null,null,PdfRenderer.Page.RENDER_MODE_FOR_PRINT)
                                val out = arg(args,"out"); save(image,out); return dimensions(image,out)
                            } finally { image.recycle() }
                        }
                    }
                }
            }
        }
        if (method == "shrink") {
            // Smaller PDF pages for sharing (docs/TECH_UPGRADE_PLAN.md E3):
            // the long side capped and a lower JPEG quality; text is untouched.
            val maxSide = (args["maxSide"] as Number).toInt().coerceIn(400, 5000)
            val quality = (args["quality"] as Number).toInt().coerceIn(30, 95)
            val small = load(arg(args,"path"), maxSide)
            try { save(small, arg(args,"out"), quality); return dimensions(small, arg(args,"out")) }
            finally { small.recycle() }
        }
        val path = arg(args,"path")
        val image = load(path,if(method in listOf("dimensions","rotate","digitCrop","crop")) 5000 else WORKING_MAX_SIDE)
        try {
            val out = args["out"] as? String ?: path
            when(method) {
                "dimensions" -> return dimensions(image,path)
                "cleanFingers" -> Arena().use { arena ->
                    val page = rgb(image, arena)
                    val n = cleanFingers(page, arena)
                    val result = bitmap(page)
                    try { save(result, out); return dimensions(result, out) + mapOf("fingers" to n) }
                    finally { result.recycle() }
                }
                "normalize" -> { save(image,out); return dimensions(image,out) }
                "enhance", "digitCrop" -> Arena().use { arena ->
                    val input = rgb(image,arena)
                    val rendered = if(method == "digitCrop") {
                        val box = (args["bbox"] as List<*>).map { (it as Number).toDouble() }
                        require(box.size == 4)
                        val x=max(0,floor(box[0]-8).toInt()); val y=max(0,floor(box[1]-8).toInt())
                        val right=min(input.cols(),ceil(box[0]+box[2]+8).toInt()); val bottom=min(input.rows(),ceil(box[1]+box[3]+8).toInt())
                        require(right>x && bottom>y) { "Digit crop is outside the page" }
                        val patch = arena.own(input.submat(Rect(x,y,right-x,bottom-y)))
                        val scaled=arena.mat(); val factor=min(2.0,2200.0/max(patch.cols(),patch.rows()))
                        Imgproc.resize(patch,scaled,Size((patch.cols()*factor).roundToInt().toDouble(),(patch.rows()*factor).roundToInt().toDouble()),0.0,0.0,Imgproc.INTER_LANCZOS4)
                        val mono = gray(scaled,arena); val contrast=arena.mat(); val clahe=Imgproc.createCLAHE(2.0,Size(8.0,8.0))
                        try { clahe.apply(mono,contrast) } finally { clahe.collectGarbage() }
                        contrast
                    } else enhanced(input,arena,true)
                    val result=bitmap(rendered)
                    try { save(result,out); return dimensions(result,out,"Shadows reduced; small pages enlarged up to 2×. Check fine text against the original.") }
                    finally { result.recycle() }
                }
                "rotate" -> {
                    val degrees = (args["degrees"] as Number).toFloat()
                    val rotated = Bitmap.createBitmap(image,0,0,image.width,image.height,Matrix().apply { postRotate(degrees) },true)
                    try { save(rotated,out); return dimensions(rotated,out) } finally { if(rotated !== image) rotated.recycle() }
                }
                "restore", "crop" -> Arena().use { arena ->
                    val input = rgb(image,arena)
                    val view = if(method == "crop") {
                        val points = (args["points"] as List<*>).map { value ->
                            val p = value as List<*>; Point((p[0] as Number).toDouble()*input.cols(),(p[1] as Number).toDouble()*input.rows())
                        }.toTypedArray()
                        require(points.size == 4 && points.all { it.x in 0.0..input.cols().toDouble() && it.y in 0.0..input.rows().toDouble() }) { "Crop corners are outside the image" }
                        val crosses = points.indices.map { i ->
                            val a=points[i]; val b=points[(i+1)%4]; val c=points[(i+2)%4]
                            (b.x-a.x)*(c.y-b.y)-(b.y-a.y)*(c.x-b.x)
                        }
                        require(crosses.all { it > 1.0 }) { "Keep crop corners clockwise without crossing" }
                        View(warp(input,points,arena),true,1.0)
                    } else pageView(input,arena)
                    val aligned = deskew(view.image,arena)
                    val result = bitmap(aligned)
                    try { save(result,out); return dimensions(result,out,if(view.cropped) "Automatically aligned; check the crop." else "Page boundary uncertain; full image kept.") }
                    finally { result.recycle() }
                }
                else -> error("Unknown operation: $method")
            }
        } finally { image.recycle() }
    }
}
