import java.io.FileInputStream
import java.security.MessageDigest
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing (docs: mobile/README.md, "Release signing"). Put the
// upload keystore's details in android/key.properties (git-ignored):
//   storeFile=/absolute/path/upload-keystore.jks
//   storePassword=…   keyAlias=upload   keyPassword=…
// Without that file, release builds fall back to the debug key and say so.
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        FileInputStream(keystorePropertiesFile).use { load(it) }
    }
}

android {
    namespace = "com.veriscript.veriscript_mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.veriscript.veriscript_mobile"
        // Isolate integration/benchmark installs from the user's document library.
        // Windows normalizes environment keys to uppercase before Gradle sees them.
        if (providers.gradleProperty("benchmarkApp").orNull == "true" ||
            providers.gradleProperty("BENCHMARKAPP").orNull == "true") {
            applicationIdSuffix = ".benchmark"
        }
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 29
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                storeFile = file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.findByName("release")
                ?: signingConfigs.getByName("debug").also {
                    logger.warn(
                        "VeriScript: android/key.properties not found; the release build " +
                            "is signed with the DEBUG key and cannot be published.",
                    )
                }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
}

dependencies {
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.24.3")
    implementation("org.opencv:opencv:4.12.0")
    // Phase 1 scan camera foundation. Align with the CameraX version used by
    // camera_android_camerax so both camera routes stay binary-compatible.
    implementation("androidx.camera:camera-core:1.6.2")
    implementation("androidx.camera:camera-camera2:1.6.2")
    implementation("androidx.camera:camera-lifecycle:1.6.2")
    // Bundled models: available on first launch with no model download.
    implementation("com.google.mlkit:text-recognition-devanagari:16.0.1")
    implementation("androidx.exifinterface:exifinterface:1.4.2")
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

// Keep clean-clone APKs from silently shipping without the offline model pack.
val verifyOcrModels by tasks.registering {
    val modelSpec = rootProject.file("../rapidocr-models.json")
    val modelAssets = file("src/main/assets/rapidocr")
    inputs.file(modelSpec)
    inputs.dir(modelAssets)
    doLast {
        check(modelAssets.resolve("manifest.json").readText() == modelSpec.readText()) {
            "OCR model manifest differs. Run python tool/prepare_rapidocr.py in mobile/."
        }
        val spec = groovy.json.JsonSlurper().parse(modelSpec) as Map<*, *>
        for (entry in spec["models"] as List<*>) {
            val row = entry as Map<*, *>
            val model = modelAssets.resolve(row["file"] as String)
            check(model.isFile) { "Missing OCR model. Run python tool/prepare_rapidocr.py in mobile/." }
            val digest = MessageDigest.getInstance("SHA-256")
                .digest(model.readBytes()).joinToString("") { "%02x".format(it.toInt() and 255) }
            check(digest == row["sha256"]) { "Damaged OCR model: ${model.name}" }
        }
        for (name in listOf("RapidOCR-LICENSE.txt", "PaddleOCR-LICENSE.txt", "ONNXRuntime-LICENSE.txt")) {
            check(modelAssets.resolve(name).isFile) { "Missing OCR notice: $name. Run python tool/prepare_rapidocr.py." }
        }
    }
}
tasks.named("preBuild") { dependsOn(verifyOcrModels) }
