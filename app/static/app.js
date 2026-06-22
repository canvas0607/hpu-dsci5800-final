const uidInput = document.querySelector("#uid");
const accountNameInput = document.querySelector("#accountName");
const budgetInput = document.querySelector("#budget");
const imageInput = document.querySelector("#image");
const requestInput = document.querySelector("#request");
const loginBtn = document.querySelector("#loginBtn");
const guestBtn = document.querySelector("#guestBtn");
const submitBtn = document.querySelector("#submitBtn");
const form = document.querySelector("#recommendForm");
const result = document.querySelector("#result");
const total = document.querySelector("#total");
const identityName = document.querySelector("#identityName");
const identityStatus = document.querySelector("#identityStatus");
const chatOutput = document.querySelector("#chatOutput");
const items = document.querySelector("#items");
const roomPreview = document.querySelector("#roomPreview");
const roomImage = document.querySelector("#roomImage");
const placements = document.querySelector("#placements");
const renderNote = document.querySelector("#renderNote");
const roomPlans = document.querySelector("#roomPlans");
const downloadMarkdownBtn = document.querySelector("#downloadMarkdownBtn");
const downloadPdfBtn = document.querySelector("#downloadPdfBtn");
let latestMarkdown = "";
let latestPlanData = null;
let currentIdentity = null;
let latestUserRequest = "";

initIdentity();

loginBtn.addEventListener("click", async () => {
  const accountName = accountNameInput.value.trim();
  if (!accountName) {
    setIdentityStatus("请输入账户名称");
    accountNameInput.focus();
    return;
  }
  loginBtn.disabled = true;
  try {
    const accountMap = getAccountMap();
    const uid = accountMap[accountName] || await createUid();
    accountMap[accountName] = uid;
    localStorage.setItem("furniture_account_uids", JSON.stringify(accountMap));
    setIdentity({ type: "account", name: accountName, uid });
  } finally {
    loginBtn.disabled = false;
  }
});

guestBtn.addEventListener("click", async () => {
  guestBtn.disabled = true;
  try {
    const guest = buildGuestName();
    setIdentity({ type: "guest", name: guest, uid: "" }, "正在准备游客会话...");
    const uid = await createUid();
    setIdentity({ type: "guest", name: guest, uid });
  } finally {
    guestBtn.disabled = false;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const requestText = requestInput.value.trim();
  submitBtn.disabled = true;
  submitBtn.textContent = "发送中...";
  result.classList.remove("hidden");
  total.textContent = "";
  latestUserRequest = requestText;
  chatOutput.innerHTML = "";
  renderChat("正在连接推荐流...", { status: true });
  latestMarkdown = "";
  latestPlanData = null;
  downloadMarkdownBtn.classList.add("hidden");
  downloadPdfBtn.classList.add("hidden");
  items.innerHTML = "";
  placements.innerHTML = "";
  roomPreview.classList.add("hidden");
  roomImage.classList.add("hidden");
  roomImage.removeAttribute("src");
  renderNote.classList.add("hidden");
  renderNote.textContent = "";
  roomPlans.classList.add("hidden");
  roomPlans.innerHTML = "";

  const formData = new FormData();
  const uid = await ensureUid();
  formData.append("uid", uid);
  formData.append("request", requestText);
  if (budgetInput.value) formData.append("budget", budgetInput.value);
  if (imageInput.files[0]) formData.append("image", imageInput.files[0]);
  requestInput.value = "";

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
    renderChat(error.message);
    items.innerHTML = "";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "发送";
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
    renderChat(payload.message || "处理中...", { status: true });
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
  if (payload.type === "room_plans") {
    renderRoomPlans(payload.room_plans || []);
    total.textContent = `整套预计总金额：${formatMoney(payload.total || 0, payload.currency || "CNY")}`;
    return;
  }
  if (payload.type === "summary") {
    total.textContent = `预计总金额：${formatMoney(payload.total || 0, payload.pricing?.currency || "CNY")}`;
    latestMarkdown = payload.text || "";
    renderChat(latestMarkdown);
    return;
  }
  if (payload.type === "clarify" || payload.type === "refuse") {
    total.textContent = "";
    latestMarkdown = "";
    latestPlanData = null;
    renderChat(payload.message || "");
    downloadMarkdownBtn.classList.add("hidden");
    downloadPdfBtn.classList.add("hidden");
    roomPreview.classList.add("hidden");
    roomPlans.classList.add("hidden");
    items.innerHTML = "";
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
  if (data.uid && currentIdentity) {
    setIdentity({ ...currentIdentity, uid: data.uid });
  }
  result.classList.remove("hidden");
  const currency = data.currency || data.items?.[0]?.currency || "CNY";
  total.textContent = `预计总金额：${formatMoney(data.total || 0, currency)}`;
  latestMarkdown = buildMarkdownPlan(data);
  latestPlanData = data;
  renderChat(data.text || latestMarkdown);
  downloadMarkdownBtn.classList.toggle("hidden", !latestMarkdown);
  downloadPdfBtn.classList.toggle("hidden", !latestPlanData);
  if (data.room_plans && data.room_plans.length > 1) {
    renderRoomPlans(data.room_plans);
    roomPreview.classList.add("hidden");
  } else {
    renderRoom(data.room_image_url || "", data.placements || []);
    roomPlans.classList.add("hidden");
  }
  renderItems(data.items || []);
}

async function ensureUid() {
  if (currentIdentity?.uid) return currentIdentity.uid;
  const identity = currentIdentity || { type: "guest", name: buildGuestName(), uid: "" };
  setIdentity(identity, "正在准备会话...");
  const uid = await createUid();
  setIdentity({ ...identity, uid });
  return uid;
}

async function createUid() {
  const response = await fetch("/api/register", { method: "POST" });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(formatApiError(error.detail));
  }
  const data = await response.json();
  return data.uid;
}

async function initIdentity() {
  const saved = readJson("furniture_identity");
  if (saved?.uid && saved?.name) {
    setIdentity(saved);
    if (saved.type === "account") accountNameInput.value = saved.name;
    return;
  }

  const legacyUid = localStorage.getItem("furniture_uid");
  if (legacyUid) {
    setIdentity({ type: "guest", name: buildGuestName(), uid: legacyUid });
    return;
  }

  const guest = buildGuestName();
  setIdentity({ type: "guest", name: guest, uid: "" }, "正在准备游客会话...");
  try {
    const uid = await createUid();
    setIdentity({ type: "guest", name: guest, uid });
  } catch (error) {
    setIdentityStatus("游客模式，提交时会再次准备会话");
  }
}

function setIdentity(identity, statusText = "") {
  currentIdentity = identity;
  uidInput.value = identity.uid || "";
  identityName.textContent = identity.type === "account" ? `账户：${identity.name}` : identity.name;
  setIdentityStatus(statusText || (identity.uid ? "会话已就绪" : "会话待准备"));
  localStorage.setItem("furniture_identity", JSON.stringify(identity));
  if (identity.uid) localStorage.setItem("furniture_uid", identity.uid);
}

function setIdentityStatus(message) {
  identityStatus.textContent = message;
}

function buildGuestName() {
  const suffix = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `游客-${suffix}`;
}

function getAccountMap() {
  return readJson("furniture_account_uids") || {};
}

function readJson(key) {
  try {
    const value = localStorage.getItem(key);
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
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
    const sourceReason = cleanSourceReason(item.reason || "");
    const card = document.createElement("article");
    card.className = "item";
    card.innerHTML = `
      <div class="item-body">
        <h3>${escapeHtml(item.name)}</h3>
        <p>${formatMoney(item.price || 0, item.currency || "CNY")} · ${escapeHtml(item.category || "furniture")}</p>
        ${sourceReason ? `<p>${escapeHtml(sourceReason)}</p>` : ""}
        <a href="${escapeHtml(item.url || "#")}" target="_blank" rel="noreferrer">查看引用</a>
      </div>
    `;
    items.appendChild(card);
  }
}

function cleanSourceReason(reason) {
  const normalized = String(reason || "").replace(/\s+/g, " ").trim();
  const noisyTerms = [
    "中文 | EN",
    "所有商品",
    "活动和特惠",
    "设计和服务",
    "家居灵感",
    "扫码下载",
    "宜家APP",
    "召回",
    "批次",
    "隐私政策",
  ];
  if (noisyTerms.some((term) => normalized.includes(term))) return "";
  return normalized;
}

downloadMarkdownBtn.addEventListener("click", () => {
  if (!latestMarkdown) return;
  const blob = new Blob([latestMarkdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `furniture-plan-${new Date().toISOString().slice(0, 10)}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
});

downloadPdfBtn.addEventListener("click", async () => {
  if (!latestPlanData) return;
  downloadPdfBtn.disabled = true;
  const originalText = downloadPdfBtn.textContent;
  downloadPdfBtn.textContent = "生成 PDF...";
  try {
    const response = await fetch("/api/plan/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(latestPlanData),
    });
    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || "PDF 生成失败");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `furniture-plan-${new Date().toISOString().slice(0, 10)}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    renderChat(`PDF 生成失败：${error.message}`);
  } finally {
    downloadPdfBtn.disabled = false;
    downloadPdfBtn.textContent = originalText;
  }
});

function renderChat(markdownText, options = {}) {
  chatOutput.innerHTML = "";
  if (latestUserRequest) {
    const userMessage = document.createElement("div");
    userMessage.className = "chat-message user-message";
    userMessage.textContent = latestUserRequest;
    chatOutput.appendChild(userMessage);
  }
  const blocks = String(markdownText || "")
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

  for (const block of blocks) {
    const message = document.createElement("div");
    message.className = options.status ? "chat-message status-message" : "chat-message";
    message.innerHTML = inlineChatMarkup(block);
    chatOutput.appendChild(message);
  }
  chatOutput.scrollIntoView({ block: "end", behavior: "smooth" });
}

function inlineChatMarkup(block) {
  const normalized = escapeHtml(block)
    .replace(/^#{1,4}\s*/gm, "")
    .replace(/^\-\s*/gm, "• ")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br />");
  return normalized;
}

function buildMarkdownPlan(data) {
  const currency = data.currency || "CNY";
  const lines = [
    "# 家具搭配方案",
    "",
    data.text || "",
    "",
    `**预计总金额：${formatMoney(data.total || 0, currency)}**`,
  ];
  if (data.room_plans && data.room_plans.length) {
    lines.push("\n## 分房间商品清单");
    for (const plan of data.room_plans) {
      lines.push(`\n### ${plan.room_name}`);
      if (plan.items?.length) {
        lines.push("| 商品 | 品类 | 价格 | 链接 |");
        lines.push("|---|---|---:|---|");
        for (const item of plan.items) {
          lines.push(`| ${item.name} | ${item.category} | ${formatMoney(item.price, item.currency || "CNY")} | ${item.url || ""} |`);
        }
      }
    }
  } else if (data.items?.length) {
    lines.push("\n## 商品清单");
    lines.push("| 商品 | 品类 | 价格 | 链接 |");
    lines.push("|---|---|---:|---|");
    for (const item of data.items) {
      lines.push(`| ${item.name} | ${item.category} | ${formatMoney(item.price, item.currency || "CNY")} | ${item.url || ""} |`);
    }
  }
  return lines.filter(Boolean).join("\n");
}

function formatMoney(value, currency) {
  const amount = Number(value || 0).toFixed(2);
  if (currency === "CNY") return `¥${amount}`;
  if (currency === "USD") return `$${amount}`;
  return `${amount} ${currency || ""}`.trim();
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

function renderRoomPlans(plans) {
  if (!plans.length) {
    roomPlans.classList.add("hidden");
    return;
  }
  roomPlans.classList.remove("hidden");
  roomPlans.innerHTML = "";

  for (const plan of plans) {
    const section = document.createElement("section");
    section.className = "room-plan";
    const image = plan.room_image_url
      ? `<img src="${escapeHtml(plan.room_image_url)}" alt="${escapeHtml(plan.room_name)}整体效果图" class="room-plan-image" />`
      : `<p class="render-note">未配置图片生成模型，当前只展示 ${escapeHtml(plan.room_name)} 的摆放方案。</p>`;
    const placementRows = (plan.placements || [])
      .map(
        (placement) => `
          <div class="placement">
            <strong>${escapeHtml(placement.item_name || "")}</strong>
            <span>${escapeHtml(placement.zone || "")} · ${escapeHtml(placement.note || "")}</span>
          </div>
        `
      )
      .join("");
    section.innerHTML = `
      <h3>${escapeHtml(plan.room_name || "空间方案")}</h3>
      ${image}
      <div class="placements">${placementRows}</div>
      <div class="chat-output room-chat">${chatBlocks(plan.text || "")}</div>
    `;
    roomPlans.appendChild(section);
  }
}

function chatBlocks(markdownText) {
  return String(markdownText || "")
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => `<div class="chat-message">${inlineChatMarkup(block)}</div>`)
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
