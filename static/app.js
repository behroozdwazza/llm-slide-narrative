const form = document.querySelector("#narrative-form");
const slidesEl = document.querySelector("#slides");
const emptyState = document.querySelector("#empty-state");
const loadingState = document.querySelector("#loading-state");
const noticesEl = document.querySelector("#notices");
const rawOutput = document.querySelector("#raw-output");
const copyButton = document.querySelector("#copy-button");
const keyStatus = document.querySelector("#key-status");
const apiKeyInput = document.querySelector("#api-key-input");
const generateButton = document.querySelector("#generate-button");
const generateButtonLabel = document.querySelector("#generate-button-label");
const loadingMessage = document.querySelector("#loading-message");
const loadingTimer = document.querySelector("#loading-timer");
const formProcessing = document.querySelector("#form-processing");
const formProcessingTimer = document.querySelector("#form-processing-timer");
const accessCodeField = document.querySelector("#access-code-field");

let lastNarrative = "";
let serverKeyConfigured = false;
let uploadLimitMb = 256;
let isGenerating = false;
let loadingInterval = null;
let loadingStartedAt = 0;

const loadingMessages = [
  "Reading the uploaded files...",
  "Preparing the slide-by-slide context...",
  "Sending the request to the selected model...",
  "Drafting memorization-ready narration...",
  "Longer decks can take a minute or two...",
  "Still working. Please keep this page open...",
  "Finishing the script and formatting the slides...",
];

document.querySelectorAll("input[type=file]").forEach((input) => {
  input.addEventListener("change", () => {
    const target = document.querySelector(`[data-file-label="${input.name}"]`);
    target.textContent = input.files[0]?.name || "Choose file";
  });
});

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    serverKeyConfigured = Boolean(data.openai_key_configured);
    uploadLimitMb = data.upload_limit_mb || uploadLimitMb;
    if (accessCodeField) {
      accessCodeField.hidden = !data.access_code_required;
    }
    updateKeyStatus();
  } catch {
    keyStatus.textContent = "Offline";
  }
}

if (apiKeyInput) {
  apiKeyInput.addEventListener("input", updateKeyStatus);
}

function updateKeyStatus() {
  const hasSessionKey = apiKeyInput && apiKeyInput.value.trim().length > 0;
  const ready = serverKeyConfigured || hasSessionKey;
  keyStatus.textContent = ready ? "LLM ready" : "Preview mode";
  keyStatus.dataset.ready = ready ? "true" : "false";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isGenerating) return;
  const sizeError = validateUploadSize();
  if (sizeError) {
    renderError(sizeError);
    return;
  }
  setLoading(true);
  await waitForPaint();
  const body = new FormData(form);

  try {
    const response = await fetch("/api/generate", { method: "POST", body });
    const data = await readResponse(response);
    if (!response.ok) throw new Error(data.error || "Something went wrong.");
    renderResult(data);
  } catch (error) {
    renderError(
      error.message === "Failed to fetch"
        ? "The browser lost contact with the local app while generating. Refresh the page and try again; if your files are large, compress the deck or export it as a smaller PDF."
        : error.message
    );
  } finally {
    setLoading(false);
  }
});

copyButton.addEventListener("click", async () => {
  if (!lastNarrative) return;
  await navigator.clipboard.writeText(lastNarrative);
  copyButton.textContent = "Copied";
  setTimeout(() => {
    copyButton.textContent = "Copy all";
  }, 1400);
});

function setLoading(isLoading) {
  loadingState.hidden = !isLoading;
  formProcessing.hidden = !isLoading;
  emptyState.hidden = true;
  isGenerating = isLoading;
  form.classList.toggle("is-processing", isLoading);
  generateButton.disabled = isLoading;
  generateButtonLabel.textContent = isLoading ? "Generating..." : "Generate narrative";
  if (isLoading) {
    slidesEl.innerHTML = "";
    rawOutput.hidden = true;
    noticesEl.hidden = true;
    copyButton.disabled = true;
    startLoadingProgress();
  } else {
    stopLoadingProgress();
  }
}

function startLoadingProgress() {
  loadingStartedAt = Date.now();
  let messageIndex = 0;
  loadingMessage.textContent = loadingMessages[0];
  loadingTimer.textContent = "Elapsed: 0s";
  formProcessingTimer.textContent = "Elapsed: 0s";
  clearInterval(loadingInterval);
  loadingInterval = setInterval(() => {
    const elapsedSeconds = Math.floor((Date.now() - loadingStartedAt) / 1000);
    const nextIndex = Math.min(
      loadingMessages.length - 1,
      Math.floor(elapsedSeconds / 12)
    );
    if (nextIndex !== messageIndex) {
      messageIndex = nextIndex;
      loadingMessage.textContent = loadingMessages[messageIndex];
    }
    loadingTimer.textContent = `Elapsed: ${elapsedSeconds}s`;
    formProcessingTimer.textContent = `Elapsed: ${elapsedSeconds}s`;
  }, 1000);
}

function stopLoadingProgress() {
  clearInterval(loadingInterval);
  loadingInterval = null;
}

function renderResult(data) {
  noticesEl.innerHTML = "";
  const notices = data.notices || [];
  noticesEl.hidden = notices.length === 0;
  notices.forEach((notice) => {
    const item = document.createElement("p");
    item.textContent = notice;
    noticesEl.appendChild(item);
  });

  if (data.raw_text) {
    rawOutput.textContent = data.raw_text;
    rawOutput.hidden = false;
    slidesEl.innerHTML = "";
    lastNarrative = data.raw_text;
    copyButton.disabled = false;
    return;
  }

  const slides = data.slides || [];
  slidesEl.innerHTML = "";
  rawOutput.hidden = true;
  emptyState.hidden = slides.length > 0;
  lastNarrative = slides.map(formatSlideForCopy).join("\n\n");
  copyButton.disabled = slides.length === 0;

  slides.forEach((slide) => {
    const article = document.createElement("article");
    article.className = "slide-card";
    article.innerHTML = `
      <div class="slide-topline">
        <span>Slide ${escapeHtml(slide.slide_number ?? "")}</span>
        <small>${escapeHtml(slide.estimated_time || "")}</small>
      </div>
      <h3>${escapeHtml(slide.slide_title || "Untitled slide")}</h3>
      <p class="narrative">${escapeHtml(slide.narrative || "")}</p>
      <div class="meta-row">
        <p><strong>Delivery</strong>${escapeHtml(slide.delivery_note || "")}</p>
        <p><strong>Alignment</strong>${escapeHtml(slide.source_alignment || "")}</p>
      </div>
    `;
    slidesEl.appendChild(article);
  });
}

function renderError(message) {
  slidesEl.innerHTML = "";
  rawOutput.hidden = true;
  noticesEl.hidden = false;
  noticesEl.innerHTML = `<p>${escapeHtml(message)}</p>`;
  emptyState.hidden = false;
  emptyState.textContent = "The narrative could not be generated yet.";
  lastNarrative = "";
  copyButton.disabled = true;
}

function validateUploadSize() {
  const files = [...document.querySelectorAll("input[type=file]")]
    .flatMap((input) => [...input.files]);
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  const totalMb = totalBytes / (1024 * 1024);
  if (totalMb > uploadLimitMb) {
    return `The selected files are ${totalMb.toFixed(1)} MB total. Please keep the combined upload under ${uploadLimitMb} MB.`;
  }
  return "";
}

async function readResponse(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
}

function waitForPaint() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

function formatSlideForCopy(slide) {
  return [
    `Slide ${slide.slide_number}: ${slide.slide_title}`,
    slide.narrative,
    `Delivery: ${slide.delivery_note || ""}`,
    `Alignment: ${slide.source_alignment || ""}`,
  ].join("\n");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

checkHealth();
