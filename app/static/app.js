const uidInput = document.querySelector("#uid");
const budgetInput = document.querySelector("#budget");
const imageInput = document.querySelector("#image");
const requestInput = document.querySelector("#request");
const registerBtn = document.querySelector("#registerBtn");
const submitBtn = document.querySelector("#submitBtn");
const form = document.querySelector("#recommendForm");
const result = document.querySelector("#result");
const total = document.querySelector("#total");
const text = document.querySelector("#text");
const items = document.querySelector("#items");
const roomPreview = document.querySelector("#roomPreview");
const roomImage = document.querySelector("#roomImage");
const placements = document.querySelector("#placements");
const renderNote = document.querySelector("#renderNote");

const savedUid = localStorage.getItem("furniture_uid");
if (savedUid) uidInput.value = savedUid;

registerBtn.addEventListener("click", async () => {
  registerBtn.disabled = true;
  try {
    await createUid();
  } finally {
    registerBtn.disabled = false;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  submitBtn.textContent = "生成中...";
  result.classList.remove("hidden");
  total.textContent = "正在连接推荐流...";
  text.textContent = "";
  items.innerHTML = "";
  placements.innerHTML = "";
  roomPreview.classList.add("hidden");
  roomImage.classList.add("hidden");
  roomImage.removeAttribute("src");
  renderNote.classList.add("hidden");
  renderNote.textContent = "";

  const formData = new FormData();
  formData.append("uid", await ensureUid());
  formData.append("request", requestInput.value.trim());
  if (budgetInput.value) formData.append("budget", budgetInput.value);
  if (imageInput.files[0]) formData.append("image", imageInput.files[0]);

  try {
    const response = await fetch("/api/recommend/stream", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(formatApiError(error.detail));
    }
    await readRecommendationStream(response);
  } catch (error) {
    result.classList.remove("hidden");
    total.textContent = "";
    text.textContent = error.message;
    items.innerHTML = "";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "生成推荐";
  }
});

async function readRecommendationStream(response) {
  if (!response.body) {
    throw new Error("浏览器不支持流式响应");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      const line = rawEvent
        .split("\n")
        .find((entry) => entry.startsWith("data:"));
      if (!line) continue;
      const payload = JSON.parse(line.slice(5).trim());
      handleStreamEvent(payload);
    }
  }

  if (buffer.trim()) {
    const line = buffer
      .split("\n")
      .find((entry) => entry.startsWith("data:"));
    if (line) handleStreamEvent(JSON.parse(line.slice(5).trim()));
  }
}

function handleStreamEvent(payload) {
  if (payload.type === "status") {
    total.textContent = payload.message || "处理中...";
    return;
  }
  if (payload.type === "items") {
    renderItems(payload.items || []);
    return;
  }
  if (payload.type === "room") {
    renderRoom(payload.room_image_url || "", payload.placements || []);
    return;
  }
  if (payload.type === "summary") {
    total.textContent = `预计总金额：$${Number(payload.total || 0).toFixed(2)}`;
    text.textContent = payload.text || "";
    return;
  }
  if (payload.type === "final") {
    renderResult(payload.data);
    return;
  }
  if (payload.type === "error") {
    throw new Error(payload.message || "流式推荐失败");
  }
}

function renderResult(data) {
  uidInput.value = data.uid;
  localStorage.setItem("furniture_uid", data.uid);
  result.classList.remove("hidden");
  total.textContent = `预计总金额：$${Number(data.total || 0).toFixed(2)}`;
  text.textContent = data.text;
  renderRoom(data.room_image_url || "", data.placements || []);
  renderItems(data.items || []);
}

async function ensureUid() {
  const currentUid = uidInput.value.trim();
  if (currentUid) return currentUid;
  return createUid();
}

async function createUid() {
  const response = await fetch("/api/register", { method: "POST" });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(formatApiError(error.detail));
  }
  const data = await response.json();
  uidInput.value = data.uid;
  localStorage.setItem("furniture_uid", data.uid);
  return data.uid;
}

function formatApiError(detail) {
  if (!detail) return "请求失败";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => entry.msg || JSON.stringify(entry))
      .join("; ");
  }
  return JSON.stringify(detail);
}

function renderItems(nextItems) {
  items.innerHTML = "";

  for (const item of nextItems) {
    const card = document.createElement("article");
    card.className = "item";
    card.innerHTML = `
      <div class="item-body">
        <h3>${escapeHtml(item.name)}</h3>
        <p>$${Number(item.price || 0).toFixed(2)} · ${escapeHtml(item.category || "furniture")}</p>
        <p>${escapeHtml(item.reason || "")}</p>
        <a href="${escapeHtml(item.url || "https://www.ikea.com/us/en/")}" target="_blank" rel="noreferrer">查看商品</a>
      </div>
    `;
    items.appendChild(card);
  }
}

function renderRoom(imageUrl, nextPlacements) {
  if (!imageUrl && !nextPlacements.length) {
    roomPreview.classList.add("hidden");
    return;
  }

  roomPreview.classList.remove("hidden");
  if (imageUrl) {
    roomImage.src = imageUrl;
    roomImage.classList.remove("hidden");
    renderNote.classList.add("hidden");
    renderNote.textContent = "";
  } else {
    roomImage.classList.add("hidden");
    roomImage.removeAttribute("src");
    renderNote.classList.remove("hidden");
    renderNote.textContent = "未配置图片生成模型，当前只展示摆放方案；配置 OPENAI_API_KEY 后会生成真实整体效果图。";
  }
  placements.innerHTML = "";

  for (const placement of nextPlacements) {
    const row = document.createElement("div");
    row.className = "placement";
    row.innerHTML = `
      <strong>${escapeHtml(placement.item_name || "")}</strong>
      <span>${escapeHtml(placement.zone || "")} · ${escapeHtml(placement.note || "")}</span>
    `;
    placements.appendChild(row);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
