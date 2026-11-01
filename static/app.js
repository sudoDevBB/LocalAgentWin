"use strict";

const $ = (selector) => document.querySelector(selector);
const notice = $("#notice");
let player = null;
let playerReady = false;
let appState = { rooms: [], bells: [], tunes: [], volume: null, active_bell: null };
let roomFilter = "all";
let volumeTimer;
let noticeTimer;
let lastRoomState = "";
const roomTuneDrafts = new Map();

function tuneLabel(filename) {
  return filename ? filename.replace(/\.wav$/i, "").replaceAll("_", " ") : "Unassigned";
}

function showNotice(message, kind = "info") {
  notice.textContent = message;
  notice.dataset.kind = kind;
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 6000);
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Your local session ended. Enter the PIN again.");
  }
  const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Soundroom could not complete that action.");
  return data;
}

function createOption(label, value) {
  const option = document.createElement("option");
  option.textContent = label;
  option.value = value;
  return option;
}

function localDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function renderBells() {
  const body = $("#bell-rows");
  body.replaceChildren();
  const bells = [...appState.bells]
    .filter((bell) => roomFilter === "all" || String(bell.room_id) === roomFilter)
    .sort((a, b) => new Date(a.fire_at) - new Date(b.fire_at));
  $("#bell-empty").hidden = bells.length !== 0;
  const nextId = bells.find((bell) => new Date(bell.fire_at).getTime() > Date.now())?.id;
  for (const bell of bells) {
    const row = document.createElement("tr");
    if (bell.id === nextId) row.className = "is-next-bell";
    const timeCell = document.createElement("td");
    timeCell.className = "bell-time-cell";
    const time = document.createElement("strong");
    time.textContent = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(bell.fire_at));
    const date = document.createElement("span");
    date.className = "bell-date";
    date.textContent = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" }).format(new Date(bell.fire_at));
    timeCell.append(time, date);
    row.append(timeCell);
    const values = [bell.room, tuneLabel(bell.tune), `${bell.duration} sec`, bell.label || "—"];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const action = document.createElement("td");
    const remove = document.createElement("button");
    remove.className = "text-button";
    remove.type = "button";
    remove.textContent = "Cancel";
    remove.setAttribute("aria-label", `Cancel bell for ${bell.room} at ${localDate(bell.fire_at)}`);
    remove.addEventListener("click", async () => {
      if (!window.confirm(`Cancel the ${localDate(bell.fire_at)} bell for ${bell.room}?`)) return;
      try {
        await api(`/api/bells/${bell.id}`, { method: "DELETE" });
        await refresh();
        showNotice("Room bell cancelled.");
      } catch (error) { showNotice(error.message, "error"); }
    });
    action.append(remove);
    row.append(action);
    body.append(row);
  }
}

function renderRooms() {
  const list = $("#room-list");
  list.replaceChildren();
  const bellRoom = $("#bell-room");
  const previous = bellRoom.value;
  bellRoom.replaceChildren(createOption("Choose a room", ""));
  const filter = $("#room-filter");
  filter.replaceChildren();
  const all = document.createElement("button");
  all.type = "button";
  all.textContent = "All rooms";
  all.className = roomFilter === "all" ? "room-chip is-selected" : "room-chip";
  all.addEventListener("click", () => { roomFilter = "all"; renderRooms(); renderBells(); });
  filter.append(all);
  for (const room of appState.rooms) {
    bellRoom.append(createOption(room.name, String(room.id)));
    const chip = document.createElement("button");
    chip.type = "button";
    chip.textContent = room.name;
    chip.className = roomFilter === String(room.id) ? "room-chip is-selected" : "room-chip";
    chip.addEventListener("click", () => { roomFilter = String(room.id); renderRooms(); renderBells(); });
    filter.append(chip);

    const row = document.createElement("div");
    row.className = "room-setting";
    const identity = document.createElement("div");
    identity.className = "room-identity";
    const nameBlock = document.createElement("div");
    nameBlock.className = "room-name-block";
    const name = document.createElement("strong");
    name.textContent = room.name;
    const assignedLabel = document.createElement("span");
    assignedLabel.className = "assigned-tune";
    assignedLabel.textContent = `${tuneLabel(room.default_tune)} · ${room.sound_description || "Custom tune"}`;
    nameBlock.append(name, assignedLabel);
    const signature = document.createElement("div");
    signature.className = "sound-signature";
    signature.setAttribute("role", "img");
    signature.setAttribute("aria-label", `Sound pattern for ${room.name}`);
    for (const height of (room.sound_pattern || [24, 24, 24, 24, 24, 24])) {
      const bar = document.createElement("span");
      bar.style.height = `${Math.max(12, Math.min(100, Number(height)))}%`;
      signature.append(bar);
    }
    identity.append(nameBlock, signature);
    const nextBell = [...appState.bells]
      .filter((bell) => bell.room_id === room.id && new Date(bell.fire_at).getTime() > Date.now())
      .sort((a, b) => new Date(a.fire_at) - new Date(b.fire_at))[0];
    const next = document.createElement("div");
    next.className = "room-next-bell";
    const nextLabel = document.createElement("span");
    nextLabel.textContent = "Next bell";
    const nextTime = document.createElement("strong");
    nextTime.textContent = nextBell ? new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(nextBell.fire_at)) : "Not scheduled";
    next.append(nextLabel, nextTime);
    const select = document.createElement("select");
    select.setAttribute("aria-label", `Default bell tune for ${room.name}`);
    const assignedElsewhere = new Map(appState.rooms.filter((other) => other.id !== room.id).map((other) => [other.default_tune, other.name]));
    for (const tune of appState.tunes) {
      const option = createOption(tuneLabel(tune), tune);
      if (assignedElsewhere.has(tune)) {
        option.disabled = true;
        option.textContent += ` · assigned to ${assignedElsewhere.get(tune)}`;
      }
      select.append(option);
    }
    select.value = roomTuneDrafts.get(room.id) || room.default_tune;
    select.addEventListener("change", () => roomTuneDrafts.set(room.id, select.value));
    const preview = document.createElement("button");
    preview.type = "button";
    preview.textContent = "Preview sound";
    preview.className = "quiet-button";
    preview.addEventListener("click", async () => {
      const tune = select.value;
      try {
        await api("/api/tunes/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tune }) });
        showNotice(`Playing the ${tuneLabel(tune)} sound through the Windows speaker.`);
      } catch (error) { showNotice(error.message, "error"); }
    });
    const save = document.createElement("button");
    save.type = "button";
    save.textContent = "Save tune";
    save.className = "secondary-button";
    save.addEventListener("click", async () => {
      try {
        await api(`/api/rooms/${room.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ default_tune: select.value }) });
        roomTuneDrafts.delete(room.id);
        await refresh();
        showNotice(`Default tune saved for ${room.name}.`);
      } catch (error) { showNotice(error.message, "error"); }
    });
    const tuneControl = document.createElement("label");
    tuneControl.className = "room-tune-control";
    const tuneLabelText = document.createElement("span");
    tuneLabelText.textContent = "Change sound";
    tuneControl.append(tuneLabelText, select);
    const actions = document.createElement("div");
    actions.className = "room-actions";
    actions.append(preview, save);
    row.append(identity, next, tuneControl, actions);
    list.append(row);
  }
  if (appState.rooms.some((room) => String(room.id) === previous)) bellRoom.value = previous;
}

function renderStatus() {
  renderBells();
  const live = $("#bell-live");
  if (appState.active_bell) {
    live.textContent = `${appState.active_bell.room} bell is playing. Music will return when it finishes.`;
    live.hidden = false;
  } else {
    live.hidden = true;
  }
  const slider = $("#system-volume");
  if (appState.volume !== null && document.activeElement !== slider) slider.value = appState.volume;
  $("#volume-value").textContent = appState.volume === null ? "Unavailable" : `${appState.volume}%`;
}

async function refresh() {
  appState = await api("/api/status");
  const roomState = JSON.stringify([appState.rooms, appState.bells]);
  if (roomState !== lastRoomState) {
    renderRooms();
    lastRoomState = roomState;
  }
  renderStatus();
  $("#output-label").textContent = appState.output_name || "Windows default output";
}

function parseVideoId(input) {
  try {
    const url = new URL(input);
    const host = url.hostname.toLowerCase().replace(/^www\./, "");
    if (host === "youtu.be") return url.pathname.split("/").filter(Boolean)[0] || null;
    if (host !== "youtube.com" && host !== "m.youtube.com" && host !== "music.youtube.com") return null;
    if (url.pathname === "/watch") return url.searchParams.get("v");
    const parts = url.pathname.split("/").filter(Boolean);
    if (["embed", "shorts", "live"].includes(parts[0])) return parts[1] || null;
  } catch (_) { return null; }
  return null;
}

window.onYouTubeIframeAPIReady = function () {
  player = new YT.Player("youtube-player", {
    width: "100%",
    height: "100%",
    playerVars: { playsinline: 1, rel: 0 },
    events: {
      onReady() { playerReady = true; },
      onStateChange(event) {
        const states = { [-1]: "Ready", 0: "Finished", 1: "Playing", 2: "Paused", 3: "Buffering", 5: "Ready" };
        $("#playback-state").textContent = states[event.data] || "Ready";
        $("#pause-video").disabled = event.data !== YT.PlayerState.PLAYING;
      },
      onError() { showNotice("YouTube could not play this video. Check the link and try another video.", "error"); }
    }
  });
};

$("#youtube-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const videoId = parseVideoId($("#youtube-url").value.trim());
  if (!videoId || !/^[\w-]{11}$/.test(videoId)) {
    showNotice("Enter a valid YouTube video link.", "error");
    return;
  }
  if (!playerReady) {
    showNotice("The YouTube player is still loading. Try again in a moment.");
    return;
  }
  player.loadVideoById(videoId);
  $("#video-empty").hidden = true;
  $("#video-title").textContent = `YouTube video · ${videoId}`;
  $("#pause-video").disabled = false;
});

$("#pause-video").addEventListener("click", () => {
  if (playerReady) player.pauseVideo();
});

$("#system-volume").addEventListener("input", (event) => {
  $("#volume-value").textContent = `${event.target.value}%`;
  clearTimeout(volumeTimer);
  volumeTimer = setTimeout(async () => {
    try {
      const result = await api("/api/volume", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ volume: event.target.value }) });
      appState.volume = result.volume;
    } catch (error) { showNotice(error.message, "error"); }
  }, 120);
});

function openBellForm() {
  $("#bell-form").hidden = false;
  $("#bell-form").scrollIntoView({ behavior: "smooth", block: "center" });
  const now = new Date();
  now.setMinutes(Math.ceil((now.getMinutes() + 1) / 5) * 5, 0, 0);
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  $("#bell-time").value = local;
  $("#bell-room").focus();
}
document.querySelectorAll("[data-open-bell-form]").forEach((button) => button.addEventListener("click", openBellForm));

$("#cancel-bell").addEventListener("click", () => { $("#bell-form").hidden = true; });
$("#bell-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const time = $("#bell-time").value;
  if (!time || new Date(time).getTime() <= Date.now()) {
    showNotice("Choose a future date and time.", "error");
    return;
  }
  try {
    await api("/api/bells", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room_id: $("#bell-room").value, fire_at: `${time}:00`, duration: $("#bell-duration").value, label: $("#bell-label").value }) });
    $("#bell-form").reset();
    $("#bell-form").hidden = true;
    await refresh();
    showNotice("Room bell scheduled.");
  } catch (error) { showNotice(error.message, "error"); }
});

$("#new-room-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/rooms", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: $("#new-room-name").value }) });
    $("#new-room-form").reset();
    await refresh();
    showNotice("Room added.");
  } catch (error) { showNotice(error.message, "error"); }
});

$("#tune-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("#tune-file").files[0];
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) {
    showNotice("Choose a WAV file smaller than 20 MB.", "error");
    return;
  }
  const form = new FormData();
  form.append("tune", file);
  try {
    await api("/api/tunes", { method: "POST", body: form });
    $("#tune-form").reset();
    await refresh();
    showNotice("Bell tune added.");
  } catch (error) { showNotice(error.message, "error"); }
});

document.addEventListener("DOMContentLoaded", () => {
  refresh().catch((error) => showNotice(error.message, "error"));
  setInterval(() => refresh().catch(() => {}), 10000);
});
