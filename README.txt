==================================================================
 LockIn  -  PC Lock & Focus Shield for Windows 10 / 11
==================================================================

LockIn is a self-improvement tool: you tell it WHEN your PC should
be off-limits (a duration, a time period, or a repeating weekly
schedule), and while that window is active an unclosable full-screen
shield covers your computer with a countdown. You chose NO ESCAPE:
there is no password and no cancel button - the timer must finish.

Read section 6 (EMERGENCY RECOVERY) before your first long lock.


------------------------------------------------------------------
1. REQUIREMENTS
------------------------------------------------------------------
* Windows 10 or 11
* Python 3.9 or newer  ->  https://www.python.org/downloads/
  IMPORTANT: during installation, tick "Add python.exe to PATH"
  and keep "tcl/tk and IDLE" ticked (tkinter is included by default).
* Internet once, for two small libraries (pystray + Pillow).


------------------------------------------------------------------
2. FIRST-TIME SETUP (one minute)
------------------------------------------------------------------
Step 1:  Double-click  install_requirements.bat
         (or run:  pip install -r requirements.txt )

Step 2:  Double-click  LockIn.pyw
         -> A padlock icon appears in the system tray (near the clock).
         -> The control panel window opens.

Step 3:  In the control panel, tick
         "Start LockIn automatically when Windows starts".
         This is strongly recommended: it makes scheduled locks
         survive restarts, sign-outs, and shutdowns.

Windows may show a SmartScreen / antivirus notice the first time -
see section 8 if that happens.


------------------------------------------------------------------
3. HOW TO USE
------------------------------------------------------------------
Open the control panel: double-click the tray padlock icon
(or right-click it -> Open LockIn). Right-click also offers quick
locks of 30 min / 1 h / 2 h.

1) LOCK RIGHT NOW (duration)
   Set hours + minutes (or click a preset), press "Lock now".
   Example: 3 h -> the PC is locked immediately for 3 hours.

2) LOCK FOR A TIME PERIOD
   Enter date, "From" and "To" times, press "Schedule lock".
   Examples:  2026-11-09, 14:00 -> 15:00
              today, 10:00 pm -> 11:30 pm
   Accepted formats: 14:00 (24-hour) or 2:00 pm (12-hour).
   Date accepts YYYY-MM-DD, "today" or "tomorrow".
   If "To" is earlier than "From" the lock runs overnight
   (22:00 -> 01:00 works fine).

3) WEEKLY SCHEDULE (repeats every week)
   "Add..." -> tick days, set From/To. Example:
   every Sunday 14:00 - 15:00. Overnight rules are the same.

Pending one-time locks can be removed any time while unlocked.
The green/red status line at the bottom always tells you whether
you are locked and when the next lock starts.

While locked, the shield shows:
   * a large live countdown
   * the exact unlock time
   * rotating motivational quotes (or your custom message)


------------------------------------------------------------------
4. WHAT THE SHIELD BLOCKS
------------------------------------------------------------------
While a lock is active, LockIn installs a low-level keyboard hook
and an always-on-top fullscreen window:

* Win key (Start menu, Win+D, Win+E, Win+L, ...)  - blocked
* Alt+Tab, Alt+Esc, Alt+Space                     - blocked
* Alt+F4                                          - blocked
* Ctrl+Esc, Ctrl+Shift+Esc (Task Manager)         - blocked
* 5x-Shift Sticky Keys prompt                     - blocked
* The shield window has no close button and re-asserts itself
  continuously if anything else grabs the screen or focus.
* If you press Ctrl+Alt+Del and lock/sign out anyway, LockIn
  comes back the moment you sign in again (instant re-shield,
  and at boot via autostart).

All of this stops the moment the timer ends - everything is back
to normal automatically.


------------------------------------------------------------------
5. NO ESCAPE - PLEASE READ
------------------------------------------------------------------
You deliberately chose the strictest mode. That means:

* No password, no "quit" button, no trick keystrokes.
* The ONLY way out is the timer (or the emergency recovery below).
* LockIn asks for confirmation before any lock longer than 6 hours.
* Suggested habit: before a long lock, put food/water/notes within
  reach and remind family/roommates that you cannot be interrupted
  digitally. The PC is unusable for EVERYONE on that account.


------------------------------------------------------------------
6. EMERGENCY RECOVERY (if something goes wrong)
------------------------------------------------------------------
LockIn is designed to FAIL OPEN: if the program itself crashes,
your PC unlocks (it never wants to destroy your data). But in the
rare case you truly must get in before the timer ends:

  1) Boot Windows into Safe Mode
     - Settings -> System -> Recovery -> Advanced startup,
       or: hold Shift while choosing Restart,
       then Troubleshoot -> Advanced options -> Startup Settings.
     (Windows does not launch startup apps in Safe Mode, so LockIn
     stays inactive.)
  2) While in Safe Mode, do ONE of these:
     - Open the folder  %APPDATA%\LockIn  and delete config.json
       (this clears all pending one-time locks), or
     - edit config.json and set  "enabled": false  (master
       kill-switch), or
     - untick "Start with Windows" later / delete the shortcut.
  3) Reboot normally.

Config location:  C:\Users\<you>\AppData\Roaming\LockIn\config.json
Log file:         C:\Users\<you>\AppData\Roaming\LockIn\lockin.log


------------------------------------------------------------------
7. HONEST LIMITATIONS
------------------------------------------------------------------
* Ctrl+Alt+Del opens a SECURE screen no normal program can block.
  From there a determined person can still reach Task Manager and
  kill python.exe - LockIn then fails open and enforcement stops.
  This tool is a commitment device against your own impulses, not
  a security product against other people.
* If a fullscreen game was running when the lock started, click
  the screen once so the shield can take over.
* Enforcement is per Windows account; other accounts are unaffected.
* If LockIn is not set to start with Windows, a reboot removes the
  active shield.


------------------------------------------------------------------
8. TROUBLESHOOTING
------------------------------------------------------------------
* "python is not recognized"      -> reinstall Python with
  "Add python.exe to PATH" ticked.
* No tray icon appears            -> run install_requirements.bat
  (the tray needs pystray). LockIn still works without it, just
  without the tray: start LockIn.pyw again to reopen the panel.
* Antivirus flags the keyboard hook  -> this is expected for any
  app that hooks the keyboard. Allow it if you trust the source
  (you can read every line of LockIn.pyw - it is plain text).
* SmartScreen "unknown publisher" -> More info -> Run anyway.
  LockIn is unsigned because code signing costs money.
* Lock did not fire at the scheduled time -> was LockIn running?
  Autostart must be ticked; check lockin.log for errors.
* Want a single .exe instead of the .pyw?  Run build_exe.bat
  (optional, builds dist\LockIn.exe with PyInstaller).


------------------------------------------------------------------
9. UNINSTALL
------------------------------------------------------------------
1) Tray icon -> Exit (only possible while unlocked).
2) Untick "Start LockIn automatically when Windows starts".
3) Delete this folder. Optionally also delete %APPDATA%\LockIn.

------------------------------------------------------------------
 LockIn - for people who outsource discipline to their own PC.
------------------------------------------------------------------
