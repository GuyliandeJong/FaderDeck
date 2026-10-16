// Talks to FaderDeck's local remote control on this PC (Settings, Remote
// control in FaderDeck). The port and token are the plugin's global settings.
import streamDeck from "@elgato/streamdeck";
import type { JsonObject } from "@elgato/utils";

export type GlobalSettings = { port?: string; token?: string } & JsonObject;

// What FaderDeck's /api/state answers; only the parts the keys show.
export type FaderDeckState = {
	connected: boolean;
	monitor: boolean;
	stream_mute: boolean | null;
	channels: Record<string, { gain: number; mute: boolean }>;
};

export const CHANNELS: Record<string, string> = { mic: "Mic", game: "Game", chat: "Chat", media: "Media" };

let settings: GlobalSettings = {};

export async function loadSettings(): Promise<void> {
	settings = await streamDeck.settings.getGlobalSettings<GlobalSettings>();
}

streamDeck.settings.onDidReceiveGlobalSettings<GlobalSettings>((ev) => {
	settings = ev.settings;
	void poll();
});

export async function api(method: "GET" | "POST", path: string): Promise<any> {
	const port = Number(settings.port) || 8765;
	const response = await fetch(`http://127.0.0.1:${port}/api/${path}`, {
		method,
		headers: { "X-FaderDeck-Token": settings.token ?? "" },
		signal: AbortSignal.timeout(3000),
	});
	const body = (await response.json().catch(() => ({}))) as { error?: string };
	if (!response.ok) {
		throw new Error(body.error ?? `FaderDeck answered ${response.status}`);
	}
	return body;
}

// One poll for every visible key, so a mute made on the PC or by a hotkey
// shows on the deck too.
type Listener = (state: FaderDeckState | null) => void;
const listeners = new Set<Listener>();
let timer: ReturnType<typeof setInterval> | undefined;

export function watch(listener: Listener): void {
	listeners.add(listener);
	if (!timer) {
		timer = setInterval(poll, 1000);
	}
	void poll();
}

export async function poll(): Promise<void> {
	let state: FaderDeckState | null = null;
	try {
		state = await api("GET", "state");
	} catch {
		state = null; // FaderDeck is closed, or the remote control is off
	}
	for (const listener of listeners) {
		listener(state);
	}
}
