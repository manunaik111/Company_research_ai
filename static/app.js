const chatLog = document.getElementById("chat-log");
const emptyState = document.getElementById("empty-state");
const form = document.getElementById("research-form");
const input = document.getElementById("query-input");
const submitBtn = document.getElementById("submit-btn");
const resultTemplate = document.getElementById("result-template");
const modelInput = document.getElementById("model-input");
const discordBotTokenInput = document.getElementById("discord-bot-token");
const discordChannelIdInput = document.getElementById("discord-channel-id");
const discordSaveBtn = document.getElementById("discord-save-btn");
const discordConfigStatus = document.getElementById("discord-config-status");

const PROGRESS_STEPS = [
    "Searching for the company...",
    "Crawling the website...",
    "Analyzing with AI...",
    "Identifying competitors...",
];

let discordSettings = {
    configured: false,
    source: "none",
    message: "Discord is not configured yet.",
};

loadDiscordSettings();

discordSaveBtn.addEventListener("click", saveDiscordSettings);

document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
        input.value = chip.dataset.example;
        form.requestSubmit();
    });
});

document.getElementById("new-research-btn").addEventListener("click", () => {
    chatLog.innerHTML = "";
    chatLog.appendChild(emptyState);
    emptyState.style.display = "block";
});

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;

    emptyState.style.display = "none";
    addUserMessage(query);
    input.value = "";
    submitBtn.disabled = true;

    const progressEl = addProgressMessage();
    const progressTimer = cycleProgressText(progressEl);

    try {
        const resp = await fetch("/api/research", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query,
                model: modelInput.value.trim() || null,
            }),
        });
        const payload = await resp.json();

        clearInterval(progressTimer);
        progressEl.remove();

        if (!payload.success) {
            addErrorMessage(payload.error || "Something went wrong. Please try again.");
        } else {
            renderResultCard(payload.data);
        }
    } catch (err) {
        clearInterval(progressTimer);
        progressEl.remove();
        addErrorMessage("Network error: could not reach the research service.");
    } finally {
        submitBtn.disabled = false;
        chatLog.scrollTop = chatLog.scrollHeight;
    }
});

function addUserMessage(text) {
    const el = document.createElement("div");
    el.className = "user-message";
    el.textContent = text;
    chatLog.appendChild(el);
    chatLog.scrollTop = chatLog.scrollHeight;
}

function addProgressMessage() {
    const el = document.createElement("div");
    el.className = "progress-message";
    el.innerHTML = `<span class="spinner"></span><span class="progress-text">${PROGRESS_STEPS[0]}</span>`;
    chatLog.appendChild(el);
    chatLog.scrollTop = chatLog.scrollHeight;
    return el;
}

function cycleProgressText(progressEl) {
    let i = 0;
    const textEl = progressEl.querySelector(".progress-text");
    return setInterval(() => {
        i = (i + 1) % PROGRESS_STEPS.length;
        textEl.textContent = PROGRESS_STEPS[i];
    }, 2200);
}

function addErrorMessage(message) {
    const el = document.createElement("div");
    el.className = "error-message";
    el.textContent = message;
    chatLog.appendChild(el);
}

function renderResultCard(data) {
    const node = resultTemplate.content.cloneNode(true);
    const card = node.querySelector(".result-card");

    card.querySelector(".result-company-name").textContent = data.company_name;
    const websiteLink = card.querySelector(".result-website");
    websiteLink.textContent = data.website;
    websiteLink.href = data.website;

    card.querySelector(".result-phone").textContent = data.phone || "Not publicly listed";
    card.querySelector(".result-address").textContent = data.address || "Not publicly listed";
    card.querySelector(".result-summary").textContent = data.summary || "";

    const productsEl = card.querySelector(".result-products");
    (data.products_services || []).forEach((p) => {
        const span = document.createElement("span");
        span.textContent = p;
        productsEl.appendChild(span);
    });
    if (!data.products_services || data.products_services.length === 0) {
        productsEl.innerHTML = '<span>No details found</span>';
    }

    const painEl = card.querySelector(".result-pain-points");
    (data.pain_points || []).forEach((p) => {
        const li = document.createElement("li");
        li.textContent = p;
        painEl.appendChild(li);
    });

    const compEl = card.querySelector(".result-competitors");
    (data.competitors || []).forEach((c) => {
        const div = document.createElement("div");
        div.className = "competitor-item";
        const nameDiv = document.createElement("div");
        nameDiv.className = "name";
        nameDiv.textContent = c.name;
        div.appendChild(nameDiv);
        if (c.website) {
            const a = document.createElement("a");
            a.href = c.website;
            a.target = "_blank";
            a.rel = "noopener";
            a.textContent = c.website;
            div.appendChild(a);
        }
        compEl.appendChild(div);
    });
    if (!data.competitors || data.competitors.length === 0) {
        compEl.innerHTML = '<span class="hint-text">No competitors identified.</span>';
    }

    const warningsEl = card.querySelector(".result-warnings");
    if (data.warnings && data.warnings.length > 0) {
        warningsEl.textContent = "Note: " + data.warnings.join(" · ");
    }

    card.querySelector(".btn-download").addEventListener("click", () => downloadPdf(data));
    const discordBtn = card.querySelector(".btn-discord");
    const discordStatusEl = card.querySelector(".discord-status");
    discordBtn.addEventListener("click", () => sendToDiscord(data, discordBtn, discordStatusEl));

    chatLog.appendChild(node);
    chatLog.scrollTop = chatLog.scrollHeight;
    maybeAutoSendToDiscord(data, discordBtn, discordStatusEl);
}

async function downloadPdf(data) {
    const resp = await fetch("/api/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data }),
    });
    if (!resp.ok) {
        alert("Could not generate PDF. Please try again.");
        return;
    }
    const blob = await resp.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.company_name.replace(/\s+/g, "_").toLowerCase()}_research_report.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
}

async function sendToDiscord(data, btn, statusEl) {
    return sendToDiscordRequest(data, btn, statusEl, false);
}

async function maybeAutoSendToDiscord(data, btn, statusEl) {
    const applicantName = document.getElementById("applicant-name").value.trim();
    const applicantEmail = document.getElementById("applicant-email").value.trim();

    if (!applicantName || !applicantEmail) {
        statusEl.textContent = "Auto-send skipped: add applicant name and email in the sidebar.";
        return;
    }

    if (!discordSettings.configured) {
        statusEl.textContent = "Auto-send skipped: save Discord bot token and channel ID first.";
        return;
    }

    await sendToDiscordRequest(data, btn, statusEl, true);
}

async function sendToDiscordRequest(data, btn, statusEl, automatic) {
    const applicantName = document.getElementById("applicant-name").value.trim();
    const applicantEmail = document.getElementById("applicant-email").value.trim();

    if (!applicantName || !applicantEmail) {
        statusEl.textContent = "Enter your name and email in the sidebar first.";
        return;
    }

    btn.disabled = true;
    statusEl.textContent = automatic ? "Auto-sending report to Discord..." : "Sending...";

    try {
        const resp = await fetch("/api/discord/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                applicant_name: applicantName,
                applicant_email: applicantEmail,
                data,
            }),
        });
        const payload = await resp.json();

        if (payload.sent) {
            statusEl.textContent = automatic
                ? "Sent to Discord automatically."
                : "Sent to Discord successfully.";
        } else if (payload.skipped_reason) {
            statusEl.textContent = payload.skipped_reason;
        } else {
            statusEl.textContent = "Failed to send: " + (payload.error || "unknown error");
        }
    } catch (err) {
        statusEl.textContent = "Network error while sending to Discord.";
    } finally {
        btn.disabled = false;
    }
}

async function loadDiscordSettings() {
    try {
        const resp = await fetch("/api/settings/discord");
        if (!resp.ok) {
            throw new Error("Could not load Discord settings.");
        }
        discordSettings = await resp.json();
        renderDiscordSettingsStatus();
    } catch (err) {
        discordSettings = {
            configured: false,
            source: "none",
            message: "Could not load Discord configuration status.",
        };
        renderDiscordSettingsStatus(true);
    }
}

async function saveDiscordSettings() {
    discordSaveBtn.disabled = true;
    discordConfigStatus.textContent = "Saving Discord configuration...";

    try {
        const resp = await fetch("/api/settings/discord", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                bot_token: discordBotTokenInput.value,
                channel_id: discordChannelIdInput.value,
            }),
        });

        const payload = await resp.json();
        if (!resp.ok) {
            discordConfigStatus.textContent = payload.detail || "Could not save Discord settings.";
            discordConfigStatus.dataset.state = "error";
            return;
        }

        discordSettings = payload;
        discordBotTokenInput.value = "";
        renderDiscordSettingsStatus();
    } catch (err) {
        discordConfigStatus.textContent = "Network error while saving Discord settings.";
        discordConfigStatus.dataset.state = "error";
    } finally {
        discordSaveBtn.disabled = false;
    }
}

function renderDiscordSettingsStatus(isError = false) {
    discordConfigStatus.textContent = discordSettings.message;
    if (isError) {
        discordConfigStatus.dataset.state = "error";
        return;
    }

    discordConfigStatus.dataset.state = discordSettings.configured ? "success" : "idle";
}
