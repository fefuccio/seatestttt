# Sea Angler Assist
A visual overlay and accessibility companion for Sea Angler in NTE.
It helps manage the fishing loop (casting, reeling and bait swaps) so you don't have to babysit every step.

## Core Features
- Casts and hooks
- Helps align the reeling bar and clears the result screen
- Reads your available baits and eventually swaps the bait based on your priority list
- Window stays on top only while the game's focused (also works while minimized)
- Saves your settings automatically (bait priorities, hotkeys, capture mode, etc...)
- Debug console if you want to see the status of stuff

## Getting Started
1. Open Sea Angler's fishing minigame
2. Set up bait (optional)
3. Press **Start**
4. Press **Stop** when you've had enough

## Known Limitations
- Needs the game focused to be able to help.
- If it can't detect a hook, bar or result screen after a while, it'll pause or keep going (depending on your "Ignore Abort" setting).

## FAQ
**Q: It isn't doing anything / says "No bait detected". What's wrong?**
A: Make sure the fishing minigame is **open** and your character is holding the rod (it needs to see the bait UI to start casting). Also check that your **Capture Mode** matches how you're running the game (**Auto** or **Window** usually works best).

**Q: I'm getting an Admin warning on startup. Do I really need it?**
A: Technically no, but the game itself runs as admin, so some features won't work right without it. I'd just run it as admin.

**Q: The hotkeys aren't working. Why?**
A: Global hotkeys need the app running as **Administrator** (it'll warn you on startup if it's not). Also check if **"Only when game is focused"** is on in Hotkeys settings.

**Q: Does this send keyboard inputs or controller inputs?**
A: Controller input via ViGEmBus by default. Falls back to keyboard if that's not available (which needs admin too).

**Q: Why does the overlay disappear when I alt tab out of the game?**
A: It only stays "Always on Top" while the game is the active window. If you switch to something else it steps back so it's not in your way, then pops back up when you return.

**Q: How do I update my current instance?**
A: It checks GitHub for new releases on launch. Say yes and it grabs the new `.exe`, closes the app, swaps the files, and relaunches automatically.

**Q: Where are my settings and bait data saved?**
A: `%APPDATA%\SeaAnglerAssist`.