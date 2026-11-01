"use strict";

const $ = (selector) => document.querySelector(selector);
const notice = $("#notice");
let appState = { rooms: [], bells: [], tunes: [], volume: null, active_bell: null, player: { state: "idle", available: false } };
let roomFilter = "all";
let volumeTimer;
let noticeTimer;
let lastRoomState = "";
let refreshBusy = false;
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
    throw new Error("Your saved Soundroom access expired. Enter the PIN again.");
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
    for (const value of [bell.room, tuneLabel(bell.tune), `${bell.duration} sec`, bell.label || "—"]) {
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
      try {
        await api(`/api/bells/${bell.id}`, { method: "DELETE" });
        await refresh();
        showNotice("Scheduled room bell cancelled.");
      } catch (error) { showNotice(error.message, "error"); }
    });
    action.append(remove);
    row.append(action);
    body.append(row);
  }
}

async function ringRoom(room, duration) {
  if (appState.active_bell && appState.active_bell.room_id === room.id) {
    try {
      await api("/api/bells/stop", { method: "POST" });
      showNotice(`${room.name} bell stopped.`);
    } catch (error) { showNotice(error.message, "error"); }
  } else {
    try {
      await api(`/api/rooms/${room.id}/ring`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ duration }) });
      showNotice(`${room.name} bell ringing for ${duration} seconds.`);
    } catch (error) { showNotice(error.message, "error"); }
  }
  await refresh();
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

    const row = document.createElement("article");
    row.className = "room-console-row";
    if (appState.active_bell?.room_id === room.id) row.classList.add("is-ringing");
    const identity = document.createElement("div");
    identity.className = "room-console-identity";
    const name = document.createElement("strong");
    name.textContent = room.name;
    const sound = document.createElement("span");
    sound.className = "assigned-tune";
    sound.textContent = `${tuneLabel(room.default_tune)} · ${room.sound_description || "Custom room sound"}`;
    const nextBell = [...appState.bells]
      .filter((bell) => bell.room_id === room.id && new Date(bell.fire_at).getTime() > Date.now())
      .sort((a, b) => new Date(a.fire_at) - new Date(b.fire_at))[0];
    const next = document.createElement("small");
    next.textContent = nextBell ? `Next · ${new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" }).format(new Date(nextBell.fire_at))}` : "No bell scheduled";
    identity.append(name, sound, next);

    const controls = document.createElement("div");
    controls.className = "ring-controls";
    for (const duration of [5, 10]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ring-button";
      const ringingHere = appState.active_bell?.room_id === room.id;
      const stopDuration = [5, 10].includes(appState.active_bell?.duration) ? appState.active_bell.duration : 5;
      const isStop = ringingHere && duration === stopDuration;
      button.textContent = isStop ? "Stop bell" : `Ring · ${duration} sec`;
      button.setAttribute("aria-label", isStop ? `Stop ${room.name} bell` : `Ring ${room.name} bell for ${duration} seconds`);
      button.disabled = Boolean(appState.active_bell) && !isStop;
      if (isStop) button.classList.add("stop-button");
      button.addEventListener("click", () => ringRoom(room, duration));
      controls.append(button);
    }

    const settings = document.createElement("details");
    settings.className = "room-sound-settings";
    const summary = document.createElement("summary");
    summary.textContent = "Sound settings";
    const tuneSelect = document.createElement("select");
    tuneSelect.setAttribute("aria-label", `Default bell tune for ${room.name}`);
    const assignedElsewhere = new Map(appState.rooms.filter((other) => other.id !== room.id).map((other) => [other.default_tune, other.name]));
    for (const tune of appState.tunes) {
      const option = createOption(tuneLabel(tune), tune);
      if (assignedElsewhere.has(tune)) {
        option.disabled = true;
        option.textContent += ` · assigned to ${assignedElsewhere.get(tune)}`;
      }
      tuneSelect.append(option);
    }
    tuneSelect.value = roomTuneDrafts.get(room.id) || room.default_tune;
    tuneSelect.addEventListener("change", () => roomTuneDrafts.set(room.id, tuneSelect.value));
    const detailActions = document.createElement("div");
    detailActions.className = "room-sound-actions";
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "secondary-button";
    rename.textContent = "Save room name";
    rename.addEventListener("click", async () => {
      const input = settings.querySelector(".room-name-input");
      try {
        await api(`/api/rooms/${room.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: input.value }) });
        await refresh();
        showNotice(`Room renamed to ${input.value.trim()}.`);
      } catch (error) { showNotice(error.message, "error"); }
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-button danger-button";
    remove.textContent = "Remove room";
    remove.addEventListener("click", async () => {
      if (!window.confirm(`Remove ${room.name}? Its scheduled bells will also be cancelled.`)) return;
      try {
        await api(`/api/rooms/${room.id}`, { method: "DELETE" });
        roomTuneDrafts.delete(room.id);
        if (roomFilter === String(room.id)) roomFilter = "all";
        await refresh();
        showNotice(`${room.name} removed. Its scheduled bells were cancelled.`);
      } catch (error) { showNotice(error.message, "error"); }
    });
    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "quiet-button";
    preview.textContent = "Preview";
    preview.addEventListener("click", async () => {
      try {
        await api("/api/tunes/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tune: tuneSelect.value }) });
        showNotice(`Previewing ${tuneLabel(tuneSelect.value)} through the Windows output.`);
      } catch (error) { showNotice(error.message, "error"); }
    });
    const save = document.createElement("button");
    save.type = "button";
    save.className = "secondary-button";
    save.textContent = "Save sound";
    save.addEventListener("click", async () => {
      try {
        await api(`/api/rooms/${room.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ default_tune: tuneSelect.value }) });
        roomTuneDrafts.delete(room.id);
        await refresh();
        showNotice(`Room sound saved for ${room.name}.`);
      } catch (error) { showNotice(error.message, "error"); }
    });
    detailActions.append(preview, save, rename, remove);
    const nameLabel = document.createElement("label");
    nameLabel.className = "room-name-label";
    nameLabel.textContent = "Room name";
    const nameInput = document.createElement("input");
    nameInput.className = "room-name-input";
    nameInput.type = "text";
    nameInput.maxLength = 48;
    nameInput.value = room.name;
    nameInput.setAttribute("aria-label", `Room name for ${room.name}`);
    nameLabel.append(nameInput);
    settings.append(summary, nameLabel, tuneSelect, detailActions);

    row.append(identity, controls, settings);
    list.append(row);
  }
  if (appState.rooms.some((room) => String(room.id) === previous)) bellRoom.value = previous;
}

function renderStatus() {
  renderBells();
  const live = $("#bell-live");
  if (appState.active_bell) {
    live.textContent = `${appState.active_bell.room} bell is ringing. Press Stop bell to end it now.`;
    live.hidden = false;
  } else {
    live.hidden = true;
  }
  const slider = $("#system-volume");
  if (appState.volume !== null && document.activeElement !== slider) slider.value = appState.volume;
  $("#volume-value").textContent = appState.volume === null ? "Unavailable" : `${appState.volume}%`;
  $("#output-label").textContent = appState.output_name || "Windows output unavailable";
  $("#server-url").textContent = appState.server_url || "Unavailable";
  $("#server-url-label").textContent = appState.server_url || "Server address unavailable";
  const player = appState.player || { state: "idle" };
  const labels = { playing: "Playing on server", paused: "Paused on server", idle: "Ready" };
  $("#playback-state").textContent = player.available ? (labels[player.state] || "Ready") : "Chrome extension offline";
  $("#video-title").textContent = player.video_id ? player.title || `YouTube video ${player.video_id}` : player.available ? "No video selected" : "Waiting for signed-in Chrome";
  $("#server-player-note").textContent = !player.available ? "Open regular Chrome on the Windows server with the Soundroom extension enabled." : player.state === "playing" ? "Sound is coming from the Windows server's signed-in Chrome session." : player.state === "paused" ? "Video is paused in the server's Chrome session." : "Ready to play through the Windows default output.";
  $("#pause-video").textContent = player.state === "paused" ? "Resume video" : "Pause video";
  $("#pause-video").disabled = !player.video_id;
  $("#open-chrome").disabled = Boolean(player.available);
  $("#reset-player").disabled = !player.available;
}

async function refresh() {
  if (refreshBusy) return;
  refreshBusy = true;
  try {
    appState = await api("/api/status");
    const roomState = JSON.stringify([appState.rooms, appState.bells, appState.active_bell]);
    if (roomState !== lastRoomState) {
      renderRooms();
      lastRoomState = roomState;
    }
    renderStatus();
  } finally {
    refreshBusy = false;
  }
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

$("#youtube-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const videoId = parseVideoId($("#youtube-url").value.trim());
  if (!videoId || !/^[\w-]{11}$/.test(videoId)) {
    showNotice("Enter a valid YouTube video link.", "error");
    return;
  }
  const button = event.submitter;
  button.disabled = true;
  button.textContent = "Opening player…";
  try {
    const result = await api("/api/player/play", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_id: videoId }) });
    await refresh();
    showNotice(result.closed_tabs ? `Closed ${result.closed_tabs} YouTube tab${result.closed_tabs === 1 ? "" : "s"} in your signed-in Chrome session.` : "Playing on the server.");
  } catch (error) { showNotice(error.message, "error"); }
  finally { button.disabled = false; button.textContent = "Play on server"; }
});

$("#pause-video").addEventListener("click", async () => {
  try {
    const action = appState.player?.state === "paused" ? "resume" : "pause";
    await api(`/api/player/${action}`, { method: "POST" });
    await refresh();
  } catch (error) { showNotice(error.message, "error"); }
});

$("#open-chrome").addEventListener("click", async () => {
  try {
    await api("/api/player/open-chrome", { method: "POST" });
    showNotice("Chrome opened on the server. Make sure the Soundroom extension is enabled and YouTube is signed in there.");
  } catch (error) { showNotice(error.message, "error"); }
});

$("#reset-player").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Resetting player…";
  try {
    await api("/api/player/reset", { method: "POST" });
    await refresh();
    showNotice("Server player reset. Enter a YouTube link to start playback again.");
  } catch (error) { showNotice(error.message, "error"); }
  finally { button.disabled = false; button.textContent = "Reset server player"; }
});

$("#bluetooth-settings").addEventListener("click", async () => {
  try {
    await api("/api/bluetooth/settings", { method: "POST" });
    showNotice("Bluetooth Settings opened on the server. Operate it at the server PC or through Remote Desktop, then select the speaker as Windows output.");
  } catch (error) { showNotice(error.message, "error"); }
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
  $("#bell-time").value = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
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
    const result = await api("/api/bells", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room_id: $("#bell-room").value, fire_at: `${time}:00`, duration: $("#bell-duration").value, label: $("#bell-label").value }) });
    $("#bell-form").reset();
    $("#bell-form").hidden = true;
    await refresh();
    showNotice(result.wake_enabled === false ? "Bell scheduled, but Windows could not register its wake task. It may not ring if the PC sleeps." : "Room bell scheduled.", result.wake_enabled === false ? "error" : "info");
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

$("#pin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const pin = $("#new-pin").value;
  if (!/^\d{6}$/.test(pin)) {
    showNotice("Use exactly six digits for the access PIN.", "error");
    return;
  }
  try {
    await api("/api/settings/pin", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin }) });
    $("#pin-form").reset();
    showNotice("PIN changed. Sign in again with the new PIN.");
    setTimeout(() => window.location.assign("/login"), 1200);
  } catch (error) { showNotice(error.message, "error"); }
});

document.addEventListener("DOMContentLoaded", () => {
  refresh().catch((error) => showNotice(error.message, "error"));
  setInterval(() => refresh().catch(() => {}), 1800);
});
