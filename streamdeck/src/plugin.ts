import streamDeck from "@elgato/streamdeck";

import { MonitorAction, MuteAction, ProfileAction, StreamMuteAction, VolumeAction } from "./actions";
import { loadSettings } from "./faderdeck";

streamDeck.actions.registerAction(new MuteAction());
streamDeck.actions.registerAction(new VolumeAction());
streamDeck.actions.registerAction(new MonitorAction());
streamDeck.actions.registerAction(new StreamMuteAction());
streamDeck.actions.registerAction(new ProfileAction());

await streamDeck.connect();
await loadSettings();
