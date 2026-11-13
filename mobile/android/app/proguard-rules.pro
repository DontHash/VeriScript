# ML Kit's Flutter plugin references optional scripts in its language switch.
-keep class ai.onnxruntime.** { *; }
# Only Latin and Devanagari models are bundled and exposed by this app.
-dontwarn com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions$Builder
-dontwarn com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
-dontwarn com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions$Builder
-dontwarn com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions
-dontwarn com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions$Builder
-dontwarn com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions

# Firebase/ML Kit discover these through manifest metadata and reflection.
# R8 full mode requires explicitly retaining the no-argument constructors.
-keep class * implements com.google.firebase.components.ComponentRegistrar {
    public <init>();
    public java.util.List getComponents();
}
