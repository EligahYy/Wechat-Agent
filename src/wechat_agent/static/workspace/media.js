import { $, esc, api, notice } from "./client.js";
let imageUrl,
  generation = 0;
export function closeImage() {
  generation++;
  if (imageUrl) URL.revokeObjectURL(imageUrl);
  imageUrl = null;
}
async function open(mid, refresh = false) {
  const pane = $("#image-view");
  if (!pane) return;
  const current = ++generation;
  pane.hidden = false;
  pane.innerHTML = '<p role="status">正在从本机读取图片…</p>';
  const response = await fetch(
    "/api/workspace/images/" +
      encodeURIComponent(mid) +
      (refresh ? "?refresh=true" : ""),
  );
  if (!response.ok) {
    const d = await response.json();
    throw Error(d.error || "图片读取失败");
  }
  const blob = await response.blob();
  const state = await api("images/" + encodeURIComponent(mid) + "/text");
  if (current !== generation || !pane.isConnected || !$("dialog").open) return;
  if (imageUrl) URL.revokeObjectURL(imageUrl);
  imageUrl = URL.createObjectURL(blob);
  pane.innerHTML = `<section class="insight-card"><div class="toolbar"><h3>原图与识别文字</h3><button id="refresh-image" data-mid="${esc(mid)}">重新读取原图</button><button id="hide-image">收起图片</button></div><img class="source-image" src="${imageUrl}" alt="本机归档的微信图片">${response.headers.get("X-Wechat-Media-Quality") === "thumbnail" ? '<p class="meta">当前为缩略图；可在微信下载原图后重试，文字需仔细核对。</p>' : ""}<p class="meta">${esc(state.ocr.note)}。OCR不调用DeepSeek；确认后才将核对文本用于下一轮分析。</p><button id="recognize-image" data-mid="${esc(mid)}" ${state.ocr.available ? "" : "disabled"}>在本机识别文字</button><form id="image-text-form" data-mid="${esc(mid)}" data-version="${state.version}"><label>核对图片中的文字<textarea name="text" rows="7" maxlength="20000" required>${esc(state.confirmed_text || state.candidate_text)}</textarea></label><button class="primary">确认文字并用于后续分析</button></form><p class="meta">识别候选不会直接作为事实；原图与原聊天保持不变。价卡的表格、计价条件和有效期仍需人工核对。</p></section>`;
  pane.scrollIntoView({
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
    block: "nearest",
  });
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (
    !b.dataset.image &&
    !["recognize-image", "hide-image", "refresh-image"].includes(b.id)
  )
    return;
  b.disabled = true;
  try {
    if (b.dataset.image) await open(b.dataset.image);
    else if (b.id === "refresh-image") await open(b.dataset.mid, true);
    else if (b.id === "hide-image") {
      $("#image-view").hidden = true;
      closeImage();
    } else {
      const originalText = b.textContent;
      b.textContent = "正在本机识别…";
      const form = $("#image-text-form"),
        token = generation;
      form.elements.text.disabled = true;
      form.querySelector("button").disabled = true;
      try {
        const data = await api(
          "images/" + encodeURIComponent(b.dataset.mid) + "/recognize",
          {},
        );
        if (token !== generation || !form.isConnected) return;
        form.dataset.version = data.version;
        form.elements.text.value = data.candidate_text;
        notice("识别完成，尚未用于模型。请对照图片核对并确认。");
      } finally {
        b.textContent = originalText;
        form.elements.text.disabled = false;
        form.querySelector("button").disabled = false;
      }
    }
  } catch (error) {
    notice(error.message);
  } finally {
    if (b.isConnected) b.disabled = false;
  }
});
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "image-text-form") return;
  e.preventDefault();
  const b = e.target.querySelector("button");
  b.disabled = true;
  try {
    const data = await api(
      "images/" + encodeURIComponent(e.target.dataset.mid) + "/text",
      {
        version: Number(e.target.dataset.version),
        text: new FormData(e.target).get("text"),
      },
    );
    e.target.dataset.version = data.version;
    await api("queue/refresh", {});
    notice("核对文本已保存，自动队列将重新整理相关客户；原图未修改。");
  } catch (error) {
    notice(error.message);
  } finally {
    b.disabled = false;
  }
});
