# Third-party sources

The downloaded files are third-party artifacts, not models trained by DriverGuard.
No field accuracy or fitness for an in-cabin infrared camera is claimed.

- Google MediaPipe, Face Landmarker: https://github.com/google-ai-edge/mediapipe
  and https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker — Apache-2.0 project;
  model source and exact digest recorded in models.json.
- Google MediaPipe EfficientDet-Lite0 int8: https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector
  COCO pretrained object model filtered to the `cell phone` label. Exact downloaded bytes and
  SHA-256 are recorded in models.json. Generic object presence is not proof of driver phone use.
- RISEF/yolov11s-seatbelt: https://huggingface.co/RISEF/yolov11s-seatbelt,
  revision 0187cdb3cd65b14ce450ba3777e59b951dc1620f — AGPL-3.0 per model card and metadata.
- MeetCool/yolov8n-smoking-detection: https://huggingface.co/MeetCool/yolov8n-smoking-detection,
  revision 7d510c6aaa3fbc3048368565d4236993c077dc0a — embedded metadata declares AGPL-3.0;
  the repository has no separate model card/license. Redistribution conditions need review.
- Ultralytics: https://github.com/ultralytics/ultralytics — upstream architecture/export tooling,
  AGPL-3.0 or separate enterprise terms. No Ultralytics Python code is executed by the Android app.
- ONNX Runtime: https://github.com/microsoft/onnxruntime — MIT.
- AndroidX Camera, Activity and Media3: https://android.googlesource.com/platform/frameworks/support/
  and https://github.com/androidx/media — Apache-2.0.
- Gradle wrapper: https://github.com/gradle/gradle — Apache-2.0.
- JUnit: https://github.com/junit-team/junit4 — EPL-1.0 (test only).

These notes do not relicense third-party artifacts. Preserve notices, license texts and
corresponding source obligations when distributing a combined application.

The seven Russian warning WAV files in app/src/main/res/raw were synthesized locally
using the Windows Microsoft Irina Desktop voice from DriverGuard-authored warning text.
They are packaged in the APK; Android does not call a speech service or download a voice.
