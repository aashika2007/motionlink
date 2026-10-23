// Webcam hand tracking with MediaPipe Tasks Vision (loaded from its CDN on first use).
// Emits a cursor in normalised 0..1 canvas coordinates (mirrored, so moving your hand
// right moves the cursor right) plus a debounced pinch state:
//   onHand({present, x, y, pinch, pressed, released})
// If the camera or the model is unavailable the caller keeps working with the mouse.
// Needs http://127.0.0.1 / localhost or HTTPS for camera access.

const MP_VERSION = "0.10.14";
const CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}`;
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const PINCH_ON = 0.33;   // thumb–index distance / palm size
const PINCH_OFF = 0.48;
const REACH = 0.12;      // ignore this margin of the camera frame so the edges are easy to reach

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const clamp01 = (v) => Math.min(1, Math.max(0, v));

export class GestureController {
  constructor(video, { onHand = () => {}, onStatus = () => {} } = {}) {
    this.video = video;
    this.onHand = onHand;
    this.onStatus = onStatus;
    this.stream = null;
    this.landmarker = null;
    this.running = false;
    this.pinching = false;
    this.cursor = null;
    this.lastVideoTime = -1;
    this.handsReady = false;
  }

  get cameraOn() { return !!this.stream; }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser can't open a webcam. Use mouse or touch instead.");
    }
    this.onStatus("Starting camera…");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false,
      });
    } catch (err) {
      throw new Error(err?.name === "NotAllowedError"
        ? "Camera permission was denied. Allow camera access in the browser, or use the mouse."
        : "No camera found. Use mouse or touch instead.");
    }
    this.video.srcObject = this.stream;
    await this.video.play();
    this.running = true;
    this.onStatus("Loading hand tracking…");
    try {
      await this._loadModel();
      this.handsReady = true;
      this.onStatus("Show one hand. Pinch to grab.");
    } catch (err) {
      console.warn("MediaPipe failed to load", err);
      this.onStatus("Hand tracking needs internet to load MediaPipe. Use the mouse.");
    }
    this._loop();
  }

  async _loadModel() {
    // Pinned version first (reproducible); fall back to the latest release if it fails.
    let base = CDN, vision;
    try {
      vision = await import(/* @vite-ignore */ `${CDN}/vision_bundle.mjs`);
    } catch (err) {
      console.warn(`MediaPipe ${MP_VERSION} failed to load, trying latest`, err);
      base = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest";
      vision = await import(/* @vite-ignore */ `${base}/vision_bundle.mjs`);
    }
    const files = await vision.FilesetResolver.forVisionTasks(`${base}/wasm`);
    const opts = (delegate) => ({
      baseOptions: { modelAssetPath: MODEL_URL, delegate },
      runningMode: "VIDEO", numHands: 1,
      minHandDetectionConfidence: 0.5, minTrackingConfidence: 0.5,
    });
    try {
      this.landmarker = await vision.HandLandmarker.createFromOptions(files, opts("GPU"));
    } catch {
      this.landmarker = await vision.HandLandmarker.createFromOptions(files, opts("CPU"));
    }
  }

  _loop() {
    if (!this.running) return;
    requestAnimationFrame(() => this._loop());
    if (!this.landmarker || this.video.readyState < 2) return;
    if (this.video.currentTime === this.lastVideoTime) return;
    this.lastVideoTime = this.video.currentTime;
    let res;
    try {
      res = this.landmarker.detectForVideo(this.video, performance.now());
    } catch (err) {
      console.warn(err);
      return;
    }
    const lm = res?.landmarks?.[0];
    if (!lm) {
      if (this.pinching) { this.pinching = false; this.onHand({ present: false, pinch: false, released: true }); }
      else this.onHand({ present: false, pinch: false });
      this.cursor = null;
      return;
    }
    const thumb = lm[4], index = lm[8];
    const palm = Math.max(1e-3, dist(lm[0], lm[9]));
    const ratio = dist(thumb, index) / palm;
    const was = this.pinching;
    if (!was && ratio < PINCH_ON) this.pinching = true;
    else if (was && ratio > PINCH_OFF) this.pinching = false;

    // Mirror x so moving your hand right moves the cursor right.
    const raw = { x: 1 - (thumb.x + index.x) / 2, y: (thumb.y + index.y) / 2 };
    const mapped = {
      x: clamp01((raw.x - REACH) / (1 - 2 * REACH)),
      y: clamp01((raw.y - REACH) / (1 - 2 * REACH)),
    };
    const a = this.pinching ? 0.45 : 0.6; // steadier while dragging
    this.cursor = this.cursor
      ? { x: this.cursor.x + a * (mapped.x - this.cursor.x), y: this.cursor.y + a * (mapped.y - this.cursor.y) }
      : mapped;
    this.onHand({
      present: true, x: this.cursor.x, y: this.cursor.y, pinch: this.pinching,
      pressed: !was && this.pinching, released: was && !this.pinching, ratio,
    });
  }

  stop() {
    this.running = false;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    this.pinching = false;
    this.cursor = null;
  }
}
