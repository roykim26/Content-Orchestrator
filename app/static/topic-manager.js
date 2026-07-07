const state = {
  topics: [],
  importMode: "file",
};

document.addEventListener("DOMContentLoaded", () => {
  bindImportTabs();
  bindSingleForm();
  bindBatchForm();
  bindFilters();
  bindDrawer();
  refreshTopics();
});

function bindImportTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.importMode = button.dataset.mode;
      document.querySelectorAll(".tab").forEach((item) => item.classList.remove("is-active"));
      document.querySelectorAll(".import-pane").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      document.getElementById(`import-${state.importMode}-pane`).classList.add("is-active");
    });
  });
}

function bindSingleForm() {
  const form = document.getElementById("single-topic-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.priority = String(payload.priority || "A").toUpperCase();
    payload.status = String(payload.status || "ready").toLowerCase();
    payload.target_platforms = String(payload.target_platforms || "")
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean);
    if (!payload.brief) {
      payload.brief = null;
    }
    if (!payload.note_account) {
      payload.note_account = null;
    }

    try {
      const topic = await jsonFetch("/topics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      let plannedMessage = "";
      if (document.getElementById("single-plan").checked) {
        const planResult = await jsonFetch(`/topics/${topic.id}/plan`, { method: "POST" });
        plannedMessage = ` Planned ${planResult.task_count} tasks.`;
      }

      showFlash(`Topic created successfully.${plannedMessage}`, "success");
      form.reset();
      document.getElementById("single-plan").checked = true;
      await refreshTopics();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });
}

function bindBatchForm() {
  const form = document.getElementById("batch-import-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const plan = document.getElementById("import-plan").checked;
    const dryRun = document.getElementById("import-dry-run").checked;
    const skipExisting = document.getElementById("import-skip-existing").checked;
    const body = new FormData();
    body.set("plan", String(plan));
    body.set("dry_run", String(dryRun));
    body.set("skip_existing", String(skipExisting));

    if (state.importMode === "file") {
      const fileInput = document.getElementById("import-file");
      const file = fileInput.files[0];
      if (!file) {
        showFlash("Choose a file before running import.", "error");
        return;
      }
      body.set("file", file);
    } else {
      const contentText = document.getElementById("import-text").value.trim();
      if (!contentText) {
        showFlash("Paste CSV or JSON content before running import.", "error");
        return;
      }
      body.set("content_text", contentText);
      body.set("filename_hint", document.getElementById("filename-hint").value);
    }

    try {
      const summary = await jsonFetch("/topics/import", {
        method: "POST",
        body,
      });
      renderImportResults(summary);
      showFlash(
        `Import finished. Created ${summary.created}, planned ${summary.planned}, skipped ${summary.skipped}, errors ${summary.errors}.`,
        summary.errors > 0 ? "error" : "success",
      );
      await refreshTopics();
    } catch (error) {
      showFlash(error.message, "error");
    }
  });
}

function bindFilters() {
  document.getElementById("topic-search").addEventListener("input", renderTopicTable);
  document.getElementById("status-filter").addEventListener("change", renderTopicTable);
}

function bindDrawer() {
  document.getElementById("drawer-close").addEventListener("click", closeDrawer);
  document.querySelectorAll("[data-close-drawer]").forEach((element) => {
    element.addEventListener("click", closeDrawer);
  });
}

async function refreshTopics() {
  try {
    state.topics = await jsonFetch("/topics");
    renderMetrics();
    renderTopicTable();
  } catch (error) {
    showFlash(`Failed to load topics: ${error.message}`, "error");
  }
}

function renderMetrics() {
  const total = state.topics.length;
  const active = state.topics.filter((topic) => ["ready", "planned"].includes(topic.status)).length;
  const draft = state.topics.filter((topic) => topic.status === "draft").length;
  document.getElementById("metric-total").textContent = String(total);
  document.getElementById("metric-active").textContent = String(active);
  document.getElementById("metric-draft").textContent = String(draft);
}

function renderTopicTable() {
  const tbody = document.getElementById("topic-table-body");
  const search = document.getElementById("topic-search").value.trim().toLowerCase();
  const status = document.getElementById("status-filter").value;

  const filtered = state.topics.filter((topic) => {
    const matchesStatus = !status || topic.status === status;
    const matchesSearch =
      !search ||
      topic.master_topic.toLowerCase().includes(search) ||
      topic.target_keyword.toLowerCase().includes(search);
    return matchesStatus && matchesSearch;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No topics match the current filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered
    .map((topic) => {
      const canPlan = topic.status !== "planned";
      return `
        <tr>
          <td>
            <strong>${escapeHtml(topic.master_topic)}</strong>
            <div class="subtle">${escapeHtml(topic.brief || "")}</div>
          </td>
          <td>${escapeHtml(topic.target_keyword)}</td>
          <td>${escapeHtml(topic.topic_cluster)}</td>
          <td>
            <div class="platform-pills">
              ${topic.target_platforms.map((platform) => `<span>${escapeHtml(platform)}</span>`).join("")}
            </div>
          </td>
          <td>${renderNoteAccount(topic.note_account)}</td>
          <td><span class="status-pill">${escapeHtml(topic.status)}</span></td>
          <td>${escapeHtml(topic.priority)}</td>
          <td>
            <button class="secondary" data-open-overview="${topic.id}">Open</button>
            ${
              canPlan
                ? `<button class="secondary" data-topic-id="${topic.id}">Plan</button>`
                : ``
            }
          </td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll("button[data-topic-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const planResult = await jsonFetch(`/topics/${button.dataset.topicId}/plan`, { method: "POST" });
        showFlash(`Planned ${planResult.task_count} tasks for topic ${button.dataset.topicId}.`, "success");
        await refreshTopics();
      } catch (error) {
        showFlash(error.message, "error");
      }
    });
  });

  tbody.querySelectorAll("button[data-open-overview]").forEach((button) => {
    button.addEventListener("click", () => openTopicOverview(button.dataset.openOverview));
  });
}

function renderImportResults(summary) {
  const container = document.getElementById("import-results");
  const results = summary.results || [];
  if (results.length === 0) {
    container.innerHTML = `<div class="empty-state">No rows processed.</div>`;
    return;
  }

  container.innerHTML = results
    .map((result) => {
      const topicLabel = result.master_topic || result.reason || "Untitled row";
      const detail =
        result.status === "planned"
          ? `${result.target_keyword || ""} • ${result.task_count || 0} tasks`
          : result.status === "created"
            ? `${result.target_keyword || ""}`
            : result.reason || (result.target_platforms || []).join(", ");
      return `
        <article class="result-item">
          <header>
            <strong>Row ${result.row}</strong>
            <span class="result-status status-${result.status}">${result.status}</span>
          </header>
          <div>${escapeHtml(topicLabel)}</div>
          <div class="subtle">${escapeHtml(String(detail || ""))}</div>
        </article>
      `;
    })
    .join("");
}

function showFlash(message, kind) {
  const flash = document.getElementById("flash");
  flash.textContent = message;
  flash.className = `flash ${kind}`;
}

async function openTopicOverview(topicId) {
  try {
    const overview = await jsonFetch(`/topics/${topicId}/overview`);
    renderDrawer(overview);
    const drawer = document.getElementById("detail-drawer");
    drawer.classList.remove("hidden");
    drawer.setAttribute("aria-hidden", "false");
  } catch (error) {
    showFlash(error.message, "error");
  }
}

function closeDrawer() {
  const drawer = document.getElementById("detail-drawer");
  drawer.classList.add("hidden");
  drawer.setAttribute("aria-hidden", "true");
}

function renderDrawer(overview) {
  const { topic, tasks, artifacts } = overview;
  const artifactByTaskId = new Map(artifacts.map((artifact) => [artifact.task_id, artifact]));
  const content = document.getElementById("drawer-content");
  content.innerHTML = `
    <section class="drawer-hero">
      <p class="eyebrow">Topic Overview</p>
      <h3>${escapeHtml(topic.master_topic)}</h3>
      <p class="hero-text">${escapeHtml(topic.brief || "No brief provided.")}</p>
      <div class="drawer-meta">
        <span class="drawer-chip">${escapeHtml(topic.status)}</span>
        <span class="drawer-chip">Priority ${escapeHtml(topic.priority)}</span>
        <span class="drawer-chip">${escapeHtml(topic.business_goal)}</span>
        <span class="drawer-chip">${escapeHtml(topic.note_account || "No note account")}</span>
      </div>
    </section>

    <section class="drawer-grid">
      <div class="drawer-card">
        <strong>Keyword</strong>
        <span>${escapeHtml(topic.target_keyword)}</span>
      </div>
      <div class="drawer-card">
        <strong>Cluster</strong>
        <span>${escapeHtml(topic.topic_cluster)}</span>
      </div>
      <div class="drawer-card">
        <strong>Platforms</strong>
        <span>${escapeHtml(topic.target_platforms.join(", "))}</span>
      </div>
      <div class="drawer-card">
        <strong>Note Account</strong>
        <span>${escapeHtml(topic.note_account || "Unassigned")}</span>
      </div>
      <div class="drawer-card">
        <strong>Artifacts</strong>
        <span>${artifacts.length}</span>
      </div>
    </section>

    <section class="drawer-section">
      <div class="drawer-section-head">
        <div>
          <p class="panel-kicker">Execution</p>
          <h2>Tasks</h2>
        </div>
      </div>
      <div class="drawer-list">
        ${tasks.length ? tasks.map((task) => renderTaskCard(task, artifactByTaskId.get(task.id))).join("") : `<div class="empty-state">No tasks yet.</div>`}
      </div>
    </section>

    <section class="drawer-section">
      <div class="drawer-section-head">
        <div>
          <p class="panel-kicker">Artifacts</p>
          <h2>Outputs</h2>
        </div>
      </div>
      <div class="drawer-list">
        ${artifacts.length ? artifacts.map((artifact) => renderArtifactCard(artifact)).join("") : `<div class="empty-state">No artifacts generated yet.</div>`}
      </div>
    </section>
  `;

  content.querySelectorAll("button[data-run-task]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await jsonFetch(`/tasks/${button.dataset.runTask}/run`, { method: "POST" });
        showFlash("Task executed successfully.", "success");
        await refreshTopics();
        await openTopicOverview(topic.id);
      } catch (error) {
        showFlash(error.message, "error");
      }
    });
  });

  content.querySelectorAll("button[data-approve-artifact]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await jsonFetch(`/artifacts/${button.dataset.approveArtifact}/approve`, { method: "POST" });
        showFlash("Artifact approved for publishing.", "success");
        await refreshTopics();
        await openTopicOverview(topic.id);
      } catch (error) {
        showFlash(error.message, "error");
      }
    });
  });

  content.querySelectorAll("button[data-requeue-artifact]").forEach((button) => {
    button.addEventListener("click", async () => {
      const artifactId = button.dataset.requeueArtifact;
      const currentStatus = button.dataset.currentStatus || "";
      const isForce = currentStatus === "publishing";
      const confirmed = window.confirm(
        isForce
          ? "This artifact is currently marked as publishing. Re-queue it back to publish_pending?"
          : "Re-queue this artifact back to publish_pending?",
      );
      if (!confirmed) {
        return;
      }

      const reason = window.prompt(
        "Optional requeue note",
        isForce ? "publisher worker appears stuck" : "manual retry",
      );

      try {
        await jsonFetch(`/artifacts/${artifactId}/requeue`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            requested_by: "topic-manager",
            reason: reason || null,
            clear_error: true,
          }),
        });
        showFlash("Artifact re-queued for publishing.", "success");
        await refreshTopics();
        await openTopicOverview(topic.id);
      } catch (error) {
        showFlash(error.message, "error");
      }
    });
  });
}

function renderTaskCard(task, artifact) {
  return `
    <article class="drawer-item">
      <header>
        <div>
          <strong>${escapeHtml(task.platform)} / ${escapeHtml(task.content_type)}</strong>
          <div class="subtle">${escapeHtml(task.angle)}</div>
        </div>
        <span class="result-status status-${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>
      </header>
      <div class="drawer-meta">
        <span class="drawer-chip">${escapeHtml(task.objective)}</span>
        <span class="drawer-chip">${escapeHtml(task.task_type)}</span>
      </div>
      ${
        artifact
          ? `<div class="subtle">Artifact linked: ${escapeHtml(artifact.id)}</div>`
          : task.error_message
            ? `<div class="subtle">${escapeHtml(task.error_message)}</div>`
            : ``
      }
      <div class="drawer-item-actions">
        ${
          !artifact && task.status !== "completed"
            ? `<button class="secondary" data-run-task="${task.id}">Run Task</button>`
            : ``
        }
      </div>
    </article>
  `;
}

function renderArtifactCard(artifact) {
  const performance = artifact.performance || {};
  const performanceEntries = [
    ["Views", performance.views || 0],
    ["Clicks", performance.clicks || 0],
    ["Conversions", performance.conversions || 0],
    ["Likes", performance.likes || 0],
    ["Shares", performance.shares || 0],
    ["Comments", performance.comments || 0],
  ];
  const canRequeue = artifact.reviewed && ["failed", "publishing"].includes(artifact.status);
  const requeueLabel = artifact.status === "publishing" ? "Force Requeue" : "Requeue";
  const noteAccount = artifact.metadata?.note_account || "";

  return `
    <article class="drawer-item">
      <header>
        <div>
          <strong>${escapeHtml(artifact.platform)} / ${escapeHtml(artifact.content_type)}</strong>
          <div class="subtle">${escapeHtml(artifact.title || "Untitled artifact")}</div>
        </div>
        <span class="result-status status-${escapeHtml(artifact.status)}">${escapeHtml(artifact.status)}</span>
      </header>
      ${artifact.summary ? `<div class="subtle">${escapeHtml(artifact.summary)}</div>` : ``}
      <div class="drawer-meta">
        <span class="drawer-chip">Reviewed: ${artifact.reviewed ? "yes" : "no"}</span>
        <span class="drawer-chip">Published: ${artifact.published ? "yes" : "no"}</span>
        <span class="drawer-chip">Attempts: ${artifact.publish_attempts}</span>
        ${artifact.platform === "note" ? `<span class="drawer-chip">${escapeHtml(noteAccount || "No note account")}</span>` : ``}
      </div>
      ${
        artifact.published_url
          ? `<div class="subtle"><a class="drawer-link" href="${escapeHtml(artifact.published_url)}" target="_blank" rel="noreferrer">Open published URL</a></div>`
          : ``
      }
      <div class="performance-grid">
        ${performanceEntries.map(([label, value]) => `<div><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span></div>`).join("")}
      </div>
      <div class="drawer-item-actions">
        ${
          !artifact.reviewed && ["generated", "review_pending", "rejected"].includes(artifact.status)
            ? `<button class="secondary" data-approve-artifact="${artifact.id}">Approve</button>`
            : ``
        }
        ${
          canRequeue
            ? `<button class="secondary" data-requeue-artifact="${artifact.id}" data-current-status="${escapeHtml(artifact.status)}">${requeueLabel}</button>`
            : ``
        }
      </div>
    </article>
  `;
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      message = payload?.error?.message || payload?.detail || message;
    } catch {
      // ignore json parse errors
    }
    throw new Error(message);
  }
  return response.json();
}

function renderNoteAccount(noteAccount) {
  const value = String(noteAccount || "").trim();
  if (!value) {
    return `<span class="account-pill account-missing">Unassigned</span>`;
  }
  return `<span class="account-pill">${escapeHtml(value)}</span>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
