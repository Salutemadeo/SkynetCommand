# Skynet Command

**Made by Salutem** · Steam: https://steamcommunity.com/id/hecton/ · Discord: hekton

> ⚠ **THIS APP IS FREE. IT CANNOT BE SOLD.** You may share it for free; selling it, or putting it behind a paywall, is not allowed. If you paid for it, you were scammed.
>
> License: **PolyForm Noncommercial 1.0.0** - see `LICENSE.txt`. Free to use, share and change for noncommercial purposes; keep the license and its Required Notice lines when you share it.

Voice macros for games, like VoiceAttack, but it uses the **Whisper** speech AI instead of Windows speech recognition. You say a phrase ("hellbomb", "five hundred kg") and it presses the keys in the game for you. Everything runs locally on your PC.

Folder on the PC: `Documents\Skynet Command\`

## Files

| File | What it is |
|---|---|
| `skynet_command.py` | The whole app (Python + Tkinter) |
| `Skynet Command.bat` | Starts the app. It uses its own `venv` if there is one, otherwise Skynet Alpha's (`..\Claude Captions\venv`), so no extra install is needed |
| `Install GPU boost.bat` | NVIDIA only: CUDA libraries for the speech engine (also started from ⚙ OPTIONS → GPU BOOST) |
| `Setup (run once).bat` | Only needed without Skynet Alpha: Python 3.12 venv + faster-whisper, PyAudioWPatch, numpy |
| `LICENSE.txt` | PolyForm Noncommercial 1.0.0 + Required Notice (Salutem): free, no selling |
| `skynet_command.ico` / `skynet_command_logo.png` | Hex-core logo (16-256 px icon, each size drawn natively; 1024 px PNG) - made by `make_icon.py` (Pillow, run in the sandbox) |
| `profiles\*.json` | One profile per game (created on first start: Helldivers 2, Windows example) |
| `settings.json`, `sfx\`, `logs\app-errors.txt` | Created at runtime |

## How it works

- **Mic → voice detector → Whisper → fuzzy match → keys.** The voice detector cuts out each phrase (it ends after ~380 ms of silence). Whisper gets the profile's command words as a hint. The matcher forgives mishearing ("hello bomb" → Hellbomb, "600 kg" → 500kg bomb) and extra words ("uh, airstrike please").
- **Borderless window** with its own title bar (drag the header, double-click = maximize, grip bottom-right = resize). Dialogs are borderless too.
- **Recording device** picker right in the main window (and in ⚙ OPTIONS); the header bar shows the mic level.
- **Key capture boxes**: in ⚙ OPTIONS / ✎ PROFILE click a key box and press the key (or combo / mouse button) - it fills itself in. Esc = cancel, ✖ = clear.
- **Lock / unlock listening** key (⚙ OPTIONS, default ctrl+alt+m) works anywhere, also in game; button in the main window too.
- **One macro speed** for every macro: ⚙ OPTIONS → MACRO SPEED, 10-200 ms per key (half held, half gap). 60 = safe, 15 = very fast.
- **Helldivers 2 profile (v3)**: 114 stratagems, every code read from its own helldivers.wiki.gg page (Oct 2026) and cross-checked by script; AMW-20 Apex and LAS-44 Nova are added switched off (no code on the wiki yet). Of the wiki category's 128 pages, the rest are not stratagems (templates, disambiguation, April Fools, mission pages, removed Illumination Flare) on the **arrow keys** (Ctrl held). Old v1 profiles are upgraded automatically (own extra commands are kept).
- Keys are sent as **hardware scan codes** (SendInput), so DirectInput games pick them up. The timer runs at 1 ms resolution for exact timings. Every key a macro held is released at the end, even when it's aborted.
- **Game focus guard:** commands only fire while the profile's game .exe is in front (can be turned off).
- **Auto-switch:** opening a game selects its profile.
- **Listen modes:** always-on voice detection, or push-to-talk (mouse4/mouse5/any key). A global hotkey pauses/resumes listening (default `ctrl+alt+m`).
- Whisper model: `auto` = large-v3-turbo on an NVIDIA GPU (uses Skynet Alpha's GPU boost libraries), base.en on CPU.
- **Import** VoiceAttack `.vap` profiles (XML export), including `[a;b]` phrase syntax and key press/down/up/pause/say actions.
- Spoken replies (`say ...`) use the Windows en-US voice through one persistent PowerShell process. The mic is muted while the app speaks or beeps.

## v33: stratagem icons
- Every Helldivers 2 command now shows its stratagem icon next to its name, and a big version on the hover card. They show in both the English and German profile, and in any command of your own that calls the same stratagem.
- The icons are taken from the "BIT BETTER UI" mod by SquidARMY7 (Nexus Mods 12146), Normal Guided Eagle option. They are coloured like in the game: orbital and eagle red, weapons, backpacks and vehicles blue, sentries, emplacements and mines green, mission yellow.
- They live in `icons/hd2/<arrow code>_26.png` and `_56.png` on this PC only, and are NOT part of the shared package or GitHub, because the mod's art is not ours to share. Without that folder the app just shows no icons.
- 106 of 116 commands have an icon. The mod has no icon for SSSD Delivery, Aquifer Drill, Tactical Video Camera, E-711 Extraction Drill, Portable Comms Relay, Bullet Storm, Directional Shield, Breakthrough Exosuit, Apex or Nova.

## v32: speaker commands tested live
- Tested on the real PC: a German voice clip played through the speakers (no microphone) was recognised. It matched SOS-Bake, Verstärkung, A/AC-8 Maschinenkanonengeschütz, Orbitales Napalm-Sperrfeuer and LIFT-182 Warp-Paket. Commands only FIRE while Helldivers 2 is in front, because ONLY WHEN GAME IS IN FRONT is on.
- Your own voice is now always recognised first. From the speakers, only the newest short phrase (3.5 s or less) goes to the speech AI. Long talk, videos and game dialogue no longer pile up in front of a real command and make it arrive too late, and the GPU has less to do.
- Speaker phrases are recognised in your command language, as German friends would expect. English stratagem names still match as before.

## v31: friends' commands actually fire
- Friends coming through the speakers can now speak either language. In German mode, "Orbital Laser", "Reinforce" or "Eagle 500kg bomb" fire your German commands, and German words work in English mode too. Whisper works out which language they speak, and the stratagem is found by its arrow code. Your own profiles stay separate.
- Friends' commands may arrive up to 3 s late before they are dropped, even if your MAX AGE is shorter. Speech coming through the speakers takes a little longer to reach the app.
- When nothing matches, the log shows a grey `◂ speakers: "…" → no match (closest …)` line, so you can see what was heard.
- Fixed: the double-trigger and game-call-out guards now run before the command fires, not after. The call-out guard only skips repeats of commands YOU said, not your friends' commands.

## v30: every sound source
- **★ ALL SOUND SOURCES** is a new entry at the top of RECORDING DEVICE, and it is now the default. It listens to every microphone and every output (speakers or headphones) at once, so commands work from your mic, from friends on Discord, or from anything else your PC plays.
- Push-to-talk still applies to your microphones. Outputs are always listened to, but only voice-like sound reaches the speech AI.
- If the same command is heard by two devices within 2 s, it fires only once.
- A device that is busy or can't be opened is skipped quietly.
- Fixed: error spam in `app-errors.txt` from the taskbar icon (`_ICON_HANDLES`).

## v29: speakers in the recording device list
- **RECORDING DEVICE** (Options and the main window) now lists your outputs too:
  - **SPEAKERS ▸ ...** listens to what your PC plays, so friends in Discord or game voice chat can say commands.
  - **MIC + SPEAKERS ▸ ...** listens to you and your friends.
- The speaker listener is always on, even in push-to-talk mode, because friends can't press your key. LOCK still stops it.
- It ignores the app's own sounds and voice while they play.
- Only voice-like sound is sent to the speech AI. Gunfire, explosions and static are dropped first, so they use no GPU.
- When friends are just chatting, there is no log spam, no fail buzz and your combo isn't lost. A command they fire is marked `· via speakers` in the log.
- If the speakers repeat a command you used in the last 12 s, it is ignored. This stops the game's own call-outs, like "Reinforcing!", from firing it again.

## v28: the eye is the logo
- The Skynet eye at the top left now looks like the app icon: a hex core behind 6 armoured lids.
- The lids work like a camera aperture. They slide in with a twist to shut, slide out to open, and blink now and then. The core still follows your mouse.
- New metal sounds when the eye opens or closes, one set per theme:
  - Skynet: servo whine, 6 clanks and a heavy lock
  - Nano: light servo, bright pings and an air release
  - Blackwatch: hydraulic hiss, steel bolts and an armoured slam

## v27: icon refresh
- Shortcuts kept showing the old red-eye icon because Windows caches icons by file name. The hex-core icon is now also saved as `skynet_command_v5.ico`, and every shortcut that starts Skynet Command gets the new icon: the app folder, Desktop, Start menu and pinned taskbar. Then Windows' icon cache is refreshed.

## v26: exact in-game German stratagem names
- The German profile now uses the real names from the German version of the game, e.g. **Adler – Luftschlag**, **Orbital-Präzisionsschlag**, **EAT-17-Einmal-Panzerabwehr**, **ARC-3-Bogenwerfer**, **M-102-Schnelles Aufklärungsfahrzeug**.
- The exact name is the command's name and its first phrase. All the old German phrases and names still work too.
- Your existing German profile is upgraded automatically. Your own phrases, changed macros and on/off settings are kept, and your usage counts follow the new names.
- 91 stratagems have their exact name. 25 had no German source (mission objectives, Eagle Rearm, Orbital Napalm, Eagle Gas, Meltagun, Grenadier Battlement, Gas Mines, the Supply and Incinerator FRV, Maelstrom, Bastion), so they keep their previous German names. Rename them in the app if your game shows something else.

## v25: separate English and German Helldivers 2 profiles
- The German profile is now called **Helldivers 2 (Deutsch)** (`profiles_de/Helldivers 2 _Deutsch_.json`); the English one stays **Helldivers 2** in `profiles/`.
- Each one has its own usage counters (x5 / x10). Your old German counts were moved over automatically and your taught phrases were kept.
- Each language remembers its own last-used profile (`profile` / `profile_de` in settings.json).
- Your overall total and rank are still shared, because they belong to you, not to a profile.

## v24: hear how to say a command
- Every row has a small **speaker** (right end of WHEN I SAY): click it and the command is read aloud in a clear, natural voice (no robot effect) - its name, then the phrases you can say. Also the **♪ HEAR** button for the selected command.
- OPTIONS → SOUND → **PRONUNCIATION SPEED**: slow (default, for learning) / normal. Works even when the Skynet voice is off.
- In German it uses a German Windows voice. If none is installed the log says how to add one (Windows Settings → Time & language → Speech → Manage voices → Add voices → Deutsch).

## v23: full German interface
- COMMAND LANGUAGE **deutsch** now switches the whole interface to German too: every label, button tooltip, option and hint, the command editor, profile window, combo / rank panel (KOMBO, GESAMT, BESTE, ST, EP, German rank names), header status (WARTET, IM SPIEL, GESPERRT …), key names (STRG LINKS, UMSCHALT, LEERTASTE …), pop-up questions and every log message. English mode is unchanged.
- One translation table (`DE` + `DE_RULES` for messages with names / numbers) and `tr()`; in German mode every label, canvas text, tooltip, title and message box goes through it.
- Fixed: the app did not start after v21 (the combo panel's code had been split by the rank side tab).

## v22: Deutsch (German commands)
- OPTIONS → LOOK → **COMMAND LANGUAGE**: english / deutsch (restarts by itself, like the themes).
- **Deutsch** uses its own profile folder `profiles_de` - a German Helldivers 2 profile (German names + phrases for all 116 stratagems, e.g. "Höllenbombe", "Orbitaler Laser", "Adler-500-kg-Bombe", "Nachschub", plus the code names like "TD-220"). Your English profiles in `profiles` are never touched or mixed in.
- Whisper listens in German (multilingual model: large-v3-turbo on the GPU, small on the CPU), German filler words ("bitte", "äh", "jetzt" …) are ignored, Whisper's typical German silence phantoms ("Untertitel im Auftrag des ZDF", "Danke") are filtered.
- The voice speaks German if Windows has a German voice installed ("Zuhören aktiv." · Blackwatch: "Verstanden. Höllenbombe." / "Funk online. Bereit.").
- Fixed: the Windows speech script for the robot / suit / radio voice had been removed by mistake in v14 - spoken confirmations work again.

## v21: Blackwatch theme
- OPTIONS → LOOK → THEME: **BLACKWATCH** - black + military yellow, blue goggle-lens eye, faint tactical grid background (a target box moves between frames).
- Radio-comms sounds: squelch clicks, static bursts, roger beeps, key-up / squelch-tail push-to-talk (sounds b1_).
- **RADIO VOICE**: lines go through a field-radio filter (narrow band, compressed, static, squelch at start and end) and are radio-style: "Copy. Hellbomb." · "Comms online. Standing by." · "Comms offline."
- Ranks in this theme follow the Blackwatch chain of command: RECRUIT → FOOT SOLDIER → SPECTRE → SPECTRE SGT → FIELD OFFICER → LIEUTENANT → COMMANDER → COLONEL → ORION SOLDIER → GENERAL (each I-V, 50 total). Your XP is shared between themes.

## v20: combo counter, use counters, 50 ranks
- Every command row shows how often you used it: an **xN** badge on the left (flashes when it fires; brighter from x10, glowing from x50).
- Panel above the COMMAND LOG: **COMBO xN** (successful commands in a row - a miss, a "game not in front" or 2 minutes without a command breaks it; the bar under it drains), **TOTAL** successful commands, **BEST** combo, and your **rank**.
- **50 ranks** (RECRUIT I → OVERLORD V), 1 XP per successful command: 4 XP for level 2 … about 2,000 for level 50. Rank-ups and every x5 combo flash a banner with a sound.
- Kept in `stats.json` (counts per profile + command). Test presses don't count.
- Click your **rank** (right part of the combo panel) and the rank board slides in as a side tab of the main window: all 50 ranks, done ✔, yours (◀ YOU), the XP each needs and how many commands to the next rank. Click the rank again, ✕ or Esc to slide it away.

## v19: themes - Skynet + Nano
- OPTIONS → LOOK → **THEME**: **SKYNET** (red machine HUD, TV static, Terminator-style sounds, cold machine voice) or **NANO** (pale-mint suit HUD with hex armour cells, nanosuit-style sounds: crisp digital blips, chirps, air whooshes, power-up / power-down swells, smoother suit voice). The app restarts by itself to switch.
- Every colour of the app follows the theme (fixed colours are translated by `T()`); each theme keeps its own sound files (v6_ / n1_) and voice cache.

## v18: credit
- The card also says **THIS APP IS FREE - IT CANNOT BE SOLD**, and the log says it at start.
- Under the title: animated **MADE BY SALUTEM** (a light runs over the letters, now and then one glitches). Click it for a small card: Steam profile (click = opens steamcommunity.com/id/hecton) and Discord name **hekton** (click = copied).

## v17: faster commands
- The threads that hear you, read the push-to-talk key and press the keys now run at high priority. With GAME FIRST on, the whole app was at low priority, so a busy game could delay commands - now only drawing the window gives way to the game.
- Push-to-talk keeps 0.15 s after you release the key (was 0.24 s).
- Every fired command shows where the time went: `… · 480 ms to fire (AI 310 ms) + keys 540 ms`. "Keys" = MACRO SPEED × number of keys - lower MACRO SPEED in OPTIONS for faster macros.

## v16: hotfix - speech AI loads again
- Fixed: since v13 the speech model never loaded ("speech error: too many values to unpack") - the model key got two new settings but the loader still read three. A new test now runs the real loading code.
- GPU MEMORY: saver falls back to normal by itself if the graphics card can't use the saver format.

## v15: speech AI on / off switch
- The first header glyph (LIVE / PTT / LOCKED / AI OFF) is now a switch: click it to take the speech AI **offline** (the model is unloaded - no RAM, no graphics memory, nothing is heard) or bring it back **online**. Coming online, lightning arcs crackle out of the glyph; they flash again when the model is ready. The choice is remembered.
- The AUTO chip in the bottom bar is gone - the Skynet eye is the auto-detect switch.

## v14: code audit - fixes for game lag
- **Push-to-talk speech gate:** a PTT press with nothing said (e.g. V used for melee) no longer wakes the speech AI. Only presses that contain speech are sent to Whisper - before, every press caused a GPU burst.
- **Faster matcher:** phrases that share too few letter pairs with what was heard are skipped, and the fuzzy-compare tables are built once per sentence instead of once per phrase. ~2.7x faster on average with identical decisions (tested on 1,343 sentences); long chatter (16+ words) is skipped. Less CPU / Python lock time right when a macro is about to fire.
- **1 ms timer only during macros:** the high-resolution Windows timer was on for the whole time the app ran; now it is switched on only while a macro presses keys.
- Hotkey watcher no longer re-reads the key settings 80 times a second; the Whisper hint is built once per profile.
- **Bug fix:** after the log trimmed old lines, clicking a line could open the wrong (old) command.
- Removed dead code; old sound files of earlier versions are deleted automatically.

## v13: game FPS - performance controls + refresh
- OPTIONS → **PERFORMANCE · GAME FPS** card:
  - **AI LOAD** low / balanced / max - how hard Whisper works per command (low = one quick pass, no second pass; balanced = beam 2, careful 2nd pass only on near misses; max = the old heavy setting).
  - **GPU MEMORY** saver / normal - saver keeps the model as int8_float16 on the graphics card (about half the VRAM).
  - **CPU THREADS** - how many CPU threads the speech AI may use.
  - **GAME FIRST** - the app runs at below-normal priority so Windows serves the game first.
  - **PAUSE ANIMATIONS IN GAME** - while another program is in front, all animations stop (header ~2 fps).
  - **DROP LATE COMMANDS (s)** - a command that could not fire within this time is thrown away, never pushed late.
  - **NOW USING** - live RAM / VRAM of the app.
- **⟳ Refresh** button next to COMMAND LOG: drops everything heard but not fired yet and stops a running macro.
- The WHISPER MODEL hint lists how much memory each model needs. A smaller model (distil-small.en) or RUN ON: cpu is the biggest saving for the game.

## v12: smoother editors, no more musical sounds
- The switches, sliders, dropdowns, arrow pad and info dots only redraw when something changes (or while the mouse is on them) - the editor windows no longer redraw dozens of widgets non-stop. The command editor's code preview and LIVE label are throttled too, and the static background changes a third of its tiles per frame.
- No tones or melodies any more: every sound is a click, metal clank, servo whir or thud. The 4 arrow keys all make the same key click, and push-to-talk press / release are short radio clicks (sounds v6).

## v11: the eye is the auto-detect switch
- Click the Skynet eye (top left) to switch auto-detect game on / off. Open eye = on: it watches your mouse pointer and waits for your game. Shut eye = off: metal shutters close mechanically and only a faint red standby slit pulses.
- It is the same switch as PROFILE → AUTO-DETECT GAME and OPTIONS → AUTO-DETECT GAME. Change any of them and the others (and the eye) follow.

## v10: static background, auto-detect game switch
- Every background (command list, log, header, OPTIONS / EDIT COMMAND / PROFILE) is now dim red-tinted TV static. No hexagons, no text, no shapes, and it never reacts to the mouse. It is 8 pre-made picture tiles that are only swapped about 11 times a second, so it is much lighter than the old hex armour.
- New **AUTO** chip (gamepad) in the bottom bar: one click switches auto-detect game on / off - profiles follow the game you open, and a profile without a game learns it the first time you talk in a full-screen program. Hover it for details.

## v9: modern Options / editor windows
- Settings sit on cards with an animated icon header (LISTENING, SPEECH AI, MACROS, SOUND).
- New controls: sliding ON/OFF switches, segmented energy-bar sliders with a value box (click, drag, mouse wheel or arrow keys), side-by-side choice buttons for short lists (ALWAYS / PTT, AUTO / GPU / CPU…) and dark dropdown lists for long ones (microphone, model, language).

## v8: Skynet eye, symbols, machine voice
- **Command list:** COMMAND and WHEN I SAY are clearly separate columns. Hover a row and a card lists *everything* you can say for it, plus its arrow code. Stratagem arrows are drawn as glowing arrows that chase-light on the hovered / selected row, with a slow scan wave down the list.
- **Symbols instead of text:** the header shows 4 animated glyphs - listening state, speech model (GPU / CPU chip + TURBO, D-SMALL…), last latency (gauge, green / orange / red) and game (IN GAME / WAITING). The bottom bar has small chips for macro speed and the lock key (and the PTT key in push-to-talk mode). Hover any of them for details, click a chip to open OPTIONS.
- **Sounds:** every UI sound was remade as metal hits, servo whirs and sub-bass impacts.
- **SKYNET VOICE** (OPTIONS): spoken confirmations and `say` actions use a cold robotized voice (Windows speech, pitched down, ring-modulated, metal echo). Each line is made once and cached in `sfx/voice/`. It also says "listening online / offline" when you lock or unlock.
- **Logo:** a red machine eye that always looks at your mouse pointer, blinks with metal shutters, half-closes when listening is locked and flashes orange when a command fires. The app icon is the same eye (the desktop shortcut is refreshed on the next start).

## v7: full names + code names

Every stratagem also answers to its **full name** and its **code name**, written and spoken: 'TD-220', 'TD 220', 'TD two twenty', 'Bastion MK XVI', 'TD-220 Bastion MK XVI'; 'MG-43' (machine gun) vs 'A/MG-43' / 'AMG 43' (sentry); 'M one oh five'; 'NUX two twenty three'. Built by `name_phrases()` / `say_number()`; very short codes (B-1) are only used together with the name ('B one supply pack') because alone they sound like everyday words. The profile upgrade (HD2_VERSION 4) merges: your taught phrases come first, macros you changed and your own commands are kept, your stratagem keys are not touched.

## v6: better recognition

- **Push-to-talk fix**: the PTT click sound used to mute the mic for 0.3 s (cutting off the start of every command) and recording stopped the instant the key was released. Now PTT ignores the app's own sounds and keeps 0.3 s before the press + 0.25 s after the release.
- **Cleaner audio into Whisper**: rumble/hum high-pass, loudness evened out, 0.25 s silence padding.
- **Accent-tolerant matching**: a sound-alike key (`phonetic()`: v=w, th=t, ph=f, qu=kv, vowels folded) lifts near misses: 'kvasar', 'real gun', 'igle airstrike', 'stalvart' all match; tested against 56 everyday callouts with no false triggers. Matcher ~3x faster (quick-ratio pre-check).
- **Focused second pass**: when the best match is a near miss (45%..threshold), Whisper listens to the same audio again expecting only the 5 closest commands (prompt + hotwords, beam 5) - only costs time on unclear commands.
- **Click to teach**: a near-miss line in the log ("closest: X · click to teach it") opens X's editor with what Whisper heard added as a phrase - the app learns your pronunciation.
- **Models**: auto on CPU = distil-small.en (small's accuracy, much faster decoder; falls back to base.en), auto on NVIDIA GPU = large-v3-turbo. New choices: distil-small.en, distil-medium.en, distil-large-v3.
- **GPU BOOST button** (⚙ OPTIONS → speech AI): runs `Install GPU boost.bat` (cuBLAS + cuDNN, ~1 GB) for whichever venv the app uses - the biggest accuracy+speed win on NVIDIA PCs.

## v4: easier editing, sounds, nanosuit look

- **Command editor builds the macro by clicking**: arrow pad (↑ ← ↓ → with W A S D on the keys) adds directions to a stratagem; with keyboard capture ON (default) pressing your real arrow keys / WASD does the same while no text box is selected. ＋ KEY captures any key or combo (`press ...`), ＋ WAIT, ＋ CLICK, UNDO, CLEAR. A live strip shows the stratagem arrows. The text box below still accepts typing.
- **Group chips**: General, Mission, Orbital, Eagle, Weapons, Backpacks, Sentries, Emplacements, Mines, Vehicles, Chat, Desktop (+ the profile's own groups) - one click; or type your own.
- **Clickable command log**: lines with ▸ open EDIT COMMAND for that command (switches profile if needed); "no match" lines open NEW COMMAND with what you said as the phrase.
- **Sounds** (⚙ OPTIONS → SOUND): volume slider (this app only, via waveOutSetVolume; the voice too), button sounds (every icon has its own synthesized sound), command chime, fail buzz (off / ptt only / always), push-to-talk press/release radio clicks (+ "denied" when listening is locked), lock/unlock sounds, spoken confirmation of the command name, spoken replies.
- **Auto-detect game**: GAME .EXE is a dropdown of the programs running right now (no alt-tabbing); with AUTO-DETECT on (default) an empty GAME .EXE is learned the first time you say a command inside a full-screen program.
- **Skynet look**: command list and log are canvas-drawn (hover glow, lock-on selection, smooth wheel scrolling, HUD scrollbars). v5: the mouse-reactive hex armor was removed (too busy + froze on clicks); now a calm fixed animation (`AmbientField`: a soft red glow band drifting down + a few embers floating up, ~40 items per panel, only moved). The list/log divider is a custom `Splitter` (glowing rail + grip pill, drag, double-click = reset, position saved).
- Options window has two columns (listening + macros | sound + speech AI + app).

## Look

- Every button is an **animated vector icon** (`draw_icon`, `IconButton`); hovering shows its name + what it does. Every option has a pulsing info dot and explains itself on hover.
- Keys are shown in plain words everywhere (LEFT CTRL + LEFT ALT + M, MOUSE 4 (BACK), stratagems as ★ ↓ ↑ ← …).
- Header logo: the Skynet eye (follows the mouse pointer, blinks, flashes orange when a command fires). Taskbar icon set per DPI (`set_win_icon`); the shortcut is rebuilt once for the new icon.

## Action language (one per line in "DO THIS")

```
press ctrl+shift+s      tap keys together  (press g 0.5 = hold 0.5 s)
down lctrl / up lctrl   hold / release
hold e 2                hold e for 2 s
wait 0.2 / wait 200ms
click left 2
type gg wp
stratagem UDRLU         or ↑↓→←↑ - uses the profile's stratagem keys (menu key + arrows/WASD)
say Hellbomb inbound
# comment
```

## Notes

- The stratagem codes were checked against public lists (Oct 2026). Arrowhead sometimes changes codes, so fix any that are off in the command editor.
- If the game misses inputs: ⚙ OPTIONS → MACRO SPEED 70-90 ms.
- No codes on the wiki for LAS-44 Nova and AMW-20 Apex (not included). Reinforcement Pods uses the code its wiki page shows (same as Upload Data).
- Matcher ignores Whisper's noise words ("thank you", "you", "bye"...) and was tuned against everyday team chat ("over here", "grenade", "hello" don't fire).
- Not tested yet on the real PC (built in a Linux sandbox; logic tested with fake Tk/Whisper). v2 = borderless, mic picker, key capture, lock key, macro speed, all stratagems.
