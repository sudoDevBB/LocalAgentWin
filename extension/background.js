const SERVER = "http://127.0.0.1:8765";
const SOCKET = "ws://127.0.0.1:8765/internal/chrome-extension";
let socket = null;
let retryTimer = null;
let heartbeatTimer = null;
let statusTimer = null;
let playerTabId = null;
let commandBusy = false;

function isYouTube(url = "") {
  try {
    const host = new URL(url).hostname.toLowerCase().replace(/^www\./, "");
    return host === "youtube.com" || host === "m.youtube.com" || host === "music.youtube.com" || host === "youtu.be";
  } catch (_) { return false; }
}

function videoIdFromUrl(url = "") {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    if (host === "youtu.be") return parsed.pathname.split("/").filter(Boolean)[0] || null;
    if (["youtube.com", "m.youtube.com", "music.youtube.com"].includes(host)) {
      if (parsed.pathname === "/watch") return parsed.searchParams.get("v");
      const parts = parsed.pathname.split("/").filter(Boolean);
      if (["embed", "shorts", "live"].includes(parts[0])) return parts[1] || null;
    }
  } catch (_) { /* ignore non-URLs */ }
  return null;
}

async function waitForTab(tabId) {
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(new Error("Chrome took too long to load YouTube."));
    }, 45000);
    function onUpdated(updatedId, info) {
      if (updatedId === tabId && info.status === "complete") {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(onUpdated);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.get(tabId).then((tab) => {
      if (tab.status === "complete") {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(onUpdated);
        resolve();
      }
    }).catch((error) => {
      clearTimeout(timeout);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(error);
    });
  });
}

async function inspectPlayer(tabId) {
  const tab = await chrome.tabs.get(tabId);
  if (!isYouTube(tab.url)) return { state: "idle", video_id: null, title: "No video selected" };
  const injected = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const video = document.querySelector("video");
      return {
        state: video ? (video.paused ? "paused" : "playing") : "loading",
        title: document.title.replace(/ - YouTube$/, ""),
      };
    },
  });
  return {
    ...injected[0].result,
    video_id: videoIdFromUrl(tab.url),
    tab_id: tabId,
  };
}

async function reportStatus() {
  if (commandBusy || !socket || socket.readyState !== WebSocket.OPEN) return;
  try {
    const stored = await chrome.storage.local.get("soundroomPlayerTabId");
    playerTabId = stored.soundroomPlayerTabId || null;
    let player = { state: "idle", video_id: null, title: "No video selected" };
    if (playerTabId !== null) {
      try { player = await inspectPlayer(playerTabId); }
      catch (_) {
        playerTabId = null;
        await chrome.storage.local.remove("soundroomPlayerTabId");
      }
    }
    socket.send(JSON.stringify({ type: "status", player }));
  } catch (_) { /* Chrome may be shutting down this worker */ }
}

async function runCommand(message) {
  if (commandBusy) throw new Error("Chrome is already handling a Soundroom request.");
  commandBusy = true;
  try {
    if (message.command === "play") {
      const tabs = await chrome.tabs.query({});
      const youtubeTabs = tabs.filter((tab) => isYouTube(tab.url));
      const closedTabs = youtubeTabs.length;
      if (youtubeTabs.length) await chrome.tabs.remove(youtubeTabs.map((tab) => tab.id));
      const tab = await chrome.tabs.create({
        url: `https://www.youtube.com/watch?v=${encodeURIComponent(message.value)}&autoplay=1`,
        active: true,
      });
      playerTabId = tab.id;
      await chrome.storage.local.set({ soundroomPlayerTabId: playerTabId });
      await waitForTab(playerTabId);
      await new Promise((resolve) => setTimeout(resolve, 1200));
      const injected = await chrome.scripting.executeScript({
        target: { tabId: playerTabId },
        func: async () => {
          const deadline = Date.now() + 25000;
          let video = document.querySelector("video");
          while (!video && Date.now() < deadline) {
            await new Promise((resolve) => setTimeout(resolve, 300));
            video = document.querySelector("video");
          }
          if (!video) throw new Error("YouTube did not create a video player.");
          try { await video.play(); } catch (_) { /* YouTube may already have started it. */ }
          return { state: video.paused ? "paused" : "playing", title: document.title.replace(/ - YouTube$/, "") };
        },
      });
      const player = { ...injected[0].result, video_id: message.value, tab_id: playerTabId };
      if (player.state !== "playing") throw new Error("YouTube loaded but playback did not start. Check Chrome's YouTube tab for a prompt.");
      return { ...player, closed_tabs: closedTabs };
    }

    if (message.command === "pause" || message.command === "resume") {
      if (playerTabId === null) throw new Error("There is no Soundroom video tab in Chrome.");
      const injected = await chrome.scripting.executeScript({
        target: { tabId: playerTabId },
        args: [message.command],
        func: async (command) => {
          const video = document.querySelector("video");
          if (!video) throw new Error("YouTube's video player is not available.");
          if (command === "pause") video.pause();
          else await video.play();
          return { state: video.paused ? "paused" : "playing", title: document.title.replace(/ - YouTube$/, "") };
        },
      });
      return { ...injected[0].result, video_id: videoIdFromUrl((await chrome.tabs.get(playerTabId)).url), tab_id: playerTabId };
    }

    if (message.command === "reset") {
      if (playerTabId !== null) {
        try { await chrome.tabs.remove(playerTabId); } catch (_) { /* already closed */ }
      }
      playerTabId = null;
      await chrome.storage.local.remove("soundroomPlayerTabId");
      return { state: "idle", video_id: null, title: "No video selected" };
    }
    throw new Error("Unknown Soundroom Chrome command.");
  } finally {
    commandBusy = false;
  }
}

function sendKeepalive() {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "keepalive" }));
}

function connect() {
  if (socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(socket.readyState)) return;
  clearTimeout(retryTimer);
  socket = new WebSocket(SOCKET);
  socket.onopen = () => {
    sendKeepalive();
    clearInterval(heartbeatTimer);
    clearInterval(statusTimer);
    heartbeatTimer = setInterval(sendKeepalive, 20000);
    statusTimer = setInterval(reportStatus, 2500);
    reportStatus();
  };
  socket.onmessage = async (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch (_) { return; }
    if (message.type !== "command") return;
    try {
      const result = await runCommand(message);
      socket?.send(JSON.stringify({ type: "result", id: message.id, ok: true, result }));
      await reportStatus();
    } catch (error) {
      socket?.send(JSON.stringify({ type: "result", id: message.id, ok: false, error: error.message || "Chrome could not complete the request." }));
      await reportStatus();
    }
  };
  socket.onclose = () => {
    socket = null;
    clearInterval(heartbeatTimer);
    clearInterval(statusTimer);
    retryTimer = setTimeout(connect, 2500);
  };
  socket.onerror = () => socket?.close();
}

chrome.alarms.create("soundroom-reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "soundroom-reconnect" && (!socket || socket.readyState === WebSocket.CLOSED)) connect();
});
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === playerTabId) {
    playerTabId = null;
    chrome.storage.local.remove("soundroomPlayerTabId");
    reportStatus();
  }
});
connect();
