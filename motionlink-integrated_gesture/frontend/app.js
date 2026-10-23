const videoInput = document.getElementById("video-input");
const videoPlayer = document.getElementById("video-player");
const uploadZone = document.getElementById("upload-zone");
const videoMessage = document.getElementById("video-message");
const canvas = document.getElementById("circuit-canvas");
const ctx = canvas.getContext("2d");

let currentVideoUrl = null;

function loadVideo(file) {
  if (!file) return;
  if (!file.type.startsWith("video/")) {
    videoMessage.textContent = "Please select a supported video file.";
    return;
  }

  if (currentVideoUrl) URL.revokeObjectURL(currentVideoUrl);
  currentVideoUrl = URL.createObjectURL(file);
  videoPlayer.src = currentVideoUrl;
  videoPlayer.hidden = false;
  uploadZone.hidden = true;

  document.getElementById("video-status").textContent = "LOADED";
  document.getElementById("tracking-status").textContent = "READY";
  videoMessage.textContent = `${file.name} loaded. Tracking must be connected to the Python backend before trajectories can be generated.`;
}

videoInput.addEventListener("change", event => loadVideo(event.target.files[0]));

document.getElementById("upload-cta").addEventListener("click", () => {
  videoInput.click();
});

uploadZone.addEventListener("dragover", event => {
  event.preventDefault();
  uploadZone.style.borderColor = "var(--accent)";
});

uploadZone.addEventListener("dragleave", () => {
  uploadZone.style.borderColor = "";
});

uploadZone.addEventListener("drop", event => {
  event.preventDefault();
  uploadZone.style.borderColor = "";
  loadVideo(event.dataTransfer.files[0]);
});

document.querySelectorAll(".nav-item").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active"));
    button.classList.add("active");

    const pages = {
      overview: ["Racing Intelligence", null],
      tracking: ["Video Tracking", "video-workspace"],
      racing: ["Racing Line Editor", "circuit-workspace"],
      analysis: ["Performance Analysis", "analysis-workspace"]
    };

    const [title, targetId] = pages[button.dataset.page];
    document.getElementById("page-title").textContent = title;

    if (targetId) {
      document.getElementById(targetId).scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  });
});

function drawEmptyCircuit() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  // Subtle grid for the editor. This is not a circuit or racing line.
  ctx.strokeStyle = "#202a34";
  ctx.lineWidth = 1;
  for (let x = 20; x < rect.width; x += 25) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, rect.height);
    ctx.stroke();
  }
  for (let y = 20; y < rect.height; y += 25) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(rect.width, y);
    ctx.stroke();
  }
}

window.addEventListener("resize", drawEmptyCircuit);
drawEmptyCircuit();
