const $ = (id) => document.getElementById(id);

const state = {
  busy: false,
};

function log(line) {
  const el = $("log");
  const ts = new Date().toLocaleTimeString();
  el.textContent += `[${ts}] ${line}\n`;
  el.scrollTop = el.scrollHeight;
}

function setBusy(on) {
  state.busy = on;
  ["btnGenerate", "btnRun", "btnPublish", "btnCopy"].forEach((id) => {
    $(id).disabled = on;
  });
}

async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (options.body != null && headers["Content-Type"] == null) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, {
    ...options,
    headers,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text || "Invalid JSON" };
  }
  if (!res.ok) {
    const msg =
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail ?? data, null, 2);
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return data;
}

async function refreshEnv() {
  const badge = $("envBadge");
  try {
    const data = await api("/api/env", { method: "GET" });
    if (data.configured) {
      badge.textContent = ".env: всё настроено";
      badge.className = "env-badge ok";
    } else {
      const keys = data.missing.map((m) => m.key).join(", ");
      badge.textContent = `.env: не хватает — ${keys}`;
      badge.className = "env-badge warn";
    }
  } catch (e) {
    badge.textContent = "Не удалось проверить /api/env";
    badge.className = "env-badge warn";
    log(String(e.message || e));
  }
}

function readTopic() {
  return $("topic").value.trim();
}

function readOptions() {
  return {
    dry_run: $("dryRun").checked,
    no_image: $("noImage").checked,
    image_size: $("imageSize").value,
  };
}

function updateCharCount() {
  const t = $("postBody").value;
  $("charCount").textContent = `${t.length} символов`;
}

$("postBody").addEventListener("input", updateCharCount);

$("btnCopy").addEventListener("click", async () => {
  const text = $("postBody").value;
  if (!text.trim()) {
    log("Нечего копировать.");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    log("Пост скопирован в буфер обмена.");
  } catch (e) {
    log("Копирование не удалось: " + (e.message || e));
  }
});

$("btnGenerate").addEventListener("click", async () => {
  const topic = readTopic();
  if (!topic) {
    log("Введи тему.");
    return;
  }
  setBusy(true);
  log("Запрос /api/generate …");
  try {
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({ topic }),
    });
    $("postBody").value = data.post;
    $("imagePrompt").value = data.image_prompt;
    updateCharCount();
    log(`Готово. Символов: ${data.char_count}.`);
  } catch (e) {
    log("Ошибка: " + e.message);
  } finally {
    setBusy(false);
  }
});

$("btnRun").addEventListener("click", async () => {
  const topic = readTopic();
  const post = $("postBody").value.trim();
  const image_prompt = $("imagePrompt").value.trim();
  const opts = readOptions();

  if (!topic && (!post || !image_prompt)) {
    log("Укажи тему слева или заполни и пост, и промпт картинки.");
    return;
  }

  const body = {
    ...opts,
    topic: topic || null,
    post: post || null,
    image_prompt: image_prompt || null,
  };

  setBusy(true);
  log(`Запрос /api/run (dry_run=${opts.dry_run}, no_image=${opts.no_image}) …`);
  try {
    const data = await api("/api/run", {
      method: "POST",
      body: JSON.stringify(body),
    });
    $("postBody").value = data.post;
    $("imagePrompt").value = data.image_prompt;
    updateCharCount();
    if (data.image_path) log("Картинка: " + data.image_path);
    if (data.image_error) log("Предупреждение по картинке: " + data.image_error);
    if (data.published) log("Опубликовано. post_id: " + data.post_id);
    else log(data.dry_run ? "Dry-run завершён без публикации." : "Готово.");
  } catch (e) {
    log("Ошибка: " + e.message);
  } finally {
    setBusy(false);
  }
});

$("btnPublish").addEventListener("click", async () => {
  const post = $("postBody").value.trim();
  if (!post) {
    log("Сначала сгенерируй или вставь текст поста.");
    return;
  }
  const image_prompt = $("imagePrompt").value.trim();
  const { no_image, image_size } = readOptions();

  if (!no_image && !image_prompt) {
    log("Для публикации с картинкой заполни промпт или включи «Без картинки» слева.");
    return;
  }

  if (!window.confirm("Опубликовать этот пост в LinkedIn?")) {
    log("Публикация отменена пользователем.");
    return;
  }

  setBusy(true);
  log("Запрос /api/publish …");
  try {
    const data = await api("/api/publish", {
      method: "POST",
      body: JSON.stringify({ post, image_prompt: image_prompt || null, no_image, image_size }),
    });
    log("Опубликовано. post_id: " + data.post_id);
    if (data.image_path) log("Файл изображения: " + data.image_path);
  } catch (e) {
    log("Ошибка: " + e.message);
  } finally {
    setBusy(false);
  }
});

refreshEnv();
updateCharCount();
log("Интерфейс готов. Убедись, что сервер запущен (uvicorn backend.app:app).");
