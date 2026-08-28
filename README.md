# Sea Angler Assist

A small tool I put together for the fishing minigame in Neverness To Everness.  
It watches the fishing UI and keeps things moving so there's no need to stare at the screen the whole time.

## What it does

- Tracks the cast, hook, reel and result phases so the overlay stays in sync with what's on screen.
- Checks the reeling bar and where the target zone is.
- Lists the baits you have, lets you set a priority order and shows which one is currently active.
- Overlay only stays on top while the game is focused. When you alt-tab it stays back and comes back when you return.
- Settings are saved automatically (bait order, hotkeys, capture mode, etc...).
- There's a debug console if you need to see what's going on under the hood.

## Setup

Grab the latest release from the [Releases page](https://github.com/sea-angler-assist/releases) and run the exe. No installer needed.

On first launch it'll ask for the game path if it can't find it at the default location:  
`C:\Program Files\Neverness To Everness\Client\WindowsNoEditor\HT\Binaries\Win64\HTGame.exe`

You can tweak settings in the app:

- **Capture mode** - Auto, Window or Monitor. *I usually use Window (it sees the game client directly even if something is on top of it)*
- **Bait priority** - drag the baits in the order you want them used.
- **Hotkeys** - for start/stop, toggle auto-switch, detect baits, etc... these only work if the app is running as admin or if focused.
- **Minimize to tray** - when enabled closing the window just hides it to the tray. Right-click the tray icon for options.

To actually use it:

1. Open the game, get into the fishing minigame and make sure that you're either in the fishing menu or that your character is holding the rod.
2. Press **Start** in the app (or use the hotkey).
3. The overlay will show you what's happening. Cast when the cast indicator shows, adjust when the bar drifts, etc...
4. Press **Stop** when you're done.

If the app can't detect something for a while, it might pause or keep going depending on the **Ignore Abort** setting. I added that because if for some reason the detection gets stuck I don't want it to stop unnecessarily.

## Notes

- The game needs to be focused for reliable detection. If it isn't, the overlay will just sit there.
- Window capture is more reliable if the app is running as admin.
- I've mostly tested this at 1920x1080. Other resolutions should work, but you may need to adjust.

## FAQ

**Q: It says "No bait detected" even though I have bait.**  
Make sure the fishing minigame is open and you're holding the rod. The overlay needs to see the bait UI. Also check your capture mode – Auto or Window usually works.

**Q: Hotkeys don't do anything.**
Run the app as administrator. Global hotkeys need elevated privileges. Also, if "Only when game is focused" is checked, they'll only work while the game is the active window.

**Q: The overlay disappears when I alt-tab.**  
That's intentional. It only stays on top while the game is focused. When you switch to another window, it hides so it's not in the way.

**Q: Where are settings saved?**  
`%APPDATA%\SeaAnglerAssist\` – there's a `settings.json` and a `baits.json`.

**Q: Does it update automatically?**  
It checks GitHub on launch. If there's a new version, it'll ask you. If you say yes, it downloads, closes, swaps files, and relaunches.

## Support

If something's broken or you have a suggestion, open an issue on the [GitHub repo](https://github.com/your-repo-link). I'll take a look when I can.

---

*Happy fishing!*