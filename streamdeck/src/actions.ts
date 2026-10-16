import type { JsonObject } from "@elgato/utils";
import {
	action,
	DialDownEvent,
	DialRotateEvent,
	KeyAction,
	KeyDownEvent,
	SingletonAction,
	WillAppearEvent,
} from "@elgato/streamdeck";

import { api, CHANNELS, FaderDeckState, poll, watch } from "./faderdeck";

type ChannelSettings = { channel?: string } & JsonObject;
type VolumeSettings = { channel?: string; step?: string } & JsonObject;
type ProfileSettings = { profile?: string; direction?: string } & JsonObject;

function channelOf(settings: ChannelSettings): string {
	return settings.channel && CHANNELS[settings.channel] ? settings.channel : "mic";
}

// A press that FaderDeck refused shows Stream Deck's warning triangle.
async function send(ev: { action: { showAlert(): Promise<void> } }, path: string): Promise<void> {
	try {
		await api("POST", path);
		await poll();
	} catch {
		await ev.action.showAlert();
	}
}

/** A key that shows an on/off state read from FaderDeck. */
abstract class StateKey<T extends JsonObject> extends SingletonAction<T> {
	private watching = false;

	protected abstract isOn(state: FaderDeckState, settings: T): boolean;

	override onWillAppear(_ev: WillAppearEvent<T>): void {
		if (!this.watching) {
			this.watching = true;
			watch((state) => void this.show(state));
		}
	}

	private async show(state: FaderDeckState | null): Promise<void> {
		for (const visible of this.actions) {
			if (!visible.isKey()) {
				continue;
			}
			const settings = (await visible.getSettings()) as T;
			await (visible as KeyAction<T>).setState(state && this.isOn(state, settings) ? 1 : 0);
		}
	}
}

@action({ UUID: "com.faderdeck.streamdeck.mute" })
export class MuteAction extends StateKey<ChannelSettings> {
	protected isOn(state: FaderDeckState, settings: ChannelSettings): boolean {
		return !!state.channels?.[CHANNELS[channelOf(settings)]]?.mute;
	}

	override async onKeyDown(ev: KeyDownEvent<ChannelSettings>): Promise<void> {
		await send(ev, `mute/${channelOf(ev.payload.settings)}?state=toggle`);
	}
}

@action({ UUID: "com.faderdeck.streamdeck.monitor" })
export class MonitorAction extends StateKey<JsonObject> {
	protected isOn(state: FaderDeckState): boolean {
		return !!state.monitor;
	}

	override async onKeyDown(ev: KeyDownEvent<JsonObject>): Promise<void> {
		await send(ev, "monitor?state=toggle");
	}
}

@action({ UUID: "com.faderdeck.streamdeck.streammute" })
export class StreamMuteAction extends StateKey<JsonObject> {
	protected isOn(state: FaderDeckState): boolean {
		return !!state.stream_mute;
	}

	override async onKeyDown(ev: KeyDownEvent<JsonObject>): Promise<void> {
		await send(ev, "stream-mute?state=toggle");
	}
}

@action({ UUID: "com.faderdeck.streamdeck.volume" })
export class VolumeAction extends SingletonAction<VolumeSettings> {
	private watching = false;

	override onWillAppear(_ev: WillAppearEvent<VolumeSettings>): void {
		if (!this.watching) {
			this.watching = true;
			watch((state) => void this.show(state));
		}
	}

	// A dial shows the channel and its volume on the Stream Deck+ display.
	private async show(state: FaderDeckState | null): Promise<void> {
		for (const visible of this.actions) {
			if (!visible.isDial()) {
				continue;
			}
			const settings = await visible.getSettings();
			const name = CHANNELS[channelOf(settings)];
			const channel = state?.channels?.[name];
			await visible.setFeedback({
				title: name,
				value: channel ? (channel.mute ? "Muted" : `${channel.gain.toFixed(1)} dB`) : "Offline",
				indicator: { value: channel ? Math.round(((channel.gain + 60) / 72) * 100) : 0 },
			});
		}
	}

	private step(settings: VolumeSettings): number {
		const step = Number(settings.step);
		return Number.isFinite(step) && step !== 0 ? step : 1;
	}

	override async onKeyDown(ev: KeyDownEvent<VolumeSettings>): Promise<void> {
		const settings = ev.payload.settings;
		await send(ev, `gain/${channelOf(settings)}?step=${this.step(settings)}`);
	}

	override async onDialRotate(ev: DialRotateEvent<VolumeSettings>): Promise<void> {
		const step = Math.abs(this.step(ev.payload.settings)) * ev.payload.ticks;
		await send(ev, `gain/${channelOf(ev.payload.settings)}?step=${step}`);
	}

	override async onDialDown(ev: DialDownEvent<VolumeSettings>): Promise<void> {
		await send(ev, `mute/${channelOf(ev.payload.settings)}?state=toggle`);
	}
}

@action({ UUID: "com.faderdeck.streamdeck.profile" })
export class ProfileAction extends SingletonAction<ProfileSettings> {
	override async onKeyDown(ev: KeyDownEvent<ProfileSettings>): Promise<void> {
		const { profile, direction } = ev.payload.settings;
		const path = profile?.trim()
			? `profile/${encodeURIComponent(profile.trim())}`
			: `profile?step=${direction === "previous" ? "previous" : "next"}`;
		await send(ev, path);
	}
}
