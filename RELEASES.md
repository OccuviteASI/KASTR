# KASTR release notes

What changed in each build, newest first.

## v0.21.87 — KASTR stays maximized, invite links survive an update, photos and backstage in My room, a steady mic

**The window comes back maximized (Kenton: "It still isn't saving position after upgrade. Or restart.").** When KASTR relaunched after an update or a restart while the old browser was still closing, Chrome opened the new window inside that old browser, which ignores the "maximized" instruction, so it came back at a default size. KASTR now finds its window after every launch, even inside the old browser, and maximizes it if it was maximized before. Windows and Linux (X11).

**Invite links that open the app (Kenton: a coworker's link "opened the app and then took him straight to the lobby").**
- An invite you open now survives KASTR updating or restarting straight away. It is kept for 2 minutes and offered again after the relaunch.
- An invite you have just opened always wins over KASTR's automatic rejoin of the room you were in before.

**My room: People, photos and backstage (Kenton: initials instead of photos; "It is not showing another person so I can choose a backstage person").** My room is never listed, so its people did not publish the records that People, profile photos and the presentation's backstage list read. Each person's KASTR now gives its name and photo to the people in the room only. Your own row always shows your own photo. If your photo cannot be shared through the relay host, a warning now says why (it used to be a hidden note). People can announce their photo to the room again on secured relays.

**Switching noise suppression keeps the mic working (Kenton: "it will stop my mic from working and I have to mute and unmute").** Leaving background noise removal (RNNoise) used to cut the filtered sound while it still fed the stream. Now the microphone goes back in first, and for a few seconds after any switch the stream follows the live microphone.

**Pointing on a shared screen (Kenton: clicks were "doing the normal zoom in/out instead of just showing me the clicks").** On the stage, a pointing click shows the click ring and nothing else. It no longer zooms or sends the view back to the gallery. A click on a small rail tile still brings the share to the stage.

**Smaller things**
- Share menu rows keep their dark background on hover, with a blue outline, instead of turning bright blue with unreadable text.

## v0.21.86 — invite links anyone can open, profile photos in Everyone online, a steadier presentation upload

**Invite links on the public web address (Kenton: "Invite link is using the internal IP of the relay I'm connected to, and not a web address that anyone can access").**
- The hub's Relay page has a **Public web address** field in the One port (Cloudflare Tunnel) card. Once a visitor has come in through the tunnel, a **Use <name>** button fills it in with one click.
- Every relay picks the hub's address up within about 3 minutes. Invite links then open that address and connect through the tunnel, so people outside your network can join.
- The address must be https and a name, never an IP address. KASTR never takes it from what a visitor's request claims, because an invite link carries a secret.
- Until it's set, links use the old address, and copying one that only works inside your network shows a warning that says so.
- **After updating:** set `https://kastr.madlabs.app` on the hub's Relay page.

**Profile photos in Everyone online (Kenton: "showing a circle with a color and initials, not the uploaded photo").** Your own row uses your profile picture. People in other rooms and the Lobby show the photo from their room's records, and people in My room and other private rooms show the photo their KASTR sends with its regular updates. Only the address of a picture stored on a relay is passed on.

**Presentations**
- The same slide uploaded twice at once no longer crashes the slide store on Windows. Each upload writes its own temporary file, and the page now renders and uploads each slide once.
- If sending a deck to KASTR breaks off (for example while KASTR restarts for an update), the message says what happened instead of "Failed to fetch".

**Remote control of Linux machines.** A Linux relay or box that can't be controlled used to say "nobody is signed in" whatever the cause. The hub's Machines list and the machine's own Relay page now give the real reason: KASTR runs without a desktop display (started from a service or SSH), the X11 libraries are missing, or XTest is missing.

## v0.21.85 — everyone online in People, shares in the stream library, a clean end for My room guests

**Everyone online (Kenton: "Add an option to see all people online in the people drop-down").** The People panel has two tabs: **This room** (the default) and **Everyone online**.
- Everyone online lists everyone on the fleet, guests included, grouped by the room they're in or the Lobby. It has search and updates within about a second when someone moves. Camera boxes and relays aren't listed.
- **Go** takes you to that person's room, and asks for the code if the room is locked.
- Right-click or ⋯ on a person offers the same invites as the rail: Invite to this room, and Invite to My room.
- **Admins** (the admin access code) also get **Restart their KASTR** and **Move to another relay…**, which until now were only on a relay machine's own Relay page. The person still sees the 10-second notice first.
- People in someone's My room show as **In a private room**, with no room name, unless you're allowed in that room. In the Lobby nobody sees names, as before.
- If the hub can't be reached, you still see the people on your own relay, with a note saying so.

**Shares in the stream library (Kenton: "Publisher+relay boxes with shared streams should also show up under streams drop-down").**
- **On a relay or hub machine,** everything its KASTR app shares (screen, webcam, RTSP feed, media file, GoPro, presentation) appears in **Streams** automatically, under that machine and its site. Each share has its own **In the stream library** switch, so a private screen can be kept out.
- **On anyone else's KASTR,** each share has the same switch, **off by default**. Find it in the share's ⋯ menu or at the top of "Show in other rooms…".
- A listed share **stays in its own room exactly as before**. Remote control, pointers and presentations keep working there. People watching it from Streams in another room get the picture only: no Request control and no pointers.
- **Camera boxes in a real room** (Kenton: "stay in room + listed"): a camera's library switch now keeps it in its room and also lists it. Boxes in no room still move into the library as in 0.21.84.
- An unwatched listed share costs nothing extra. Upload rises only while someone watches it from Streams.
- Turning the switch on for a share from this computer (an RTSP feed, camera, media or screen share) restarts it once, with a short gap.

**My room guests who came in by link only.** When the owner leaves, goes quiet, closes KASTR or takes back the link, a guest without an access code used to be stuck in the closed room. Their session now ends with a screen that says why, for example "Owen left their room — the room closed". **Join again** reuses the same link: it says "isn't in their room right now" until the owner is back, then lets them in. Guests who have Lobby access still move to the Lobby.

**Smaller things**
- In an empty room, the **Add streams from the library** card sits at the bottom of the stage instead of over your own picture.
- A page whose relay can't be reached no longer logs an error every 8 seconds.

## v0.21.84 — the stream library, presentations in KASTR, the window stays where you left it

**The stream library: streams that belong to no room, which any room can pull in (Kenton: "stream to an 'available streams' section ... accessible inside of each room for adding to a grid or view in that room").**
- **Streams** (a new toolbar panel, like People / View) lists every stream on the fleet, grouped Site ▸ box ▸ stream, with stills, search, and filters for Live now, kind and Site. Show offline lists cameras that aren't streaming. Everyone on the fleet sees it, viewers too; it can be pinned to the right-hand column like the other panels.
- **Camera boxes publish into the library.** A box that wasn't in a real room moves its cameras there **automatically** when it updates (about 10 s). Pins, spotlights, room grids and My room pins that showed those cameras follow them, with no duplicates. A box in a real room stays as it is until a camera's **In the stream library** switch (in its rooms picker) is turned on. **Show in rooms…** keeps working.
- **Using a stream:** a publisher's row menu offers **Add to this room**, **Spotlight for everyone**, **Add to a grid**, **Add to My room** and **Watch here, just me** (viewers see these greyed, with the reason). Rows can also be dragged onto the stage, and the grid builder has a Library group with **Build a grid from these**.
- **Browsing never wakes a camera.** Hovering a live row shows a peek; an asleep camera offers **Preview**. An asleep camera added to a room opens in about 2 s ("Starting…" then the picture).
- **Across sites,** a library stream is fetched the cheapest way through the relay mesh — in the lab, a stream from one site to another over a direct link put nothing through the hub.
- **Invite-link and My room guests** see only the library streams added to their room.
- **Admins** on the hub's Relay page get a Stream library card: the fleet switch, and Hide / Unhide / Rename per stream. A hidden stream disappears from every site within seconds and its pins say "No longer in the library". The Links card shows each relay's site name.
- **If the hub goes down,** library streams keep playing and the panel says the list is from when it was last reachable; adding to rooms waits for the hub, and hidden streams stay hidden.
- Older KASTR apps (0.21.83) in a room still play library streams added to it.

**Presentations in KASTR (Kenton: "using powerpoints, or other documents, directly inside of KASTR ... The person presenting and the 'backstage' person controlling need to see the notes/slides upcoming as well as what is live while others only see the presentation").**
- **Share ▸ Presentation…** opens a **PowerPoint (.pptx) or PDF** deck. When PowerPoint is installed on your computer, KASTR uses it to draw the slides exactly; otherwise KASTR draws them itself. (A deck shared from a web browser never starts PowerPoint on the relay's machine.)
- **The presenter view** shows the live slide, the next two, your notes (editable), a timer, the slide strip, Black / White screen, and works with clicker keys. Pick **backstage** people — anyone in the room — and they get the same view and can move the slides; two people pressing Next together move one slide.
- **Everyone else sees only the live slide**, sharp, about 0.1 s after Next. They never get the notes, upcoming slides or earlier ones — KASTR refuses to hand them over. Slides are encrypted end to end.
- Library tiles and the rest of the room keep playing while you present.

**KASTR comes back in the same window after an update (Kenton: "after an upgrade while launching KASTR, it doesn't hold my same window state").** The Relay and stats windows were saving their own size and position over the main window's, and a minimized or hidden window could save a position off the screen. Now only the main window is remembered, and only while it's visible on screen.

## v0.21.83 — admins control relays and boxes without asking, files across remote control, pointers with sonar, a smaller share pill

**Fleet admins can control relays, hubs and camera boxes without asking — only where that machine opted in (Kenton: "allow remote control with the admin permissions on a relay/hub/camera box. This should be opt-in only and a check box in the relay server page").**
- **Opt-in on the machine itself:** the machine's own Relay page has a Remote control card with "Let fleet admins control this machine without asking", off by default. Only that machine's own page can switch it on; the hub sees the setting but can never turn it on.
- **Fleet admins only** (the admin access code): **More ▸ Machines…** (and the Relay menu) lists every opted-in machine — name, site, role, online, version, screens, who is connected. **Control** opens its desktop in a private window with control already granted, never shown in any room. The hub's Relay page has Control buttons too, also in the mesh map's zoomed relay.
- **Switch screens and windows (Kenton: "allow for switching to different windows/monitors on the device"):** each monitor, all monitors, any open window (with thumbnails), previous / next monitor (Ctrl+Alt+PgUp/PgDn) and Bring to front; each switch comes back in about 0.5–1.5 s, control kept.
- **On the machine:** the red pill names the admin, Ctrl+Alt+Space or Stop control ends it, and every session (who, from where, how long) is logged on the machine and in the hub's Remote sessions table. A locked screen or nobody signed in is shown in Machines….
- Administrator windows on that machine work only if KASTR there runs as administrator; otherwise the session says so.

**Copy files and pictures across remote control (Kenton: "Am I able to copy a file on my machine or the remote machine and paste it on the other side?").** Files, folders and pictures copied on either side paste on the other (Explorer, Paint, Word…); a file dragged onto the shared screen lands where it is dropped (a folder, the desktop, else Downloads\KASTR). Up to 100 MB comes over at once, bigger copies wait for "Get them" or the controller's Ctrl+V. Progress with Cancel; the sharer sees "Bob copied report.docx from your computer". Encrypted end to end — others in the room can't read it. Limits in kastr.ini (2 GB a file, 8 GB a session); received files are cleaned up 10 minutes after control ends. The Allow prompt now mentions file copying.

**Point on a shared screen without controlling it (Kenton: "a view-only mode ... when they click it makes a little sonar thing around the mouse click to show everyone where it was clicked").** Anyone watching a screen or window shared from the KASTR app can ask **Point on this screen**, or the sharer switches on **Let everyone point**. Each person gets an arrow with their name in their colour — the sharer's own pointer too — and a click makes a **sonar** ripple shown on the sharer's real screen and on everyone's view. Pointing never clicks or types on the sharer's computer. Up to 12 pointers; the sharer removes anyone, and "Show my clicks" shows their own clicks as sonars. Phones point with a tap.

**The share pill (Kenton: "when I try to click in that space it doesn't work ... The pill should be smaller also").**
- The person in control can click, drag and scroll on whatever is under the pill; the sharer's own clicks still reach its buttons. In their view a faint outline shows where it sits.
- Smaller (28 px tall instead of 40), shorter labels, and above the shared window when there is room.
- While controlled it offers **Stop control** and **Stop sharing** (ends both at once).
- **Administrator windows are obvious now (Kenton: "The pop-up saying it was admin wasn't easy to notice"):** an amber badge and outline stay on the admin window in the controller's view while their pointer is over it; Windows blocks clicks, typing, and moving or closing such a window unless KASTR on that computer runs as administrator.
- Hovering the screen you control no longer pops up a grey tooltip.
- **"Share something else" and screen switches no longer freeze:** the old capture now ends cleanly first, so the new one appears in about a second (it could freeze for 14 s or more).

**Smaller things**
- **The rooms toggle moved next to the room name (Kenton: "make the expand/collapse icon more like this and up in the bar next to the room name")** — a panel icon that fills in on hover; the arrow points left to collapse, right to expand.
- **Zoom + and − show only while zoomed** (Kenton: "hide the + and - buttons for zoom except when the zoom label is showing also").
- **No more false "relay link dropped" log lines:** what looked like the spoke-to-hub link timing out every 10 s was KASTR's own bandwidth meter reading the relay's stats; those reads now close after 2 s and are not logged. The real hub link was never dropping.

## v0.21.82 — click the zoomed relay to go back

**On the mesh map, clicking the relay you zoomed into takes you back to the full mesh (Kenton: "when you click on that same relay again it should go back a level")** — like ← Full mesh or Escape; its tooltip says so. Dragging it still just moves it.

## v0.21.81 — save a recording as MP4, WebM, MKV, MOV, M4A or MP3

**Recordings save in the format you pick (Kenton: "allow for saving in multiple different formats. Default to MP4").** When a recording stops, the save dialog lists **MP4** (picked every time — plays everywhere), **WebM**, **MKV**, **MOV** (QuickTime / editing apps), and audio only **M4A** and **MP3**; the file name, Save as… and Download follow the choice.
- **MP4 needs no conversion on Windows:** KASTR now records H.264 + AAC straight away (5 Mbit/s, was VP9 at 4), so MP4 saves in under a second and MKV, MOV and M4A are quick copies; WebM and MP3 are converted by the app's own ffmpeg ("Converting… 42 %", with Cancel — the recording is kept).
- **Long recordings are fine:** a 1.6 GB, 5-minute recording saved without the page's memory growing; nothing is left behind on disk after saving.
- **Web viewers** (no KASTR app) save what the browser recorded (MP4 in Chrome); the other formats show "needs the KASTR app".

## v0.21.80 — two pointers in remote control, much less delay, grid cameras that open

**Each person gets their own pointer (Kenton: "I would like to have a mouse with a name of the person controlling it, rather than them controlling my own mouse. Allow both mice at the same time").** The person in control now moves their own arrow, tagged with their name in their colour, on your screen — your cursor stays where you left it, and you can both work at once.
- **Clicks without taking your cursor:** in classic Windows windows (Notepad, dialogs, settings, forms) their clicks go straight to the window, even when it is covered. Browsers, Electron apps, Office documents, Explorer and games only accept a real cursor, so there your cursor jumps to their spot for the click and straight back — never while you are holding a mouse button (their click waits until you let go), and if you press during their drag, yours wins.
- **Both type at once.** Their keys reach the shared window; when it isn't in front, typing goes to its text box where the app allows it, otherwise they are told to click inside first.
- **Your mouse no longer pauses theirs.** Stop control, Ctrl+Alt+Space, stopping the share or leaving still end it.
- **Viewers see both pointers with names while someone has control** (Kenton chose: only during remote control): the controller's arrow and name, and your name beside your cursor, lined up with the video.
- On Linux the controller gets a real second pointer and keyboard.

**Remote control is much faster (Kenton: "There is a bit of delay").** From a click to seeing the result on the controller's screen: about 0.7 s before, about 0.15 s now (lab). The controller's view of the shared screen now plays with no extra buffer and at top priority while they have control, the input goes out at once, and the sharer's KASTR takes it over a direct local connection.

**A camera clicked in a grid opens instead of snapping back (Kenton: "It expands the view like it's going full and then closes immediately and goes back to the grid").** The cause on Mendon was the double-click: the first click started opening a camera that wasn't playing yet, and the double-click that followed un-zoomed the cell, which cancelled the open. Cameras already playing elsewhere opened at once, which is why two of Mendon's always worked. A double-click is now ignored while a cell is opening (lab: 11 of 11 double-clicks open, before 5 of 11).
- **A camera you had parked, asleep when clicked** (transcoded box cameras sleep while unwatched) was sent back to the grid as "not watched"; the click now counts as watching it, wakes it and waits on the cell (lab: 19 of 19).
- **Grids pulled from another room:** a camera listed into the room but not yet loaded now loads on the click, an asleep one opens in 1–2 s instead of 9–15 s, and one not shown in this room at full quality stays on its cell and says so (the box can add it with Share ▸ Show in rooms) instead of waiting 90 s.
- A camera that really went away still returns you to its grid. Every time the stage goes back to a grid, the reason is now kept in the app's diagnostics.

## v0.21.79 — remote control of a shared screen, a colourful mesh map, native screen sharing on Linux

**Ask to control someone's shared screen (Kenton: "request remote control when someone is sharing their desktop and a prompt to allow that user to take control of your machine. Local input always overrides remote input").** On a screen or window shared from the KASTR app, **Request control** sits in the share's menu and on a spotlit share.
- **Only publishers and admins of that room can ask**; viewers never see it, and the relay refuses a forged ask.
- **The sharer clicks Allow every time** ("<name> asks to control your window 'Title'. They'll be able to use your mouse, keyboard and clipboard."), in KASTR and on the share's own bar. A "no" holds further asks back for 30 s.
- **Mouse, keyboard and clipboard** (text, up to 64 KB, both ways while control lasts). Clicks land on the shared screen or window only; a covered window is brought to the front.
- **Your own mouse and keyboard always win:** any local input pauses remote input at once and for 3 s after you stop, and releases anything the other person was holding; they see "<name> is using their mouse — paused".
- **It lasts until you stop it:** a red always-on-top bar says who is in control, with **Stop control** — or press **Ctrl+Alt+Space**. Stopping or pausing the share, either person leaving or closing KASTR, or the controller going quiet for 10 s also ends it.
- The controller sees "Controlling <name>'s window" with **Release** (or holds Esc for 1 s); in full screen their system keys go through too.
- Not on browser shares, cameras or Wayland desktops (the asker is told why). Windows with admin rights and the Windows sign-in / UAC screens can't be controlled; the controller is told.

**Native screen sharing on Linux (X11).** Linux desktops now get the same list of screens and windows as Windows (no browser prompt), which is also what makes them controllable. Linux screen shares carry no sound, so **Use the browser's picker instead (shares sound)** stays one click away. Wayland keeps the browser's picker. `KASTR_NATIVE_SCREEN=0` turns it off.

**A more colourful, expressive mesh map (Kenton: "I want the mesh map to be more colorful and expressive").**
- **Every relay has its own colour** (the hub ASI blue, the backup violet; red and amber stay reserved for trouble), on its node, name chip, tooltips and its half of each link — a link blends between its two relays' colours. Hub and backup links are drawn as hollow pipes.
- **Traffic flows:** dots run along each link, one lane each way in the sender's colour — faster, denser and bigger with more bitrate; idle links are thin and still.
- **Load rings:** two rings round each relay fill like meters (inner in, outer out; deep = its own clients, light = relay links) and the relay glows with its load.
- **Trouble reads at a glance, by pattern as well as colour:** down = red broken line with ✕, slow / flapping = amber with ⚠, not linked = grey dots, needs update = ↑ badge. A legend shows each mark.
- **Zoomed view:** people are green circles, camera boxes magenta squares, web viewers blue diamonds.
- Values ease between refreshes; hovering a relay or link dims the rest. With reduced motion nothing moves (arrows show direction).

## v0.21.78 — My room for others, panels that stay open or pin to the side, a mesh map that shows the traffic

**My room can be shared (Kenton: "I need to be able to share out access to 'my room' as wanted").** My room is now always the first card on the rooms rail; before you have one it opens a setup that explains what My room does and asks for a passcode. Once it exists, **Share My room** has two ways in:
- **People with access** — pick people seen on the hub; they see "<your name>'s room" in their rooms list (marked "away" while you are not in it). Tick **Can arrange** for one person to help you arrange; remove anyone at any time.
- **Invite links** — 1 hour, 24 hours or 7 days, revocable, like a regular room's.
- **Guests watch and talk** (camera, mic, chat); only you (and the one helper) pin, spotlight and arrange. The hub enforces it.
- **Only while you are in it (Kenton: "Only allow people in 'My room' if the owner is in it").** Nobody else gets in while you are away ("Kenton isn't in their room right now"); when you leave, switch rooms, close KASTR or drop off for 15 s, everyone else is sent to the Lobby with a note saying why, and the hub stops their access.
- The My room dialog no longer shows two Close buttons.

**Invite someone with a right-click (Kenton: "Allow right clicking on a person on the left and inviting to the room you're in, or my room").** Right-click a person on the rooms rail or in People (the same menu in both places) → **Invite to <this room>** or **Invite to My room**. Their KASTR shows "<name> invites you to <room>" with **Join** / **Ignore**; Join needs no room code. Anyone in a room can invite to it (6 a minute at most).

**Panels stay open, and can be pinned (Kenton: "don't collapse them until clicking outside of them or clicking on another menu item, or clicking on the same menu item").**
- People, View, Files, Chat and Share close only on a click outside, another toolbar button or their own button — no longer when a file or colour picker opens, when you switch windows, or when a confirm prompt (e.g. Mute all) is answered. View stays open while you switch layouts (Full screen still closes it).
- Share closes once you choose a screen, window, tab, presenter mode, "Share something else" or a media file; adding an RTSP camera, device, GoPro or webcam leaves it open so you can rename the feed first.
- **Pin to the right (Kenton: "Allow user to pin people, view, files, chat, share to the right side").** A pin in each panel's header docks it into a column right of the video: pinned panels stack, the dividers and the column's edge resize them, the video shrinks rather than being covered, the toolbar button folds a pinned panel, and Unpin returns it to a dropdown. Kept per device; not on phones.
- **Dropdowns show their whole list** when there is room below (Kenton: "there shouldn't be a scroll bar") and only scroll in a short window.

**Room timers start with the first person (Kenton: "We don't need to show the time counting up on a room until a person is in the room, not just camera boxes").** A room holding only camera boxes shows no timer.

**The mesh map shows the traffic (Kenton's requests on the hub's Relay page).**
- **Hover a link** for its bandwidth each way — direct, hub and backup links alike (lab: within 1–4 % of what was received). Line thickness follows the bitrate.
- **Hover a relay** for its own load: local traffic (its users and cameras), relay-link traffic and the total, plus streams and sessions.
- **Click a relay to zoom in:** that relay with every client connected to it — people's KASTR apps, camera boxes, web viewers — with names, what each publishes and watches, and **each client's own download and upload on hover** (each KASTR reports its own figures; an older KASTR shows "no figure"). "← Full mesh" or Escape zooms back out; a refresh keeps the zoom.
- **Set a cost on every link,** including each relay's own hub and backup link — applied live, without restarting the relay (a 0.21.77 relay restarts once). Pairs that are not linked are drawn faint and clickable, with the reason.
- **A layout that fits itself:** relays spread out, linked relays sit closer, it re-fits as relays come and go; drag a relay to pin it, **Re-arrange** releases it. A half-typed cost survives the 5 s refresh.
- **Figures stay current:** a camera nobody watches is not encoded, so it reads **idle** at both ends; each KASTR re-reports within ~10 s when its own figure changes (not once a minute), and where the relay and a client briefly disagree the map says which is newer.
- The hub link moved into the relay's live peer list, so a renewed hub token or a cost change no longer restarts the relay.

## v0.21.77 — relays link directly over private paths, a live mesh map, steady links between relays, Docker images on GitHub

**Relays link directly when they can reach each other privately (Kenton: "I don't want everything to necessarily go through the hub except the tracks that actually do get seen through it" and "have the relays do a traceroute ... if they can reach each other without going to a public IP, they could just mesh").** Every relay now tests the other relays' private addresses every few minutes: can it reach the relay there, how fast, and does the route (traceroute) stay on private addresses the whole way — the same LAN or a site-to-site VPN. Two relays with a private path link directly, and each stream takes the cheapest path by round-trip time.
- **The hub and the backup hub stay connected to every relay**, as last-resort paths (cost 50 by default, set on the Relay page): a stream crosses them only when someone watches through the hub or the backup itself, or when no direct path exists. Before, a relay connected to the backup only after a failover.
- **If a direct link drops, streams fall back through the hub within seconds**, and move back to the direct link when it returns.
- Changing links restarts nothing; changing the hub / backup cost restarts each relay once.
- **Lab check:** a stream from one spoke to another took the direct link and the hub carried nothing for it; cutting the link moved it through the hub after a 13 s gap; restoring it moved it back in about 10 s with no gap; viewers on the hub and the backup pulled over their own links.

**A live mesh map on the hub's Relay page (Kenton: "a visual mesh view that is dynamic, rather than just text").** Each relay is a circle (the hub in the middle, the backup beside it), each link a line — green up, amber slow or flapping, red down, dotted off, dashed for the hub / backup paths — animated while streams cross it (still when reduced motion is on). Hover a link for its round trip, hops, whether the route stays private, its cost and the streams crossing it now; click it to turn it on or off, set its cost or address, or go back to automatic; click a relay for its probe results. Relays can be dragged and keep their places. A links table sits underneath. A link a probe could not reach says what to open ("blocked? open UDP and TCP <port> on <relay>"); a relay older than 0.21.77 shows "needs update".
- **The relays no longer pin the hub's certificate** (Kenton approved): every link between relays fetches the other relay's certificate fingerprint when it connects, as the first connection to the hub always did. A hub restart no longer restarts every spoke.

**Steady links between relays when a link is too thin (the Southridge / Mendon stalls).** When more video was asked of a link between two relays than it could carry, the relay kept queueing the stream that was losing out, and after about 40 s every stream on that link dropped to 0–3 fps until people re-joined (moq-relay 0.17.7 does the same). Every relay KASTR starts now holds back at most one short window per stream and keeps only about 2 s of history besides the live picture, so the stream that loses out skips ahead instead of choking the link.
- **Lab check:** two 1080p streams over a 4 Mbit/s link between relays — the important one held 29.9 fps for 7½ minutes (before: 1.7 fps after 95 s), the other kept about 9 fps; a 10.7 Mbit/s 4K stream still arrived in full at 60 ms round trip, and 120 ms was no worse than without the change. Relay memory stayed at 30–40 MB.
- Applies to the hub, the backup and every relay once each restarts on 0.21.77.

**KASTR's Docker image is published to GitHub's registry (Kenton: "Lets use the Git Repo").** Each release is pushed privately as `ghcr.io/occuviteasi/kastr:<version>` and `:latest`; `docker-compose.yml` uses it by default, with optional automatic image updates (`docker compose --profile autoupdate up -d` adds Watchtower). DOCKER.md has the one-time login for each Docker host.
- **Fixed:** the container's startup script tried to run `docker compose pull` on its first start (a comment it writes into kastr.ini held backticks), and printed a harmless error on a fresh volume.

## v0.21.76 — what matters wins on a thin link, and streams in other rooms only while they stream

**What matters wins on a thin link (Kenton 2026-10-20: streaming quality ahead of 0.22).** A lab measurement showed the relay gives a higher-priority stream its full frame rate on a link too thin for everything, both from the relay to a viewer and from a spoke to the hub, while the lower one drops frames. With everything at the same priority, whichever stream was opened first won. KASTR now ranks every tile:
- **On the stage (spotlit, opened, pinned): highest. Then grids, then shared screens and camera feeds, then people's cameras in the rail.** Each tile's sound sits just above its own picture, and room information (catalogs) always goes first.
- The rank follows the stage live: open a camera and it moves to the top at once (the relays are told mid-stream).
- **A grid's picture adapts to the uplink, with a floor:** the box's grid now steps its bitrate down when the upload can't keep up, but never below 600 kbps, so a weak uplink sheds detail before it loses the picture.

**Streams shown in other rooms appear only while they stream (Kenton: "streams that are only running sometimes ... never go away when nothing is streamed, they always show connecting").** A camera, share or grid shown in other rooms (Show in rooms…, Also show in) is now listed there only while it is really on the air: it disappears about 20 seconds after it stops and comes back within about 10 seconds of starting again. Its room choices are kept. A box camera that is only asleep because nobody watched it (0.21.73) stays listed, since opening it wakes it.

## v0.21.75 — invite links, My room, boxes that share without a room, hide a camera in my grid view

**Room invite links (Kenton: anyone in the room can copy one; 24 hours by default; the room's creator or an admin revokes them).** **Share invite** (People) now asks how long the link should work — 1 hour, 24 hours or 7 days — and copies it. Whoever opens the link joins that room with just their name: no access code, no room code.
- The link opens KASTR if it is installed on that computer (KASTR registers itself for kastr:// links each time it starts), otherwise the host's web page; phones go straight to the web page. If KASTR is set to another relay it asks "Switch to <relay>?" first.
- **Room settings ▸ Invite links** (right-click the room, creator or admin) lists the links — who made each, when it ends, how many people joined — with **Revoke** and **Revoke all**. A revoked or expired link is refused at once on every relay of the fleet; people already in the room stay.
- Invited people join as members who can share, never as admins; kicks and bans still apply; a wrong link counts towards the wrong-code lockout. Links are made and checked on the hub (a spoke refuses new joins by link while the hub is unreachable). The Lobby and personal rooms have no invite links.
- **Lab check:** a link made on the hub and one made on a spoke each let a second browser join with only a name; Revoke turned a third browser away; an expired link was refused; with the hub stopped the spoke said so, and worked again when the hub came back.

**My room (Kenton: "everyone gets a personal room no other user sees, where they set up their own views of feeds from other rooms"; kept on the hub so it follows you; your name + a personal code).** **More ▸ My room…** makes yours (pick a personal code, entered twice) or opens it on another device (name + code, entered once — the device remembers). It is the first card in your rooms list.
- Nobody else sees it: it is in no list, and while you are in it KASTR announces nothing (no presence, no room entry). Getting in needs your personal code; an admin can reset a forgotten one.
- Pin cameras from other rooms into it (**Pin to My room** on any tile or grid), spotlight them, arrange its grids and build cross-room grids there — all of it is stored on the hub, so it looks the same on every device you open it on.
- **Lab check:** pins and a spotlight set on the hub showed up on a second device on a spoke after name + code; a third person never saw the room and could not get in; with the hub stopped, the spoke refused entry rather than guess.

**Boxes that share without being in a room (Kenton chose: "Show in rooms…" per camera).** A Publisher or Publisher + relay box's join page has **No room — this box only shares its cameras into the rooms I pick**. The box then sits in a hidden room of its own (in no one's list, and nobody can make a room with such a name) and each camera row has **Show in rooms…** — pick any rooms (several per camera, a code for a locked room).
- The cameras show in exactly those rooms — no box tile, labelled with the camera's name — and can be spotlit, pinned and used in grids like any shared camera.
- The box's KASTR keeps them listed itself: they stay with the window closed and come back after a restart. A room that refuses (a wrong code, a kick) says why on the camera's row. A box already in a real room keeps working as before and gets the same per-camera rooms on top.
- A grid composite can be shown in other rooms from its header the same way (while the box's window is open).
- **Lab check:** camera 1 into rooms A and B, camera 2 into B — viewers saw exactly those, with no box tile and no hidden room in their lists; they stayed listed 200 s after the box window closed, and came back after the box restarted.

**Hide a camera in my grid view (Kenton: "hide individual cameras in my grid view").** Right-click a grid cell ▸ **Hide <camera> for me**: the rest of the grid closes up around the gap, only for you, on this device. **Show hidden cameras (n)…** brings them back. It works on box grids (also in **Arrange this grid for me**, which can now remove and add back) and on cross-room grids; the hidden camera's own tile also leaves your rail.
- **Lab check:** a viewer hid one of four cameras — the other three reflowed and clicks opened the right cameras; the other viewer still saw all four; it stayed hidden after a reload.

**Fixed on the way:**
- A camera that a box shows in another room (or one pinned in My room) wakes up when someone opens it there, even after it went to sleep with nobody watching (0.21.73 stops a converted camera's encode a minute after its last viewer). **Lab check:** with the box's cameras asleep and its window closed, opening one showed a picture within 5–13 s in 15 of 15 tries, on the hub and on a spoke.
- A tile stuck on "connecting…" because no picture had arrived yet never got its re-subscribe (it was skipped while the tile showed the person's face). It now does — this could also leave a grid camera stuck after a slow start.

## v0.21.74 — a box keeps its window drawing and in its room

**A box looks after its own window (Kenton: Mendon's grid "split into separate streams" and its room lost the play icon after a weekend alone; relaunching KASTR on Mendon fixed it).** A camera box's cameras are published by KASTR itself, so they stayed on the air — but the grid and the room's "on air" marks come from the box's window, and that window had stopped doing its job. Now, on a box (Publisher or Publisher + relay mode), KASTR watches its own window and reopens it when:
- its page has not reported for 3 minutes while the browser still runs (a frozen or crashed page), or never reported after the window opened;
- or its page has been out of the box's room for 5 minutes.
- It reopens at most once every 10 minutes, and gives up after three tries in a row that do not get the box back into its room (launch.log says so). A box someone took out of its room with **Leave** is left alone.
- **Lab check:** a test box's page was frozen; 181 s later KASTR reopened the window, the new page rejoined its room, and KASTR kept running (and closed that window when it was told to quit).

## v0.21.73 — encode only while watched, pause sharing, remote Restart and Move, admins can do what publishers do, no more corner zooms

**Encode only while watched (Kenton, Mendon's CPU with Pass through off: "encode only while watched" — he chose: only the cameras the box transcodes).** A grid camera that its box re-encodes (Pass through off, or a camera that cannot pass through) now stops encoding a minute after the last viewer closes it, and starts again when anyone opens it.
- **The grid itself is unaffected:** it keeps drawing from each camera's preview feed, so every cell stays live. Only the full-quality copy of a camera nobody has open is stopped.
- **Opening a sleeping camera:** the click asks for it (from any relay of the fleet — the request travels through the hub to the box that has it). In the lab the box restarted the encode 0.3 s after a click made on the hub, then the camera's tile opened as usual; the grid cell fills the stage meanwhile with "full quality starting…".
- **Pass-through cameras stay on all the time:** copying a camera costs next to nothing, and they keep opening at once.
- **The box's Share ▸ RTSP rows** say "asleep — encodes only while watched" or "encoding while watched", and an asleep camera is never counted as down or restarted.
- A recorded camera stays awake. `sleep_unwatched = off` in kastr.ini keeps every camera encoding always.
- Viewers need 0.21.73 for the click to wake a sleeping camera (they follow their relay's version).

**Restart a user's KASTR remotely (Kenton: "the ability to restart a client KASTR remotely through the fed hub or the relay they are connected to").** The Relay page's **Users** table has a **Restart** button on every app and box that checks in — on the hub for anyone in the federation, or on the relay the person uses.
- The request reaches their KASTR at its next check-in (within a minute). Their window shows "An admin is restarting KASTR — it closes and reopens in 10 s. You'll be back in <room>.", then KASTR restarts and rejoins that room with the microphone and camera as they were. A box with no window restarts at once.
- The row spins until the KASTR checks in again with a new start time, then shows **✓ restarted** (or **didn't restart** after 5 minutes, with the reason under the table).

**Move a user to another relay (Kenton: "the ability to force a client to move to a different relay"; he chose: this session only).** **Move…** opens a list of the fleet's relays (this one and each spoke, with their addresses) or takes a typed address.
- The person's window shows a 10-second notice, then KASTR restarts on the chosen relay and rejoins the room it was in; "nearest relay" does not move it back during that run.
- The move lasts until they close KASTR — the next launch picks its relay as usual.
- The row shows **✓ moved to <relay>** once the KASTR checks in from there.

**Pause sharing, and share something else without stopping (Kenton: "I would like a pause share button, so I don't have to stop all streaming before resharing" — he chose both).**
- **Pause sharing / Resume sharing:** a new amber button next to **Stop sharing** at the top, in your share tile's menu and in the floating mini window. While paused, everyone sees a dark "paused" card in the share's place and hears nothing from it; the share keeps its tile, its spotlight and any pins, so **Resume** carries on right where it was. Your own thumbnail says "Paused — viewers see a pause card". It works for screens, windows and tabs, presenter mode, and browser shares.
- **Share something else…:** in the share tile's menu and the mini window. The Share panel opens with "Pick what to share instead of …"; the screen, window or tab you pick replaces the current share in place — same tile, spotlight and pins, the red border moves to the new window, nothing stops. A browser share asks the browser's picker again and swaps over.
- **Lab check:** a shared test window paused in 0.5 s (the same stream switched to the card and kept flowing), resumed, then switched to a second test window: still one share, same stream name, the preview showed the new window.
- **Fixed on the way:** **Stop sharing** on the red border's bar now ends the share in the KASTR window too — before, the "You're sharing" thumbnail and the mini window stayed behind.

**Admins can do everything a publisher can (Kenton: "Admin needs to be able to do the same functions as a publisher in addition to admin").** The admin access code already shared, published and joined like a publisher, but locking a room, keeping a room open and changing a room's code were checked against the publisher code only — an admin got "Only the publisher access code can lock a room or keep it open", and each try counted towards the wrong-code lockout. The admin code (this relay's, or the hub's on a spoke) now does all three.

**Cameras that open zoomed into a corner (Kenton: "some users that will click on video in Southridge and it will zoom to the top left 1/9 of the camera. It happens on some but not all cameras" — he has not seen it himself).** Two causes, both fixed:
- **A cell zoom that lost its place.** Clicking a grid cell fills the stage with that cell while the camera opens. The grid comes in two sizes (small for small windows and slow links, full otherwise), and the zoom remembered its position in the small picture's pixels: when the full-size grid arrived during the wait, the zoom landed in the grid's top-left corner, roughly the top-left ninth. It now keeps the same spot when the picture changes size. This depended on window size, screen scaling and link speed, which is why only some users saw it.
- **An old copy of the player kept in the browser.** The 0.21.63 fix for 4K HEVC cameras opening zoomed into their top-left corner changed a player file without renaming it, and KASTR served its files without telling the browser to check for a newer copy, so a machine that had the old file could keep using it after updating (only the 4K HEVC cameras were affected). KASTR now makes the browser check every file each time (an unchanged file costs a tiny "not modified" answer).
- **Lab check:** the player file now comes with "check for a newer copy" and an unchanged one answers "not modified".

**Offline users are hidden until you ask (Kenton: "In the user section, I would like a toggle to view offline in addition to online, and have this off by default").** The Users table shows who is online. A **Show offline users (N)** switch below the heading adds the 30-day history; it is off by default and remembered on that machine. It replaces the "not seen for over 24 hours" checkbox and is hidden when nobody is offline.

## v0.21.72 — camera previews with effects, more themes, a mirrored self view, sideways phones

**Camera preview with the camera off (Kenton: "In the video options, show a preview of the camera even if the camera is not enabled in the room.").** The **Video effects and settings** panel showed "No camera" unless your camera was on in the room. Now, with the camera off, the panel opens the camera you picked just for itself and shows it through the background you've chosen. You can try backgrounds, blur strength and the other effects before anyone sees you.
- Nothing is sent: the preview runs on its own, so the room still sees your camera as off.
- It follows the background you click and the camera you pick. When you close the panel the camera is released; when you turn the camera on in the room, the panel shows the live camera again.
- **The join page too (Kenton: "Any preview window, like here and on the join page should have the live video feed with the effects, so you can see your video prior to sharing.").** Turning the camera on on the join page now shows it with your background, so you see what the room will see before you join. While you're on the join page, the panel shows that same picture.
- **Lab check:** on the join page with ASI navy saved, turning the camera on showed it over navy, and turning it off released it. Kenton then joined with the camera off and opened the panel. The preview showed the camera, took on the ASI navy background when he clicked it, and went back to the plain camera on **Off**. Alex's tile for Kenton's camera received 0 bytes before and during the preview. Closing the panel stopped it.

**Your initials and the compass stay default (Kenton: "I don't want my initials to match the selected color, just leave it default. Same with the compass icon.").** With the camera off, your own tile used to tint your initials with your profile colour, and the ASI compass behind them took your accent colour. Your initials are now white, like everyone else's, and the compass is always ASI blue. Your colour still shows as the ring around your picture.
- **Lab check:** with a yellow accent, Kenton's own tile showed white initials over the blue compass.

**More themes (Kenton: "I would like more theme options other than light/dark/system").** **More ▸ Theme** (it was Appearance) now shows a small picture of each theme to click. Kenton chose named themes, High contrast and Custom:
- **System:** ASI Navy or Light, following the device's setting.
- **ASI Navy:** the dark look KASTR has always had, and still the default.
- **Midnight:** near-black, for dark rooms and OLED screens.
- **Slate:** a neutral dark grey with no blue tint.
- **Light** (as before) and **Warm light:** paper tones instead of cool grey.
- **High contrast:** pure black and white, white outlines, slightly bolder text, a thick white focus ring and brighter status colours. Easy to read on a projector or with low vision.
- **Custom:** choose the background, panel and text colours yourself. KASTR works out the lines and dimmer text from those three and decides on its own whether the theme is light or dark. **Reset** goes back to ASI Navy.
- Every theme applies to every KASTR page on the device, including the Relay page and the start page, before the page first appears. **Accent colour** still works on top of any theme, and the video stage keeps its dark ground in the light themes.
- The theme, your custom colours and your accent colour are now kept with the app's other settings, so they survive a browser profile reset.
- **Lab check:** each theme set the expected page colours, a custom set survived a reload (applied before the first paint), and the menu showed all eight with Custom's three colour pickers.

**Your own view is mirrored (Kenton: "On the cameras set the default to mirror" — he chose: only my own view).** Your own camera tile, the camera preview in Video effects and the join page's preview now show you mirrored, like a mirror, so moving and pointing feel natural. Everyone else still sees you the right way round, so writing on a whiteboard or a shirt reads correctly.
- **Video effects** has two switches now: **Mirror my own view** (on unless you turn it off; only you see it) and **Mirror for everyone** (the old **Mirror**, off by default; it flips the picture you send).

**No "Searching for live broadcasts…" in the Lobby (Kenton: "On the lobby page I don't need to be searching for broadcasts").** Nothing plays in the Lobby, which only lists the rooms, so the empty-stage message stays hidden there.

**A sideways phone looks like the desktop app (Kenton, iPhone landscape: "It should be more like the desktop app when in landscape mode and have the video on the left and the rail on the right").** Held sideways, a phone used to drop the rail and stack everything in one narrow column. It now uses the desktop layout: the stage on the left and the rail on the right, at no more than about a quarter of the width, two tiles across when it's busy, with page arrows when there are more. Several spotlit or pinned items share the stage in a grid, as on the desktop. An upright phone keeps its layout (the stage on top, the thumbnail strip under it).
- **Lab check:** at 844 × 390 (an iPhone on its side), speaker view showed the stage on the left (497 px wide) and the other three cameras plus Kenton two-up in the rail. Four pinned cameras made a 2 × 2 grid on the left with Kenton in the rail.

## v0.21.71 — your backgrounds built in, a new picker, no flash of the room

**No flash of your real room when the camera starts (Kenton: "When sharing the camera, it takes about 1 second for the background video to show up and hide the actual background.").** Until a picture, GIF or video background had loaded, the background effect drew you over a blur of your real room. With a video background that was about a second each time the camera came on.
- While a background loads, its thumbnail stands in behind you; a background without a thumbnail gets a plain dark fill. Your room never shows.
- The video background you've chosen is loaded as soon as KASTR opens, then waits paused with no decoding until the camera starts. It stays loaded when the camera goes off, so turning it on again starts on the background at once.
- **Lab check:** a camera with the News room video behind it, watched from another page, with the background video made to arrive 2 seconds late. Before the fix, viewers saw the camera's real picture for 0.2–1.7 s on each start. After it, zero frames of it, even with the video 8 seconds late.

**Fourteen ASI backgrounds built in (Kenton: "I would like to build these videos and backgrounds into the video background options.").** From the shared Backgrounds folder, seven pictures (Elgato lights, Gray home office, Light blue home office, Living room at night, Office space, Porch sunset, Room in the morning) and seven moving backgrounds (Clock, Coffee shop, Lo-fi bedroom, News room, Office, Rainy window, The view). They sit right after the two colour presets.
- The videos are re-encoded to 1280×720 WebM: the camera never sends more than 720p, and all 14 add 5.6 MB instead of 48 MB, with no visible difference.

**A new background picker (Kenton: "I would like to also update the video selector menu to look more like this", with an Elgato Camera Hub screenshot).**
- Thumbnails only (the name shows on hover), 16:9, four across. **Off** and **Blur** come first as labelled tiles, moving backgrounds carry a small camera badge, and the choice is outlined in your accent colour.
- 16 to a page with **‹ 1 2 ›** below the grid. The picker opens on the page of your current background.
- **Add ▾** at the bottom right: **Add** picks a picture, and the arrow offers **Picture…** or **GIF or video…**. The two "+ Add" tiles are gone. Your own backgrounds still have their ✕ on hover.
- **Blur strength** (1–100%) under the grid: the slider and the % box agree, and the camera follows within a fraction of a second. 50% is the blur KASTR has always used. It's greyed out unless **Blur** is the background.
- **Lab check:** the picker showed two pages (Off, Blur, the presets and the new backgrounds first). Choosing Blur enabled Blur strength; 90% was saved and reached the camera. The Add arrow listed Picture… and GIF or video….

## v0.21.70 — room rail fixes and Create room options

**The room group's menu button is on its group's row (Kenton: "The group settings button is in a weird spot and doesn't make sense.").** The group's ⋮ button accidentally used the same style as a grid's pop-up menu, which pins itself to the top-right corner. It floated over whichever room card was at the top of the list, with nothing tying it to its group.
- It now sits at the right end of the group's own row, beside the room count. It is the same **⋯** used on room cards and appears when you hover the row (always shown on touch screens).
- **Right-click a group row** to open the same menu: Collapse / Expand, Rename…, Ungroup all, Delete group….
- Admins see it as well as the relay operator, matching 0.21.68's admin room groups.
- **Lab check:** a group in the rooms rail. The ⋯ sat on the group's row beside its count, and right-clicking the row listed Collapse, Rename…, Ungroup all and Delete group….

**Create room has the Room settings options (Kenton: "When creating a room, give it the same options of the room settings from an admin.").** Besides the name, the room code and **Keep room open**, the Create room form now has **Lock the view** and a **Group** list (with **New group…** for admins). Both are applied the moment the room exists, through the same path as Room settings. If one can't be saved, a message says so and points to Room settings.
- **Lab check:** a room created with Lock the view on and a group picked came up on the hub with its view locked and filed under that group, and the page joined it.

**One pop-up per room on hover (Kenton: "On hover, I get 2 separate pop-ups. It should only be the back one.").** The round room bubbles also carried a browser tooltip ("sr-rm-1 — 1 here (always open)") that appeared on top of the collapsed rail's hover card. It's gone; the same text stays for screen readers.

**The right-click menu isn't covered by the hover card any more (Kenton: "When I hover and right click, the right click menu is partially hidden. It shouldn't show the hover menu once right-clicked.").** A right-click closed the hover card, but it also focused the room, and the focus (or the next small mouse move) opened the card again over the menu. Now any click on a room, right-click included, keeps its hover card away until the pointer leaves that room.
- **Lab check:** collapsed rail. Hover showed the card; a right-click showed the menu alone, still alone after a small move; moving to another room and back brought the card back.

**Room switches are timed (Kenton: "Sometimes it takes a while to switch between rooms.").** Each switch now records three steps: getting the new room's token from the relay host, reconnecting, and the first video tile of the new room appearing. The last 10 switches are in the app's diagnostics (`/api/diag`, `switches`), and one that takes more than 4 seconds to show a tile is also written to launch.log. The next slow switch will say which step was slow.
- **Lab check:** eight switches between two rooms whose cameras come from two different spokes, watched from the hub: the token in about 35 ms, the reconnect in about 40 ms, the first tile in 0.55–0.65 s every time. So the slow cases in the field come from outside the page (most likely the relay host's token service or the camera's path across sites), and the timings will show which.

## v0.21.69 — real machine names on the Relay page

**The Users table shows each computer's own name (Kenton: "For the machine name in the user section, can we pull the hostname of the device instead? Or what are the options?").** Kenton chose all four:
- **Hostname:** the **Machine** column shows the computer's hostname as the operating system has it (`DESKTOP-TC5VJIB`, `mobius-moq`). Before, it showed KASTR's internal machine ID (`desktop-tc5vjib-27a6`), which is now in the tooltip. Apps report their hostname from 0.21.69; an older app keeps showing its ID until it updates.
- **Signed-in user:** beside the hostname, dimmed, the operating-system account running KASTR, to tell people apart on a shared computer.
- **IP:** the address each machine connects from has its own column, which you can sort by.
- **Nickname:** on the hub's own Relay page, hover a machine and click ✎ to give it a nickname ("Support laptop (truck 3)"). The nickname then replaces the hostname, which stays beside it. An empty nickname goes back to the hostname. Nicknames are kept on the hub with the 30-day history, so they survive restarts and upgrades.
- Web visitors still show their browser ("Chrome on Windows").
- **Also fixed:** 0.21.68 saved `kastr_relay.py` with Windows line endings. It is back to Unix line endings. Nothing changes when it runs.
- **Lab check:** an app check-in carrying a hostname and user showed as `DESKTOP-TC5VJIB · support` with its IP in the new column. After a nickname it showed "Support laptop (truck 3)" with the hostname and user beside it, and the nickname, hostname and user were all still there after the hub restarted.

## v0.21.68 — room groups for admins, 30 days of users, readable accent text

**Text on your accent colour is always readable (Kenton: "The 'You're Here' pill is difficult to see with certain colors.").** With a light accent such as yellow, the white text on the **You're here** pill and on your room's bubble disappeared. Text on the accent colour, there and on every accent button and badge, is now black or white, whichever contrasts more with the accent you picked. The default ASI blue gets dark text (6.2:1 instead of 3:1 for white).
- **Lab check:** yellow (#e5ff00) and ASI blue gave dark text; navy and red gave white; after a reload the colour was right from the first paint.

**Joining a room survives a dropped connection (Kenton: "Could not join aoz-6: Failed to fetch" — it joined on a later try).** Changing rooms asks the relay host's KASTR for the new room's token in one request. If that request never got an answer (the host restarting for an update, a dropped connection), the switch failed at once with "Failed to fetch". It is now tried again twice, 1.5 and 3 seconds apart. A refusal (a wrong or missing room code) is still reported straight away. If the host stays silent, the message now says the relay host's KASTR did not answer and to try again in a moment.
- **Lab check:** with the token request made to fail twice, the room switch went through on the third try (about 6 s). With it failing every time, the page stayed in its room after three tries.

**Admins can create room groups from any desk (Kenton: "I'm not able to group the rooms because I can't create a group name.").** Creating, renaming and deleting a room group used to work only from a KASTR running on the relay box itself. From any other computer the **New group…** choice never appeared, so there was no way to name a group.
- Anyone who joined with the **admin code** can now create, rename and delete groups and file any room under one, from any computer. On a spoke, the request goes to the hub with the admin's proof, as Room settings already does.
- **Room settings ▸ Group** has a **New group…** choice. It asks for the name, creates the group and files the room under it in one step.
- Group names are typed into KASTR's own dialog instead of the browser's prompt box.
- Without the admin code, nothing changes: a room's creator can still put their room into an existing group.
- **Lab check:** a page on the hub that, like your desk, isn't the relay box. With the publisher code, no **New group…**. With the admin code, **Room settings ▸ Group ▸ New group…** asked for a name; the hub created the group and the room was filed under it ("Moved to …").

**Relay page Users keeps 30 days of history, through restarts and upgrades (Kenton: "The user section should store any past users persistent through reboots/upgrades. Keeping a full history of all devices that have connected in the past 30 days.").** Before, the Users table only knew who was connected right now (and whatever a spoke last reported), so a restart or an upgrade of the hub emptied it.
- The hub now remembers every device it hears about: its own apps' check-ins, every spoke's users and live sessions. Each is kept with its name, machine, kind, relay, last KASTR version, when it was first seen and when it was last seen. The list is saved in `relay-users.json` next to the hub's other state, at most a minute after a change and when KASTR closes. A device not seen for 30 days is dropped.
- **The table:** people connected now as before, then everyone else from the last 30 days, dimmed, with **Last seen** and a hover note saying when they were first seen. Offline rows never get an Update button and aren't counted by **Update all users**. The header adds "· N offline (last 30 days)". Rows older than 24 hours still sit behind the **Show users not seen for over 24 hours** checkbox.
- **Lab check:** two past users were saved on the lab hub, which was then restarted with nobody connected. The Users header read "0 users … · 2 offline (last 30 days)". The user seen 3 hours ago showed dimmed with no Update button; the one seen 4 days ago was behind the 24-hour checkbox, which showed "(1)".

**Relay page Users: no empty checkbox line (Kenton: "If there are no users to show, don't show the line with the checkbox.").** The **Show users not seen for over 24 hours** checkbox appears only when at least one user is that old, and it says how many. With everyone recent, the line is gone.
- **Lab check:** two recent users: no line. One of them last seen 3 days ago: the line came back as "(1)".

**Pull test text without colour codes.** When a Pull test gets no data, the Relay page shows the moq tool's last line. That line was full of terminal colour codes (`[2m`, `[0m`, …); they are removed now, so it reads "subscribe started" plainly.

## v0.21.67 — your room stands out

**Your room looks different from rooms you watch (Kenton: "We need a way to show which room I'm in and it needs to be different than how it shows what rooms I'm pulling feeds from.").** Before, both had a blue outline and a blue ring; the watched one was just dimmer.
- **The room you are in:** the card is tinted in your accent colour, its round bubble is filled solid with white initials, and a **You're here** tag sits beside the people count.
- **A room you pull feeds from:** no fill, a dashed outline, a dashed ring around the bubble with a small eye under it, and a **Watching** tag.
- **Collapsed rail:** the bubble says it on its own: solid for your room, dashed ring and eye for a watched one.
- **Lab check:** Kenton in one room, watching a camera in another, in dark and light themes and with the rail collapsed. The two read differently at a glance in every case.

**The Relay page's Pull test shows its result (Kenton: "I saw the button, but I can't find where the pull goes to").** The stream list on the Relay page refreshes every 5 seconds and was rebuilt from scratch each time. That wiped the "pulling… (15 s)" note and the result beside the button before anyone could read them, since a pull takes 15 seconds. The note and the result now stay on the stream's row through every refresh. You see "pulling… (15 s)", then "first byte 0.58 s · 1.21 Mbit/s" (green) or "no data in 15 s" (amber). Hover over the result to see when it ran. The pulled video itself goes nowhere: the relay box reads the stream through its own relay for 15 seconds, counts the bytes and discards them.
- **Lab check:** on the lab hub's Relay page, a Pull test on a camera shared from the spoke. "pulling…" stayed through two refreshes, and the result showed after 15 seconds and was still there three refreshes later.

## v0.21.66 — spotlight you can arrange, grids from any room

**Drag the spotlight around (Kenton: "I want to be able to adjust spotlighted items after they are spotlighted by dragging them around.").** When two or more things are spotlit and share the stage, drag one onto another and they swap places.
- A see-through copy of the tile follows the pointer, and the tile you would drop on is outlined in blue. A click without moving is still a plain click.
- The new order is saved on the room board, so **everyone in the room sees the same arrangement**, and it stays after the person who arranged it leaves. New spotlights go after the arranged ones, oldest first, as before.
- Who can drag: anyone who can change the room board (the publisher code). In a room whose view is locked, only its creator or an admin; for everyone else the tiles simply don't drag.
- Your own pins (two or more pinned for you) can be dragged the same way; that order is only yours, on this device.
- **Lab check:** two cameras spotlit in a hub room. Kenton dragged the first onto the second with the mouse: the see-through copy and the blue outline showed, both his stage and Alex's swapped within about a second, and the order stayed for Alex after Kenton left the room. A click without moving behaved as before.

**Back to spotlight (Kenton: "I want a shortcut to go straight back to the spotlight view and not have to go through the gallery.").** Whenever the room has a spotlight (or you have pins) and your stage isn't showing it — the gallery, another tile you clicked, a camera opened from a grid — a small **Back to spotlight** button sits at the top-left of the stage. It doesn't fade away with the other controls, because it may be the only way back. **S** on the keyboard does the same (not while typing). It puts back exactly the spotlight view: the shared stage for several items, or the single item. Added to Help's keyboard shortcuts.
- **Lab check:** from the gallery the button showed and one click brought back both spotlit cameras side by side; from another camera on the stage, S did the same.

**Your own grid of cameras from any room (Kenton: "I also need to be able to create my own grid with several streams across multiple rooms.").** **More ▸ Build a grid…** opens the grid builder over a new grid tile.
- **The camera list has every stream you can see:** your room's tiles, every source of the rooms you watch (ticked or not) and streams listed into your room. Drag them onto spots, use the presets (1 to 26), put several cameras in one spot to take turns on **Time** or **Motion** (KASTR's own motion detection, from each camera's own picture), and give it a name ("Kenton's View" to start with).
- **Yours or the room's:** with **Share with this room** off, the grid is only yours, on this device, in whatever room you are in. With it on, it goes on the room board: everyone in the room sees it, and it stays when you leave. Up to 8 grids each way, 32 spots, 8 cameras per spot.
- **One tile:** the grid shows as one tile on the stage, in the rail and in the gallery. Pin it for yourself; a room's grid can also be spotlit for everyone and pinned to the room like any tile.
- **Each viewer draws it:** no box puts it together. Each person's KASTR draws every spot from that camera's own stream. While the grid is on screen, its cameras keep playing in the background, using a camera's small copy when it has one.
- **The trade-off for cycling spots:** a spot that changes on **Time** plays only the camera it shows, plus the next one for its last 4 seconds so the switch isn't black. A spot that changes on **Motion** keeps all of its cameras playing, because motion is measured on each camera's own picture. That uses more data, in exchange for switching the moment something moves.
- **Click a spot** to open that camera at full quality; click it again to go back to the grid.
- **Cameras only in a grid stay out of the way:** a camera that is there only for a grid (an unticked source of a watched room, or another room's camera in a room grid) gets no tile of its own in the gallery or the rail, and is silent.
- **Another room's camera in a room grid:** saving one needs your access to that room (the same proof as pinning it to the room). After that, everyone in your room can see it inside the grid, including people who don't watch that room. In a locked room, only an admin can add its cameras, unless they are your own.
- **The grid tile's ⋯ menu:** **Edit grid…**, **Rename…**, **Share with this room** / **Keep only for me**, **Delete grid**. A room's grid follows the view lock like everything else on the board.
- **Lab check:** a hub room and a spoke room. Kenton (who watches the spoke room) built **Kenton's View** with only the mouse: one camera from his room, two spoke-room cameras that switch on motion (they move at different times) and two that switch every 4 seconds. Over 22 seconds every spot showed a picture, the motion spot followed whichever camera moved, and the time spot switched on schedule. Clicking a spot opened that camera; clicking again went back. A second grid shared with the room reached Alex, who doesn't watch the spoke room. It drew the spoke-room camera with no tile of its own, and stayed after Kenton left.

**Arrange a grid from another room in your room (Kenton: "When I right click on this grid from another room that is viewing it, I can't adjust the grid in that room. I need to be able to do that.").** A camera grid from another room that is pinned to or listed in your room now gets the same tools as your room's own grids: **Arrange this grid for me…**, **Arrange for everyone in this room…** (the builder, with presets, drag and drop and cycling spots), **Remove … from this room's grid**, **Show … on its own in this room**, **Add back** and **Reset to the box's layout**.
- It all lives on **your** room's board and only changes how your room sees the grid. The box, and the grid's own room, are untouched.
- Before, these tools worked only for people who also watched the grid's room, because only they knew which camera sat in which cell. Now the box that owns the grid posts that layout to the hub, and everyone in a room where the grid is pinned or listed gets it, whether they watch that room or not. The box needs 0.21.66 for this.
- A camera you show on its own is shared into your room for everyone, the same way a pin is.
- **Also fixed:** a second stream listed or pinned into a room from the same other room (a second pin, a room grid's camera, a camera shown on its own) used to wait on "connecting" until the page reconnected. It now plays straight away.
- **Lab check:** a 7-camera grid from the spoke room, pinned into the hub room. Alex, who doesn't watch the spoke room, got the arrange tools in its menu. Kenton removed one camera, showed another on its own and set a 4-spot room layout. Alex saw all three, the grid and the split camera both played, and Alex could add the removed camera back himself. The spoke room's own board was unchanged.

**The grid editor no longer covers the grid (Kenton: "The grid layout options are put right on top of the grid so I can't see it all to adjust properly.").** While any grid editor is open (the box's **Edit layout…**, **Arrange this grid for me…**, **Arrange for everyone…**, and the new grid builder), the grid shrinks to fit below the toolbar and beside the camera list. Every spot, its ✕ and its resize corner stay visible and can be grabbed. This also holds when the toolbar wraps onto two lines on a narrow window. Done or Cancel gives the grid its full size back.
- **Lab check:** a box's 7-camera grid at 1400 × 900 and 1100 × 800 (where the toolbar wraps to two lines): every spot's ✕ and resize corner was the topmost thing under the pointer, and neither the toolbar nor the list overlapped the grid.

**No white bar on your room in the rooms list (Kenton: "No longer a need for the White bar on the side with the area highlighted.").** The white bar down the left edge of your room's card, and the one beside its bubble when the list is collapsed, are gone. The blue outline and the blue ring around the bubble now show which room you are in, in both light and dark themes. The card's spacing is even.

**Room details on hover when the rooms list is collapsed (Kenton: "On hover of the collapsed room view, show the info for the room similar to the expanded view.").** Pointing at a room's bubble (or moving to it with Tab) opens a small card beside it after a moment. It shows the same details as the expanded list: name, number of people, time, the lock / keep-open / video badges, and the people in the room (A to Z, with the publisher and view-only marks, speaking rings, deafened mark and "just joined" icon). The Lobby still shows no names. The card stays up to date while it is open. Clicking it works like the expanded card: it joins or switches rooms, and a person's ⋯ opens their menu. It closes when the pointer leaves both the bubble and the card. Phones and tablets keep opening the full list instead.
- **Lab check:** hovering over a collapsed room bubble opened the card with the room's three people and its timer, and moving away closed it.

**Clicking a camera in a grid no longer makes the grid disappear (Kenton, Mendon: "when I click on any of the videos other than the first 2 the grid is crashing ... The grid window disappears. It doesn't come back until I refresh the page or leave the room and come back.").** The cameras that did this were ones turned off for watching on that computer. A camera's watch switch is remembered on each device, and unticking one in a room's source list does the same thing. Clicking such a camera's cell asked the stage to show a camera this page wasn't playing. The grid stepped aside for it as usual, so the stage was left empty.
- Clicking a cell now turns that camera back on for watching (the click is the ask) and opens it at full quality like any other cell.
- As a safety net, if the camera open on your stage can't be shown (turned off, gone down, or removed from this room's grid), the stage goes back to its grid instead of going blank.
- **Lab check:** a 7-camera grid shared from the spoke, watched from the hub, with two of its cameras turned off for watching. Before the fix, clicking either of them left an empty stage with the grid hidden, exactly as at Mendon. After it, all seven cells opened their camera. A camera that went down while open on the stage handed the stage back to its grid within a few seconds.

**A grid whose cameras are all offline is hidden (Kenton, on an RTMP grid stuck on "cameras offline — reconnecting (3)": "It should hide it").** When every camera in a grid is offline, viewers no longer see the "cameras offline" placeholder. The grid leaves the gallery, the rail and the stage, like a share that ends, and the stage moves on to the next thing. The box keeps the grid running, and the moment one camera is live again the grid comes back. If it was on your stage and you hadn't picked something else meanwhile, it goes back there; the gallery stays the gallery. It stays visible while you have its layout editor open.
- **Lab check:** a 3-camera grid on a viewer's stage. All three were knocked offline: the grid left the stage and the gallery. One came back: the grid returned to the stage. In the gallery it hid and returned the same way, and the viewer stayed in the gallery.

**Noise removal (RNNoise) no longer silences you with a Bluetooth headset (Kenton: "When I turned on RNNoise filter no one could hear me at all." — a Bluetooth headset, switched on mid-call, no error).** Turning the microphone on makes Windows move a Bluetooth headset to its call mode, which removes its speaker output and adds it back. The noise filter's audio engine was tied to that output, so it could stop and pass on silence without reporting an error.
- The filter's audio engine is no longer tied to any output device, so a headset changing modes can't stop it.
- A watchdog checks it every second. If its clock stops, or your microphone has sound while the filter puts out silence for 3 seconds, it rebuilds the filter once. If that happens again, KASTR switches to the browser's own noise suppression and says why, both on screen and in the log. You are never left silent.
- **Lab check:** a speech recording as Alex's microphone, RNNoise on, Kenton listening. Alex was heard at full level. Then the filter's clock was frozen on purpose. The first time, the watchdog rebuilt the filter and Alex was still heard. The second time, KASTR switched to the browser's suppression with the reason shown, and Alex was still heard.

## v0.21.65 — tidier tiles

**A sound when you deafen and undeafen (Kenton: "Make a noise for yourself when you deafen and another for undeafen ... a different tone than the room enter/exit tone").** Deafening plays a short, low, muffled two-note going down; undeafening plays it going up. Only you hear it, even while deafened. It sounds nothing like the room chime and comes with every way in or out, including turning sound back on with M.

**The mute and camera-off marks always show; the name joins them on hover (Kenton: "Always show the no camera/mic on the left when not mousing over, on hover put the name in the same row as the camera/mic icons but before the icons. This is on the preview rail and the gallery, or any other view.").** Every person's tile now has one small row in its bottom-left corner, in every view: the gallery, the speaker-view rail, the main stage, full screen and phones, for other people's tiles and for your own preview.
- **Mouse not on the tile:** only the marks that apply: camera off first, then mic muted (or the amber headphones when the person is deafened). Nothing at all when the camera and mic are both on. No name and no dark bar across the bottom.
- **Mouse on the tile:** the name, then the same marks right after it, in one row. A long name is cut short with "…" on a narrow tile, so the marks never get pushed off or covered.
- **The marks no longer fade** when the mouse stops moving (before, they showed only in the gallery, or only while the mouse moved). The name still goes away with the other controls about 3 seconds after the mouse stops.
- **Phones and tablets** (no mouse): the name and the marks always show.
- **View-only people:** the eye (and the amber headphones when deafened) always show, with the name before them on hover, the same as everyone else.
- **Unchanged:** RTSP cameras and grids show no mic mark, your screen-share preview shows no marks, a shared file's play bar still sits just above the row, and the ⋯ / fill / full-screen buttons, pins, latency and the talking ring stay where they were.
- **Lab check:** five people in one room (camera off and muted; camera paused and talking; deafened with a long name; view-only; and my own paused, muted camera). Every tile was photographed with and without the mouse over it in the gallery, the rail, a narrow rail and the stage, plus a 390-pixel phone. The marks sat at the bottom-left without the mouse; with it, the name came first and the marks followed in the same row.

**Renamed cameras keep their names for everyone (Kenton: "I renamed the videos, but it doesn't show for other users when not in a grid").** A camera you rename on the sharing computer now shows that name on every viewer's tile, for example "Tremonton Relay — Southeast" instead of "Tremonton Relay — Q8msm2q628iwuelf". A rename reaches everyone within seconds. The sharing computer needs 0.21.65; grids already showed their cells' names.

**"Just joined" in the rooms list (Kenton: "When someone joins a room, show an icon in the left side rail for a few seconds to denote that they are new and just joined").** When someone arrives in any room, a green person-with-a-plus shows beside their name in the rooms list for 8 seconds, then fades. Opening KASTR or changing rooms doesn't light up everyone already there. Someone moving in from another room counts as joining.

**The grid builder: presets up to 26 cameras, drag and drop, and several cameras taking turns in one spot (Kenton: "I would like more preset options in a dropdown for camera views in the grid, instead of just the 1/2 camera big options. ... a method for building the grid with a drag and drop method. This also allows for multiple cameras being set to the same spot on a grid and cycle between the cameras on motion or a time.").** Every grid layout editor is now the builder: the box's own **Edit layout…**, **Arrange this grid for me…** and **Arrange for everyone in this room…**.
- **Presets:** a **Layout** dropdown lists **1 Camera** to **26 Cameras**, each with a small drawing of its pattern and a tick on the one in use. 1, 4, 9, 16 and 25 are equal grids; the others mix one or two big spots (top left) with small ones filling the right and the bottom, like UniFi's Multi-View. The old **Equal / One big / Two big** (and **Side by side / Stacked** on the box) are still there, under "Fit every camera".
- **Spots:** a preset makes that many spots. The cameras keep their order; spare spots say **Drop a camera here**; cameras that don't fit wait in the list.
- **The list:** beside the picture, "N available streams" with a search box, each camera's name and a small live picture, and a tick once it is in the grid. On the box it lists the grid's own cameras; in a room layout, all of the grid's cameras.
- **Drag and drop:** drag a camera from the list onto a spot. Drag one spot onto another to swap them. The ✕ on a camera takes it out of that spot. You can still move a spot, resize it from its corner, add one (**+ Spot**) and set the gap.
- **Several cameras in one spot:** dropping onto a spot that already has a camera asks **Add to this spot (cycle)** or **Replace** (hold Shift while dropping to add straight away). Up to 8 cameras per spot. The spot then shows "N Cameras" and **Cycles on: Motion / Time**:
  - **Time:** the next camera every 10 seconds (you can change the number).
  - **Motion:** the camera with the latest motion shows, and stays on until 15 seconds after its motion stops (you can change the number). If nothing moves, the camera on screen stays.
- **Motion is KASTR's own:** no NVR login. Four times a second KASTR compares a tiny grey copy of each camera in a motion spot with the one before. A change counts after two checks in a row, and the first second after a camera starts is ignored. **Motion: Low / Medium / High** in the toolbar sets how much change counts (Medium by default).
- **Who does the cycling:** for the box's own grid, the box. It draws only the camera whose turn it is, and everyone's cell names and clicks follow it. For a room's layout, each viewer's KASTR cycles it from the grid picture. Room layouts with spots are saved on the room board like before, so everyone in the room sees the same thing (up to 32 spots, 8 cameras per spot).
- **Older KASTRs:** a box layout keeps each spot's first camera in the old format too, so an older box or viewer still draws a sensible grid. Room layouts on a hub that has not been updated stay at 0.21.64 (no spots).
- **Lab check:** a box with four test cameras (two that move for 4 seconds every 30 seconds at different times, one still, one always moving), two viewers in its room and one in another room. Kenton's room layout was built only by dragging: preset "2 Cameras", the two part-time movers in one spot (motion, 5-second hold), the still and moving cameras in the other (time). For Alex the time spot switched every 10 seconds, and the motion spot switched to whichever camera had just moved. The same layout on the box itself cycled the composite the same way, and the viewers' cell names followed within about a second. No page errors.

**Split a camera out of a grid, for this room (Kenton: "split streams out of a grid on the viewing side that I can also pin and spotlight to the room that don't affect the original room/grid that they are in").** Right-click a camera's cell in a grid and choose **Show <camera> on its own in this room**, or use **Show on its own in this room** in the camera's own menu.
- Everyone in the room then sees that camera as its own tile in the rail and the gallery. It can be pinned to the room or spotlighted with the usual menus. Its cell in the grid stays. A split camera never takes over anyone's stage by itself.
- **Back into the grid only** undoes it, for everyone in the room.
- **This room only:** other rooms that watch the same grid, and the box, don't change. It is kept on the room board (it survives everyone leaving), up to 32 cameras per room. Anyone in the room with the publisher code can do it, but not in the Lobby or from a box. The Relay page's **Board** column counts it ("1 split out").
- A camera removed from the room's grid stays removed: removing wins over splitting.
- It needs the camera's own stream, which a box sends unless its grid feeds are set to "Grid only".
- **Lab check:** Kenton split one camera out. Alex saw its own tile within 4 seconds, and spotlighting it put it on Kenton's stage. Bob, in another room watching the same grid, saw no change. **Back into the grid only** hid it again for everyone.
- **The hub must run this version** for spots in room layouts and for split cameras. A spoke on this version whose hub is older says so.

**The rooms list opens and closes from a tab on its own edge (Kenton: "update the hamburger menu icon to be a expand/collapse icon and put it on the edge of the room sidebar window").** The ☰ button at the top left is gone.
- **The tab:** a small arrow tab sits on the right edge of the rooms list, halfway down. It points left while the list is open (click to collapse it to the icon rail) and right while it is collapsed (click to open it). Its tooltip says **Collapse rooms** or **Expand rooms**. It can be reached with Tab and pressed with Enter or Space.
- **Phones:** the rooms list is still a drawer over the page. The same tab sticks out at the left edge of the screen as its handle: tap it to open the drawer, tap it again (or tap outside the drawer) to close it.
- **Lab check:** the tab collapsed and expanded the list by mouse and by keyboard, the arrow turned with it, and on a 390-pixel phone the handle opened the drawer and the shaded area closed it.

**Room settings after the fact (Kenton: "Ability to change room settings after the fact. Only for admin or creator. Right click menu.").** Right-click a room in the rooms list and choose **Room settings…** (the room you are in also has it in **Room info**). It shows only for the room's creator (the computer that created it), an admin (joined with the admin code) and the relay's own computer. Each change applies at once:
- **Name / Rename:** the room gets a new name. Everyone in it moves to the new name by themselves within a few seconds, with their camera and microphone as they were. Its chat history, pinned feeds, spotlights, grid layouts, split cameras, group and cross-room listings go with it. The old name points to the new one for a week, so anyone who comes back late is moved too.
- **Locked with a code:** turn it on and type a code to lock the room, type a new code to change it, or turn it off to unlock it.
- **Keep this room open:** on or off. Off also releases a room that was kept open only because it had pins or spotlights; it then closes 10 minutes after the last person leaves.
- **Group:** move the room into a group or out of it.
- **Lock the view:** see below.
- **Not for the Lobby:** it cannot be renamed, locked or changed.
- **Who may:** the creator proves it with the room's key, which stays on the computer that created it. Someone whose name matches the room's creator, but on another computer, sees the settings greyed out with a note to use that computer or the admin code. Anyone else gets "only the room's creator or an admin can change its settings".
- **The hub keeps rooms:** a change made on a spoke goes to the hub, and every relay shows it. The hub must run this version.
- **Lab check:** Kenton (on the hub) created a room, and Alex (on a spoke) and Bob joined it. Kenton renamed it from Room settings; all three were moved to the new name within 4 seconds, and the hub listed the old name as renamed.

**Lock the view (Kenton: "Ability to lock the view in a room so only an admin/creator can spotlight/change anything" and "Instead of just ignoring other users, hide the options in the locked room").** A switch in Room settings.
- **While it is on, for everyone except the room's creator or an admin:** these items are gone from every menu (tile menus, your own share menus, grid menus, a grid cell's right-click, the rooms list and People): **Spotlight for everyone**, **Remove spotlight**, **Pin to this room** / **Unpin from this room**, **Arrange for everyone in this room…**, **Remove from this room** (and "Remove … from this room's grid"), **Show on its own in this room** / **Back into the grid only**, and **Removed from this room (n) — Add back…**.
- **Still allowed for everyone:** Pin for me, Arrange this grid for me, Mute for me, zoom, and everything that only changes your own screen.
- **A small amber "View locked" badge** shows after the room's name at the top.
- **Safety net:** the hub refuses any change to the room's pins, spotlights or layouts from anyone else ("The view in this room is locked -- only its creator or an admin can change it"), and every KASTR shows only the spotlights the creator or an admin set, so an older KASTR that still offers the button cannot spotlight anything.
- **Lab check:** with the view locked, Bob's menu on Alex's camera showed only Mute, Pin for me and Show latency, while Kenton (the creator) still had Spotlight for everyone and Pin to this room.

**Zoom in on any camera on the main stage (Kenton: "I would like to be able to zoom in on a shared camera").** Any video on the main stage can be zoomed now, people's cameras included (before, only shared screens and camera feeds could).
- **How:** the mouse wheel, two fingers on a touch screen, or the **−** / **+** buttons at the bottom right of the stage. A double-click zooms to 2x and back. Drag to move around while zoomed; a single click shows the whole picture again.
- **The zoom resets** when the tile leaves the stage (another tile takes it, or you go back to the gallery).
- **Grids are unchanged:** a click on a grid's cell still opens that camera, and the grid zooms as before.
- **Fixed on the way:** a double-click on a stage tile used to send the stage back to the gallery on its first click, so the 2x zoom never happened. A single click now waits a moment to see whether a second click follows.
- **Lab check:** Alex's camera on Kenton's stage zoomed to 231% with the wheel, 200% with a double-click, back to 100% with a click, and stepped 150% → 225% → 150% with + and −. Going back to the gallery reset it.

**Several webcams shared at once, from the Share menu (Kenton: "I need to be able to use multiple webcams on a computer at the same time in the sharing menu" and "any cameras shared through the share button to be configured this way ... the Logan-ROC has a webcam for a shared camera, but I had to share it as a camera because it wasn't displaying under the share menu").** **Share** now has a **Webcam** section, under Screen.
- **It lists every camera on this computer** by its own name. **Share** next to a camera shares it as a shared camera: its own tile named after the webcam, which can go in a grid, be spotlit or pinned, and comes back after KASTR restarts. Share as many as the computer has. **Stop** stops one.
- **The toolbar camera is never used for this.** If your toolbar camera is using the same webcam, KASTR asks first, turns the toolbar camera off, then shares the webcam.
- **Linux (like the Logan-ROC):** only the devices that really capture video are listed (a webcam's second "metadata" device and video encoders are left out), with the camera's own name instead of "video0", and by a fixed address, so a re-plug or a restart does not mix two cameras up. A camera KASTR is not allowed to open says why and how to fix it (add the user to the `video` group).
- **Windows:** two webcams with the same name are listed as "Name" and "Name #2", and both can be shared.
- **A browser (the web portal)** sees a short note instead: webcams are shared from the KASTR desktop app on the computer they are plugged into.
- **The old picker** under RTSP/HTTP feed ("Camera on this computer…") is still there and now shows the cameras' names too.
- **Lab check:** the lab computer has no webcam, so the camera list was simulated (a Logitech, a Linux camera KASTR may not open, and KASTR's test pattern standing in for a camera). The section listed all three, the one that cannot be opened said why, and **Share** on the test pattern published it as its own tile that Bob saw on his stage. **Not tested on real hardware:** two physical webcams at once, and the Linux listing on the Logan-ROC itself (it was checked against a simulated set of Linux camera devices).

**Turn off the "change rooms?" question (Kenton: "Give an option in the options menu to toggle on/off the notification when clicking between rooms. Default should be on.").** **More** has **Ask before changing rooms**, on by default, remembered on this computer.
- **Off:** clicking another room in the rooms list moves you there at once, without "Leave X and join Y?".
- **A locked room still asks for its code** either way.
- **Lab check:** with it off, a click on another room moved Kenton there with no question; a locked room still asked for its code; with it back on, the question came back.

**The "…" next to a name in the rooms list only shows when it does something (Kenton: "Viewers on the left people rail have ellipsis next to their name, but don't give any menu when clicked").** The **…** and the right-click menu now appear only for someone who has a camera or a share showing, or, for an admin, someone watching only (to remove them from the room). Someone who only watches shows no **…** to everyone else. The People panel follows the same rule.
- **Lab check:** a person who joined with the viewer code showed no **…** in Kenton's rooms list.

## v0.21.64 — KASTR gets through the web portal's tunnel

**Arrange a camera grid for everyone in the room, and take cameras out of it (Kenton: "I need to be able to customize the grid for everyone in the room to see. I need to be able to remove feeds from that grid as well.").** A grid's layout and the cameras removed from it are now saved on the room's board, on the hub, so they apply to everyone in that room and survive everyone leaving and the box restarting. Kenton chose:
- **Arrange for everyone in this room…:** a new item in a grid tile's menu. It opens the same layout editor as **Arrange this grid for me…** (move, resize, Equal / One big / Two big, the gap). **Done** saves it and says "Grid layout saved for everyone in <room>"; the others see it within about 8 seconds, without reloading.
- **Remove a camera:** each camera in the editor has an ✕ ("Remove from this room's grid"). Right-clicking a cell of the grid offers it too, and a camera's own tile has **Remove from this room**. A removed camera's cell is not drawn, a click never opens it, and its own tile is not shown anywhere in the room (rail, gallery, stage, People) for anyone. The others' cells keep the room's layout, or share the picture in equal cells when the room set no layout.
- **Undo:** the editor lists **Removed (n)** with **Add back** for each camera, and **Reset to the box's layout** drops the room's layout and brings every camera back. The grid menu also shows **Removed from this room (n) — Add back…**.
- **This room only:** nothing is sent to the box, which keeps publishing every camera. Another room that watches the same grid or camera still sees the box's own layout.
- **Who sees what:** if you arranged a grid for yourself, you still see your own arrangement; the menu then offers **Use the room's layout**. Otherwise you see the room's layout, or the box's when the room has none.
- **Who can change it:** anyone in the room who joined with the publisher (or admin) code, as for pins and spotlights. Not in the Lobby, and not from a box. A room with a grid layout is kept open like one with pins. Up to 16 grid layouts per room.
- **Relay page:** the **Board** column counts them, for example "1 pinned · 1 grid layout".
- **Fixed on the way:** a box whose grid used a custom layout could tell viewers its cell positions only after the next layout change, so a viewer's own arrangement cut the wrong parts of the picture. The box now sends them as soon as it draws the grid.
- **Lab check:** a box with three cameras on a spoke; two viewers in its room on the hub, one viewer in another room. One viewer arranged "One big" and removed a camera: the other viewer saw it in under 4 seconds, the spoke's copy of the board matched, and the viewer in the other room still saw the box's layout. Add back, Remove from this room and Reset worked for both, with no page errors.
- **The hub must run this version** for room grid layouts. A spoke on this version whose hub is older says so when you save.

**Update now shows for clients on the web portal (Kenton: "I've been on a desktop client for more than 2 minutes and it doesn't show the button").** The web portal's Cloudflare tunnel refused every request the KASTR app made by itself (HTTP 403, Cloudflare error 1010), because the app identified itself as Python's default client. A desktop KASTR connected through kastr.madlabs.app could therefore never learn the hub's version, so the button never appeared. The same wall blocked its update checks and its other calls to the hub through the tunnel. Every request now identifies itself as KASTR, and Cloudflare lets it through (checked against kastr.madlabs.app).
- **Clients already in the field (0.21.63 and older) still send the old identity.** Update them once by hand, or switch off Cloudflare's Browser Integrity Check for the web portal; then they reach the hub and update themselves.

**Speaking rings in the rooms list (Kenton: "This isn't following the colors that the users set for themselves. Also, the highlighted ring appears to be overlapping with other rings. This ring is also sticking around when the user is muted or not making any noise").**
- **Stuck rings:** the ring now goes the moment the person mutes or goes quiet. It used to stay on after the last person speaking muted, because KASTR's sound meter stopped and the last clear-up was skipped. In the lab it now goes 0.2 s after the mute.
- **Your room:** a name in the room you're in rings only while your KASTR actually hears that person. It no longer also trusts a "speaking" flag from the other person's app, which can lag when their window is minimized. A muted microphone now says "not speaking" at once.
- **Colours:** every ring of a person (their name in the rooms list, their tile, their People entry) is their own colour: the one they picked, or else their automatic colour, the same one as their picture's ring. It used to fall back to your own accent colour.
- **Overlap:** the ring is drawn inside the name's box, and the rows have a little more room, so neighbouring rings no longer run into each other.

**Viewer-code members see what they can't use greyed out (Kenton: "Viewer code users are able to see the share, camera, and mic buttons. But they can't use those").** Someone who joined with the viewer code sees **Share**, **Camera** and **Mic**, and their menus, greyed out. Hovering explains: "Your access code is for watching only — sharing, camera and microphone need the publisher code". Clicking does nothing but repeat that.

**Up-to-date apps no longer show as "older KASTR" without a name (Kenton: "Sometimes devices are showing in here as not up to date and without a name when they are up to date").** An app reports its name and version to its relay every minute. Two things stopped that report, and the hub then showed only that the app was connected:
- **Web portal:** an app reaching the hub through the web portal was refused by Cloudflare (fixed above).
- **Wrong web port:** an app sent its report to the relay's KASTR on the default web port 8000 when it hadn't learned the real one, and Southridge's KASTR doesn't run on 8000. A failed report now makes the app ask the relay for its web port and try again, and the failure is written to the app's launch.log.
- **Label:** a row whose app doesn't report now says **not reporting**, and its tooltip gives the reasons, instead of claiming the app is old.

**RNNoise comes back by itself (Kenton: "I just had an error about the RNNoise filter not being able to connect").** When background noise removal fails to start, KASTR still switches to the browser's own suppression, but now:
- **Retries:** it tries RNNoise once more 30 seconds later, instead of leaving it off for the rest of the session.
- **Recorded:** the reason is written to the app's launch.log and to its diagnostics, so the logs collected at the hub show what failed even without a screenshot.
- **Lab check:** a failed load switched to the browser's suppression and RNNoise came back after 30 s.

## v0.21.63 — the vehicle API, rooms that keep their pins and spotlights, HEVC cameras whole again

**Spotlights and pinned feeds stay with the room (Kenton: "Spotlights are not staying in a room when I add views to a room, spotlight, leave the room, and come back. The spotlights should stay tied to the room." and "When pinning a feed to a room, does it show for everyone?").** Each room now has a board, kept on the hub, that remembers what is pinned to the room and what is spotlit. Before, a spotlight lived only in the room's members' own state, so it disappeared when the person who set it left. Kenton chose:
- **Pin to this room:** a new item in every tile's menu (and in the menus of your own shares and grids). The feed is listed in the room as a tile for everyone, until someone picks **Unpin from this room**. A pinned tile wears a small amber pin in its top-left corner ("Pinned to this room"). **Pin for me** is unchanged and still only changes your own stage.
- **Feeds from other rooms too:** a feed from a room you watch, or one shown in your room from elsewhere, can be pinned. It stays listed even when nobody who shares it is in the room. Pinning a locked room's feed into another room needs that room's admin code, unless it is your own share (the same rule as spotlighting it).
- **Spotlights stay:** **Spotlight for everyone** is now saved on the room's board as well, so the spotlight is still there after the person who set it leaves, and when you leave and come back. **Remove spotlight** takes it off the board. Spotlighting a feed from a room you watch pins it to your room first, so that one stays too.
- **Who can change it:** anyone in the room who joined with the publisher (or admin) code can pin, spotlight and remove. Viewers see the board but cannot change it; their spotlights work as before, for as long as they stay. The Lobby has no board.
- **The room stays open:** a room with anything pinned or spotlit is switched to **Keep room open**, so its setup isn't lost when everyone leaves. Removing the last item doesn't turn Keep off; close the room (its creator, an admin, or **Close** on the hub's Relay page) when it is no longer needed. When 64 rooms are already kept, pinning in a new room is refused with a message saying so.
- **Limits:** up to 32 pinned feeds and 16 spotlights per room.
- **Every relay knows it:** spokes pass board changes to the hub and receive the hub's boards with the same connection that carries bans, so a room's board looks the same from every site. A spoke keeps its last copy if the hub goes dark.
- **Relay page:** the hub's **Rooms on this relay** table has a **Board** column, for example "2 pinned · 1 spotlit". Hover it to see what is pinned and spotlit, and who set it.
- **Closing a room** removes its board too.
- **Older KASTRs:** they still show pinned feeds from other rooms as tiles, but they can't pin, and they don't keep a board spotlight once the person who set it has left. The hub must run this version for boards to work anywhere in the fleet.

**Vehicles share their cameras without a room code (Kenton: "I now need to have a vehicle syslogic be able to connect via POST to the relay to share the cameras on the vehicle. They need to be able to create a room and share the cameras directly from the vehicle" ... "I need to be able to send a POST request without having to set a room code").** Each vehicle gets its own key. With it, the vehicle POSTs once to make a room (or join one) and publishes its cameras with the `moq` tool, the same tool it uses today. Kenton chose:
- **A key per vehicle, made on the hub:** the hub's Relay page has a new **Vehicles** card. Type the vehicle's name and press **Add vehicle**. The key is shown once, with **Copy** and a ready-to-run example (the POST and the camera command). Only a hash of the key is kept, so it cannot be shown again. The table lists each vehicle's name, when it was made, when it was last used and its last room, with **Revoke** and **Delete**. A spoke's Relay page says "Vehicle keys are managed on the hub".
- **The key can only make rooms and publish:** it cannot watch and has no admin rights. Each vehicle publishes under its own name in the room (for example `vehicle-12-3f9a`), and every camera shows as its own tile.
- **No room code:** the vehicle sends `POST /api/vehicle` with its key and a room name. If the room does not exist it is created as an ordinary room with no code. A room someone locked still needs its code. The Lobby (`main`) takes no vehicles.
- **Any relay in the fleet:** the vehicle posts to the relay it publishes to, hub or spoke. A spoke asks the hub whether the key is good and remembers a yes for a minute. The room is made on the hub, like a room made from a page.
- **The room closes when the vehicle stops:** the vehicle posts again every 5 minutes, which keeps the room open. About 10 minutes after the last post the room closes by itself.
- **Outbound only:** the vehicle makes an HTTP POST to the relay's port + 1 and connects to the relay on QUIC 4443, the same as a spoke. That works from a cellular link behind NAT.
- **Wrong keys count like wrong codes:** five wrong keys within a minute lock that address out, as with access codes. A revoked key is refused with "this vehicle key was revoked".
- **For the vehicle team:** `docs/vehicle-api.md` has the request and reply, the camera command (`ffmpeg ... | moq ... import ts`), the refresh rule and what each error means.

**Rooms made without a code are ordinary rooms now (Kenton asked for this with the vehicle API).** A request to make a room with no code that is not set to stay open used to be refused ("bad room record") unless it was marked plain. Now it simply makes a plain room. Heartbeats and take-overs work as before.

**4K HEVC cameras show the whole picture (Hollis: clicking a Southridge feed "zooms into the top left corner of the video and he can't zoom out ... some work like normal").** The moq tool labels an HEVC camera's picture as square: it writes the camera's pixel shape (1:1) where the picture shape (16:9) belongs. The player then decoded a 3840×2160 camera as 3840×3840, and KASTR stretched it back with a correction that showed a zoomed corner whenever it was off. KASTR's player now ignores a square display shape on a picture that isn't square, so these cameras decode at their real size with no correction. H.264 cameras were never affected. Real anamorphic cameras are left alone.

**Pull test on the Relay page (Kenton: "Sometimes when clicking on a video it still takes a while to display the full quality").** Each stream in **Streams on this relay** has a **Pull test** button (on the relay's own computer). The relay fetches the stream itself for 15 seconds and shows the time to the first byte and the rate. Run it on the hub, while nobody watches that camera, to see whether a slow open comes from the camera's site or the link between relays (slow here too) or from the viewer's side (fast here). In the lab, a cold camera across two relays gives its first byte in 0.1 s.

**Room bubbles show each part's initial (Kenton: "use the first initial of each part of the name").** **aoz-4** shows **A4** and **aoz-6** shows **A6** (both used to show AO), **control-center** shows **CC**, and **southridge** shows **S**. Up to three letters, slightly smaller when there are three. The Lobby shows **L**.

**Shorter times on the Relay page (Kenton: "instead of showing 3 min 23 s, just change it to 3m 23s").** "Last seen" and the other times there read **45s ago**, **3m 23s ago**, **1h 03m ago**.

**Mute and camera-off marks stay in the gallery (Kenton: "When showing user previews in the gallery view show their the mute/no cam icons whether hovering or not").** In the gallery view a person's muted-mic and camera-off marks stay visible when the mouse is away. Elsewhere they still fade with the other controls.

**Release notes and the Relay menu open above the rooms list (Kenton: "When looking at the version menu, the room rail is over top of it").** Both now sit above the rooms list and the toolbar menus. KASTR's confirm popups still come in front of them.

## v0.21.62 — each share picks its rooms

**Choose the rooms for each share, your camera included (Kenton: "When sharing my camera, I don't have the ability to share it to another room ... I need to be able to choose which shares go to different rooms, not all shares will go to every room").** Every share still sends one stream; people in each room you pick for it see it too, and nothing extra is uploaded. Kenton chose all four ways to pick:
- **Rooms button:** every source in **Share ▸ Sources** (camera, screens, RTSP and RTMP feeds, files) and every grid shows where it goes: **This room**, or **This room +2**. Click it to tick rooms for that share only.
- **Show in other rooms table:** a card under Sources lists your shares down the side and the other rooms across the top. Tick any box. A locked room asks for its code once.
- **Asked when you start a share:** a new share asks **Show “…” in other rooms too?** Answer **Just this room**, or tick rooms and **Apply**. Your camera, a camera box, and shares that come back when you rejoin never ask.
- **Menus:** **Show in other rooms…** is in every one of your own tiles' menus, and in the camera menu (**Show my camera in other rooms…**).
- **Remembered:** each share's rooms are remembered on this computer. A reload, a restart or an update lists it in the same rooms again. Room codes are never saved; a locked room asks again after a restart.
- **Removed:** the **Also show in** pill row in Share (which sent every new share everywhere) and the **More ▸ Share to several rooms** switch. Choosing rooms is always available now.

## v0.21.61 — light mode, your colours, updates that put you back, spotlights that wait

**Choose Light, Dark or System (Kenton: "Let people choose light/dark mode or the system default").** **More ▸ Appearance** switches between **Dark**, **Light** and **System**. System follows the device's own light or dark setting, and changes along with it.
- **Default:** Dark stays the default, so nothing changes for anyone until they choose (Kenton chose this).
- **One setting for every page:** the choice applies to every KASTR page on that device, including the Relay page and the start page. It takes effect at once in any page that is already open.
- **The video stays on dark (Kenton chose this):** in Light, the panels, toolbar, menus, rooms list and Relay page turn light, while the video stage and tiles stay on a dark background so pictures aren't surrounded by white. The ASI top bar keeps its navy look in both.
- **No flash:** each page applies the theme before it draws, so a light page never flashes dark first.

**The Lobby is called the Lobby everywhere (Kenton: "I clicked on the Lobby and got this message" -- it said "join main").** Going to the Lobby from a room now asks "Leave “tremonton” and go to the Lobby?" with a **Go to the Lobby** button. The join screen's title and **Room info** say Lobby too, and Room info no longer shows how many people are waiting there.

**Two colours of your own (Kenton: "1 to replace the global highlights for myself and 1 to choose my colors that other people see").**
- **Your colour (Profile):** pick one of ten colours, a custom one, or Automatic (today's colour). Everyone sees it on your rings: around your picture, around your name in the rooms list, and around your tile and your People entry while you talk.
- **Accent colour (More ▸ Accent colour):** replaces ASI blue across your own KASTR, on every page: buttons, highlights, the selected room, switches and the top bar's line. Nobody else sees it. The first swatch puts ASI blue back.
- **Older KASTRs:** older versions show ASI blue on your rings until they update.

**Update now beside the version (Kenton: "When a desktop user is not up to date, show an update now button at the top next to the version number. Make it strobe brighter/darker").** A KASTR app whose relay host runs a newer KASTR, or that the hub's Relay page offered an update, shows a pulsing amber **Update now** button next to its version. It checks every 2 minutes. One click runs the same update as About ▸ Check for updates. Web pages never show it, since they follow their host anyway.

**An update puts you back where you were (Kenton: "When pushing an update to a client, have it reconnect to the room and shares exactly as it was prior to upgrading").** After an update restarts it, a desktop KASTR goes straight back into the room it was in, with no join screen. It returns with your mic and camera as you left them, and puts back what you had spotlighted for everyone, unless someone removed it meanwhile.
- **Shares:** cameras, RTMP ingests, host files, screen and window shares kept on this computer come back as before.
- **Browser shares:** a share picked in the browser's own picker can't restart by itself, so a note asks you to share it again.
- **Other launches:** this happens only for a launch that follows an update, within 20 minutes; an ordinary launch shows the join screen as before. **Leave** clears it.

**RTMP ingests survive updates (Kenton: "RTMP URLs didn't stick after upgrading on the Support Laptop").**
- **Always kept:** an RTMP ingest (GoPro) is kept from the moment it's added, because the device holds its URL. Host cameras and host media files follow the "Keep sharing after restart" switch.
- **Nothing lost on restart:** a kept feed that can't come back at launch, or hasn't come back yet when you join, stays saved and is tried again next launch. Before, joining during a restart's first minute, or a failed restore, could erase the feed for good. Only Remove, or turning Keep off, forgets a feed.
- **Port freed at exit:** the RTMP listener now stops with KASTR, so the next launch can reuse its port.

**A spotlighted camera or grid waits 10 minutes for its box (Kenton: "retain the spotlighting through a relay/client reboot/upgrade ... hold Spotlighting for 5 or 10 mins").** When an RTSP camera or a camera grid is spotlighted, the box sharing it remembers that on its own disk. If the box or its relay restarts or updates, the spotlight comes back as soon as the box rejoins, if that happens within 10 minutes. While the camera is away the spotlight is held for those 10 minutes; screen shares and files still let go after 8 seconds. Lab test: the box closed and a new session joined, and the viewer's stage showed the camera spotlighted again at once.

**Room changes show at once (Kenton: "Is there a way to shorten the time it takes to show someone in a room and removing them from the old room?").** Someone who changes rooms now leaves the old room's list at the moment they appear in the new one: about 1 s on the lab LAN, where it used to take about 10 s. Someone who only reloads still gets the old 8-second grace, so they don't flicker out.

**RTMP feeds on a weak signal leave the grid (Kenton: "On an RTMP feed, on a weak signal, it keeps going to Connecting and doesn't remove it from the grid").** An RTMP ingest that stops delivering pictures for 10 s is taken out of its grid. It comes back after 15 s of steady pictures, so a flapping signal stays out instead of blinking in and out.

## v0.21.60 — the Lobby, a guide in Help, and the iPhone app's top edge

**`main` is now the Lobby (Kenton: "Lets change main to something like waiting room ... disable all views and people seeing each other").** The room everyone starts in is shown as **Lobby** everywhere: the room pill, the rooms list, the join screen and the change-room prompt. Kenton chose these rules:
- **Nothing is shared in the Lobby:** Camera, Mic, Share, People, Chat, Files and View are switched off there. The relay itself enforces it: a Lobby token can announce only that its holder is present, cannot publish media and cannot watch anything in the room. **An unattended box left in `main` stops publishing** and says so on its page. Move each box to its site room.
- **Nobody sees anybody:** no tiles, no people list, and the Lobby's card in the rooms list shows no names and no count.
- **Other rooms, seen from the Lobby:** their names and how many people are in each, but not who. You can't watch another room from the Lobby.
- **No chat:** the Lobby refuses chat messages and files, and keeps no history.
- **Joining a room:** the stage lists every room with its count; tap one to go straight in (a locked room asks for its code). The rooms list works as before.
- **Unchanged:** KASTR still opens in your last room; the Lobby is where first-timers start and where you land when your last room is gone. The room's internal name stays `main`, so saved settings, invite links and older KASTRs keep working. A relay enforces the Lobby rules only once it runs 0.21.60; on an older relay, only the page hides things.

**Help is now a guide to basic use (Kenton: "I would like an update to the help section with a guide for basic use").** **More ▸ Help & guide** opens short sections you can open and close: Getting started, The screen, Watching, Talking, Sharing, Rooms, Phones and tablets (including how to add KASTR to an iPhone or Android home screen), Keyboard shortcuts, and Something not working?. It replaces the old help text, which still described the 0.7 layout. The guide scrolls inside its card, so it fits on a phone.

**The iPhone home-screen app's top edge works (Kenton, iPhone in full screen: "I can't click on everything at the top. When I collapsed the top bar it won't let me click on the expand button. The expand button is overlapping with the people button").**
- **Show top bar:** with the top bar hidden, a thin strip across the top of the page brings it back. It sits below the iPhone's status bar, pushes the page down instead of floating over the toolbar, and on phones it is tall enough for a finger.
- **Rooms list:** the side panel on a phone starts below the status bar, so its first rooms can be tapped.

## v0.21.59 — pick any source on a phone

**A row of thumbnails under the stage on phones (Kenton, iPhone: "I don't have the ability to see the side rail to pick anything other than the spotlighted items").** A phone held upright used to show only the stage in speaker view, with no rail, the same as Focus on content. Now it shows a row of small live thumbnails directly under the stage: everyone and everything else in the room, with your own preview last. Swipe the row sideways and tap a thumbnail to put it on the stage; the stage stays where it is while you swipe.
- **Spotlight grid:** when several things are spotlighted, the phone shows the first on the stage and the rest at the start of the row.
- **Unchanged:** a phone held sideways, full screen, and Focus on content keep the full stage with no row. The thumbnails use extra mobile data; Focus on content still turns them off.

## v0.21.58 — sites that stay fresh

**Sites no longer go stale after days connected (field, Kenton: "sites get stale if they are connected too long ... I had to restart 2 sites after the weekend").** The two sites were Linux boxes. The relay showed auth refusals, and cameras and the grid stopped showing or froze. Every token a site box holds lasts a day at most, and several long-lived connections kept using their old token until the relay cut them off.
- **Camera feeds renew the token they are actually using:** when the box page handed a running camera feed a fresh token, the feed noted it but kept streaming on the old one. Its renewal timer then saw a full day left and did nothing, so the relay cut the camera about a day later. Now a feed moves onto the fresh token 15 minutes before its current one ends: one planned restart instead of a cut.
- **A cut camera feed can always recover:** a feed that was cut waits for a fresh token. It used to retry every 5 minutes with its expired token, which is refused every time, and it could not get a new token at all once the box page had left its room. It now never retries with an expired token, and it keeps getting tokens for the last room the page was in.
- **One hour of grace (Kenton chose this):** when the relay re-checks a connection that is already open, it accepts a token that ran out less than an hour ago, provided the relay itself signed it. A new connection still needs a valid token, and anyone kicked, banned or removed is still refused at once. The relay log notes each connection kept on an old token.
- **The box page's main connection** switches to its fresh token as soon as it gets one, instead of being cut at a random moment once a day.
- **The relay restarts itself:** if moq-relay exits on its own (for example, killed by Linux when memory runs low), KASTR restarts it after 5 seconds, waiting longer each time if it keeps failing within the hour, and says so in the log. Before, nothing restarted it, and the box looked half-alive because its token service kept answering. In the lab, a killed relay was back within 6 seconds.
- **The relay's log reader keeps going:** a line it could not decode used to stop it for good, and with nobody reading, moq-relay could freeze while still looking alive. Now it reads UTF-8 whatever the system setting and skips a bad line.
- **Recordings:** the token they record with lasts a day instead of an hour, so they are no longer cut every hour.

## v0.21.57 — one standby at a time

**Make standby hides once a standby is chosen (Kenton: "Lets just hide the 'make standby' if one is already chosen for now").** The hub keeps one standby. While one is chosen, only its row shows a button, **Remove standby**, and the other spokes show none. Remove it to pick a different spoke.

## v0.21.56 — arrange the Relay page on a grid

**Collapse, resize and snap the Relay page's cards (Kenton: "allow for collapsing individual tiles on the relay server page. Also allow for resizing and snap to grid instead of highlighting the other tile edges").** The cards now sit on a 12-column grid.
- **Collapse:** the chevron at the right of a card's title folds it down to its title. Click it again to open the card.
- **Resize:** drag the grip at a card's bottom-right corner. The width snaps to columns: a quarter, a third, half, two-thirds, the full width, and so on. The height snaps to 8-pixel rows, and a card shorter than its contents scrolls. Double-click the grip to make the card fit its contents again.
- **Move:** drag a card by its title. A dashed box shows exactly where it will land, and the other cards make room around it, instead of a highlighted edge.
- **No holes:** cards always float up into any space above them, so collapsing or shrinking a card closes the gap (Kenton chose "Cards float up").
- **Kept:** the layout is saved on this machine; a saved 0.21.52 card order carries over. **Reset layout** puts back the original order and sizes and opens every card. In a narrow window, every card is full width.

**Fixed:** in 0.21.55 an empty amber badge showed next to "Federation" on every Relay page that is not a standby.

## v0.21.55 — names for web visitors, update everyone, standby fixes

**Web visitors show by name on the Relay page (Kenton: "I need to have a name for web clients that shows in the relay server page").** The Users table used to list someone in a browser only as a `web-…` ID with no name.
- **Check-in:** a page opened in a browser now checks in with the relay host it came from, as the app does. It sends the name the person joined with and which browser it is. It checks in once a minute while in a room, and the row goes 3 minutes after the last check-in.
- **What the table shows:** the visitor's name in the Name column, and their browser, such as "Chrome on Windows" or "Safari on iPhone", in the Machine column. Hover over that cell to see the `web-…` ID.
- **Safe on a public tunnel:** a relay accepts a check-in for a `web-…` ID only while that ID has a live session on it, so nobody can add made-up users from outside.
- **Older relay hosts:** pages from a relay host older than 0.21.55 don't check in, so their visitors appear as before.

**Make standby works on older hubs (field, Kenton on the hub: "only the hub picks a standby (turn on 'This relay is the hub' first)").** A hub set up before 0.21.23 never saved its "This relay is the hub" setting. The Relay page shows the switch on, because the relay dials no hub and spokes register with it, but the standby code only accepted a hub whose setting was saved. Picking a standby, taking the hub's duties back after a takeover, and the hub's standby line now treat it as the hub too.
- **Only on the hub (Kenton: "hide the standby option unless it is a hub"):** the Make standby / Remove standby buttons appear only on the hub's Relay page. They don't appear on a spoke, or on a standby while it is acting as the hub.

**The standby says so (Kenton: "On the standby, show something in that section to know it is a hub standby").** The standby's Relay page shows a **Standby hub** badge next to the Federation heading. Below the hub fields, a highlighted box says whose standby it is, how recently it copied the hub's records, and when it would take over. The box turns amber if the copy is more than 2 minutes old. A standby acting as the hub shows **Acting as hub**, and a spoke that moved to the standby shows **On standby hub**, both in amber.

**Update all users (Kenton: "I want an update all users button").** Below the Users table, **Update N users** sends the same update request as each row's Update button to every KASTR app that is behind its relay's version, after one confirmation.
- **Each person is asked first:** their KASTR shows "Update now / In 10 minutes", as with a single Update. Unattended boxes update at once.
- **Who is left out:** web visitors (they follow their relay host by themselves), apps older than 0.21.50 (they can't receive a pushed update) and anyone not seen for 24 hours.
- **While it runs:** each row spins until that person is on the new version, and the button reads "Updating N users…". When nobody is behind, it reads "All users up to date".

**Users not seen for a day are hidden (Kenton: "Hide those that haven't connected in over 24 hours. But have a check box to show them").** The Users table hides anyone not seen for more than 24 hours.
- **Showing them:** tick **Show users not seen for over 24 hours (N)** above the table. The number tells you how many are hidden, and the tick is remembered on that computer. Someone with an update in progress always shows.
- **Connected boxes no longer look stale:** for boxes and apps older than 0.21.50, "Last seen" used to show when they *connected*, so a box online for two days read "2 days ago". Anyone with an open connection now counts as seen now, and hovering over Last seen shows when they connected.
- **Long gaps:** past two days, Last seen reads "3 days ago".

## v0.21.54 — back to the spotlight, a chosen standby address, a tidier top

**Hide the top bar (Kenton: "Give an option to collapse the top bar with the ASI logo, version, etc. and then an option to expand when collapsed").** A chevron at the right end of the top bar (logo, version, App, Go Live, Relay) hides it, which gives the page that height back. A small tab at the top centre brings it back. The choice is remembered on that computer, for the app and for every page in a browser.

**Back to the room's spotlight without changing it (Kenton: "There still isn't a way to get back to the spotlight view without adding/removing a spotlight").** Until now, the room's spotlight reached your stage only at the moment someone added or removed one. After you chose Gallery or clicked another tile, nothing brought it back.
- **View ▸ Spotlight** appears while the room has a spotlight and is ticked while it is on your stage. Choose it to put the room's spotlight back, whether that is one person, one share or the spotlight grid.
- **View ▸ Speaker** and the **G** key now go to the room's spotlight too, when one is set. Your own pins still come first.

**You choose the standby's address (Kenton asked which IP Make standby uses).** Before, the hub guessed it from the spoke's first network address, which on a box with several network adapters could be the wrong network.
- **The dialog:** Make standby now asks which address the other spokes should use. It lists every address the spoke reports, plus the one the hub sees it connecting from, with the likely one first. You can also type your own, such as `10.0.5.2`, `10.0.5.2:4443` or a name. Without a port, the spoke's relay port is used.
- **Its public address too (Kenton: "Have spoke check whatsmyip and suggest that as an option for hub standby"):** each spoke asks api.ipify.org for its public address when its relay starts and every 6 hours. If that service does not answer, it tries icanhazip.com, then ifconfig.me. The dialog offers that address marked "needs a port forward to it": spokes at other sites can reach the standby there only if its router forwards the relay port (UDP) and the port above it (TCP) to it.
- **The check:** when you confirm, the hub tries the address. If it gets no answer, the message says so in amber, so you can fix a wrong address or a firewall before you need the standby.
- **On the row:** the standby's row shows "spokes use <address>".

**Sort the Users table by any column (Kenton: "Sort Users on relay server page alphabetically. Or allow for sorting by any column").** On the hub's Relay page, click a heading in the Users table (Name, Machine, Kind, Room, Relay, KASTR or Last seen) to sort by it, and click it again to reverse the order.
- **Default:** by name, A to Z.
- **Order:** numbers sort naturally (Box 2 before Box 10) and capitals do not matter. Empty values go last. Last seen puts the most recent first.
- **Kept:** your choice is remembered on that computer.

**A failing camera leaves the grid after 3 attempts (Kenton: "still sometimes showing up beyond 5 attempts. Lets set it to 3 attempts before it drops from the grid").** A camera that stops answering now leaves the grid on its third failed reconnect instead of after its fifth, and comes back when it streams again. The seat stays reserved.
- **Why it could reach attempt 14:** a camera only left the grid when its feed's ffmpeg had also stopped. An ffmpeg waiting on a camera that accepts the connection but never sends video keeps running, so the camera was never removed. A running feed now counts as healthy only if video arrived in the last 30 seconds.
- **Lab test:** a camera that went dark in that way left the grid on attempt 3, 26 seconds later, stayed out while dark, and came back 42 seconds after it streamed again.

## v0.21.53 — a standby hub

**A spoke can stand in for the hub (Kenton: "Lets start on the standby hub").** Pick one spoke with **Make standby** on its row of the hub's spokes table. That spoke keeps working as an ordinary relay and also keeps a copy of the hub's records.
- **What it copies:** rooms and room groups, access codes (as their salted hashes, never the codes), kicks, and chat history. The copy follows the hub within seconds; the hub's Relay page shows how old it is, and the standby's own Relay page says whose standby it is.
- **When it takes over (Kenton chose "Standby + a spoke agree"):** the standby must have lost the main hub for 2 minutes, and at least one other spoke must have lost it too. With no spoke to agree, it takes over alone after 5 minutes. This keeps a broken link between just the standby and the hub from splitting the federation.
- **What spokes do:** a spoke that cannot reach the main hub for 2 minutes asks the standby to take over and, once it has, moves there. Its access code works there unchanged, because the standby holds the same code records. Viewers on a spoke reconnect within seconds while its relay re-points.
- **Locked rooms stay locked (Kenton: "Stay locked"):** while the hub is down, a spoke refuses to open a hub-locked room without its code. This now holds even after a spoke restarts, because each spoke reads the saved copy of the hub's room list, which records which rooms are locked.
- **Back to normal by itself:** when the main hub returns, it finds the standby acting as the hub. It takes back everything that changed meanwhile: new and closed rooms, groups, code changes, kicks and chat lines. It then sends every spoke home, and the standby returns to being a standby.
- **On the Relay page:** the standby's row has a "Standby" badge, and the button on that row becomes "Remove standby". A spoke that moved shows "Moved to the standby hub … the main hub … was unreachable", and a standby acting as the hub says so in amber.

**View-only people show just the eye (Kenton: "On view only people, autohide their name when not moving the mouse same as the publishers. Just keep the eye symbol").** In the speaker view and the side rail, a watcher's name now behaves like a publisher's: it shows while the pointer is on the tile and folds away when the mouse rests, leaving only the eye (and the deafened mark when it applies). In the gallery, names stay visible, as publishers' names do.

**"Last seen" reads naturally past a minute (Kenton: "Change Last seen to show minutes/seconds when over 60 seconds").** The spokes and Users tables now show "45 s ago", "2 min 05 s ago" and "1 h 03 min ago".

**Fixed on the way:**
- **Hand-over notes were lost:** relay-cluster.json dropped every setting it did not know when saved. This included the 0.21.25 hand-over note, so a spoke that started late never learned the hub had moved. Those settings are now kept.
- **Chat numbering after a hand-over:** a hub that took over another hub's chat history could reuse message numbers until it restarted. It now re-reads them at once.

## v0.21.52 — arrange the Relay page, restart a spoke, grids that heal

**The Relay page's cards fit their contents and go where you put them (Kenton: "drag around the windows in the relay server page to where I want them. Have the tiles only take up the space they need, not just use the same height for everything in the row").**
- **Height:** each card is only as tall as its contents, and smaller cards fill the gaps beside taller ones, so a short card no longer stretches to the tallest card in its row. Cards resize live as their contents change.
- **Moving a card:** drag it by its title (the dotted mark). A see-through copy follows the pointer, and a blue line shows whether it will land before or after the card underneath.
- **Kept:** your arrangement is saved on this machine. "Reset layout", next to the page introduction, puts the cards back in their original order.

**Restart a spoke from the hub (Kenton: "Build in ability to do remote restart of a spoke from the hub").** Each row of the hub's spokes table has a Restart button.
- **What happens:** after you confirm, that spoke's KASTR closes and opens again, and its relay restarts with it, so people on that relay reconnect within seconds.
- **Waiting:** the button spins until the spoke registers again with a newer start time, then says "✓ restarted". After 5 minutes it says "didn't come back".

**Grids no longer stay split into separate tiles (field, Mendon: "it has everything split out into separate tiles ... resolved by restarting KASTR on the mendon-relay").** The cause was on the viewer's side: a viewer that missed the box page's announcement of its room state never learned the grid's layout, so the grid and its cameras showed as separate tiles until the box restarted. Now a grid with no layout for 20 seconds looks up its owner's room state from presence and subscribes directly, and the grid comes back by itself, in your room and in rooms you watch. The diagnostics now show the room state a page publishes and reads, and a relay's log collection includes its own page's diagnostics.

**The person's circle stays centred (Kenton: "Sometimes the circle is not centered and is pushed up").** A tile with no picture showed its round avatar, sound meter and caption as one centred stack, so a caption such as "connecting…" or "waiting on relay …" pushed the circle up, into the top edge on short rail tiles. Now only the circle is centred, with the meter and caption hanging below it. In the lab it was exactly centred (0 px off) in the gallery and in a 177 px rail tile, with and without a caption.

**A failing camera says why (field, Mendon's log collection: camera `d9wxp8a5o5cjvhep` stopped every 10.5 seconds and its log line ended with the moq tool's message).**
- **The log line:** a camera feed's exit line now quotes the process that actually stopped, and says what ffmpeg's exit code means. Mendon's code 183 means "invalid data from the camera": the camera sends a stream ffmpeg cannot parse, so check its codec settings (H.265+/smart codec) or use its substream.
- **The Relay page:** the health card shows each feed's last exit and why, in amber once a feed has restarted more than three times.

## v0.21.51 — logs collected at the hub

**Every machine's logs in one place, on request (Kenton: "Could we have the logs all send to the hub to make log collection easier?").** A new Logs section on the Relay page has two actions:
- **Collect the last hour:** every relay (the hub and every spoke), every unattended box and every KASTR app sends its last hour of logs to the hub.
- **Search every log for …:** each machine sends only the lines that contain your words, for example a stuck camera's path such as "mikey/camera". This is quick even over thin site links.

**How a collection runs:**
- **Who sends what:** a relay sends its relay log and its launch log; an app or box sends its launch log and its pages' diagnostics.
- **When they answer:** relays answer within seconds over the hub's command channel. Apps answer at their next check-in, within a minute, and their logs reach the hub through the relay they use.
- **Watching it:** the section lists each machine as it answers and shows who it is still waiting for, for up to 3 minutes. "Download all (.zip)" gives one file per machine and log.
- **Secrets:** tokens, access codes and bearer keys are blanked on each machine before anything is sent.
- **Limits:** at most 4 MB per log file per machine (the newest lines are kept). The hub keeps the last five collections.

Nothing is sent until someone presses one of the buttons, so there is no standing traffic between sites.

**Tested** on the two-relay lab: "Collect the last hour" got answers from the hub's relay, the spoke's relay and a simulated app connected to the spoke ("3 answered — everyone answered"). The zip held all six files, and the app's token appeared as `jwt=<redacted>`. A search for "connected" reached the same three.

## v0.21.50 — every user on the hub's Relay page, updates that wait, the relay's log on disk

**Every user, with their KASTR version, on the hub's Relay page (Kenton: "see all of the users in the hub relay server page. With the ability to push an update to the client and see what version it is").** A new Users table on the Relay page lists everyone connected to this relay and, on the hub, to every spoke: name, machine, app, box or web, room, the relay they use, their KASTR version (amber when behind their relay) and when they were last seen.
- **How it knows:** every KASTR app now checks in with the relay it uses about once a minute, saying its machine, version and mode. Spokes pass their list up to the hub.
- **Web visitors and older apps:** web visitors and apps older than 0.21.50 still appear, from their relay connection. Older apps are marked "older KASTR" and have no Update button; restarting KASTR on that machine updates it.

**Update pushes come from the user's own relay (Kenton: "The update push should come from the connected relay, not the hub").**
- **Delivery:** Update on a user's row asks the relay that user is connected to. The app hears it on its next check-in and downloads the update from that relay.
- **Asking the person first:** their window says "KASTR 0.21.x is ready from your relay. Restart KASTR now to update?" with Update now / In 10 minutes. After 10 minutes it updates by itself.
- **No one to ask:** unattended boxes, and apps with no window open, update straight away.

**Update buttons that wait (Kenton: "don't go back immediately to being able to click update. Have it spin and wait ... before coming back and saying that the updates are done").**
- **Pending state:** an Update (for a user, a spoke, or "Update N spokes now") becomes a spinner with a timer and what it waits for: "waiting for the person…", "updates by itself soon…", "updating…" or "restarting…".
- **Finished:** it ends with "✓ updated to 0.21.x" once the new version reports back, or after 10 minutes with "didn't update" and the reason (offline, still on the old version, the person chose later, or the update failed there).
- **Refresh:** the table refreshes every 5 seconds while anything is waiting, and the finished results stay listed under the table.

**The relay's log on disk, and a search for the field check (field, Mendon: the 200 lines kept in memory covered a few seconds, so a stuck camera left no trace).** Every relay line now also goes to relay.log in KASTR's state folder (about 20 MB plus one older copy). The field check can pull every line about a stream:

  powershell -ExecutionPolicy Bypass -File kastr-field-check.ps1 -Find "mikey/camera,support-laptop"

On Linux use `FIND="mikey/camera,support-laptop" bash kastr-field-check.sh`.

**Tested** on the two-relay lab. A simulated app (Test PC, KASTR 0.21.40) checked in with the spoke, and the hub's Users table listed it under lab-spoke with an Update button. Pressing Update reached the app through the spoke. The cell showed "waiting for the person… 0:30" while the app asked, then "✓ updated" once it checked in on the new version, and the result line said "Test PC updated to …". The relay log search returned the cluster link lines from relay.log.

## v0.21.49 — spotlight a watched source for everyone, see who's out of date, choose the RTMP address

**Spotlight a source from another room for everyone (Kenton: "I'm still not able to spotlight a share from another room except for pinning it for myself").** A source you watch from another room now offers "Spotlight for everyone".
- **How it works:** it brings that one source into your room (everyone there receives it), then spotlights it. The source stays listed while it is spotlit and is withdrawn about a minute after the spotlight is removed.
- **Locked rooms:** as Kenton chose, anyone who can see a source may bring it in, except that a source from a locked room needs the admin code, so a locked room's content can't leak out through a plain member. The relay enforces this, not just the page.

**See who is on an old KASTR (field: Support Laptop on 0.21.34 stayed "connecting…" for everyone until it was updated).** Each person's presence now says which KASTR they run. Participants marks anyone older than you: "KASTR 0.21.4x — needs updating", or "Older KASTR — needs updating" for versions before 0.21.49, which don't report one.

**Choose the RTMP push address (Kenton: "The support laptop is choosing an IP that is on an interface I don't want to use").** The RTMP ingest always accepted pushes on every interface; only the address shown in the push URL was fixed to the computer's first one. An RTMP feed's row now has a menu of the computer's addresses. Your choice is remembered, and is no longer replaced by the first address when KASTR starts.

**Tested** on the two-relay lab: Kenton (kb3) watched Alex's camera feed in ka3 and spotlit it for everyone; Sam (kb3) received it, played it (162 frames) and his stage showed it. Unit tests cover the relay side: a view-only member may bring in, a token from a different room may not, a locked room needs the admin code, the target room still needs its member token, and a stop withdraws the listing.

## v0.21.48 — everyone can see you're deafened

**Deafen shows to others wherever they look (Kenton: "I need to show others when I have deafen turned on").** Since 0.21.40 the mark appeared only on your camera tile's mic chip, and that chip fades out when the viewer's mouse is still, and in Participants.
- **On your tile:** the headphones-off chip is now amber and stays visible, even when the viewer's mouse is idle.
- **Without a camera:** your view-only tile (avatar and eye) shows the headphones-off mark too.
- **In the room rail:** a headphones-off mark appears beside your name in the left room list, both for people in your room and for people in other rooms.
- **It clears the moment you undeafen.**

**Tested** on the two-relay lab with four windows: Alex (camera on) and Sam (view only) deafened in room dz. Kenton (in dz) saw the amber chip on Alex's tile with the mouse idle, the mark on Sam's view-only tile, and both names marked in the rail. Olive, in another room, saw both marked on dz's card. Undeafening cleared everything.

## v0.21.47 — choose what you watch, rooms in Share, spotlights stay in their room

**Watching another room: you choose the sources (Kenton: "don't show all of the room shares, let me select which one or multiple are viewed in my current room").**
- **The list:** the eye on a room card (or its right-click "Watch from <room>…") opens that room's list: shares, grids and cameras first, then people. Only what you tick shows in your window, muted until you choose "Hear <room>". Ticking a grid brings its cameras along, hidden behind it, so a cell still opens in full quality. Close the list with nothing ticked and you're not watching that room.
- **Later sources:** a source that starts in that room later is not shown on its own. The eye shows how many you have not looked at yet, and the list marks them "new".
- **A tile's own menu:** a watched tile's menu has "Stop watching this" (that one source) and "Choose what to watch from <room>…".

**It stays with the room you're in (Kenton: "it should stay with the room I'm in, not follow me around").** Each room you join keeps its own watch list. What you picked while in A shows only in A; switching to C shows C's list (empty until you pick), and coming back to A brings A's back. Lists are kept per relay on this device. The list you had in 0.21.44–0.21.46 moves to the room you're in when you first open 0.21.47.

**Share › Also show in (Kenton: "Give options to choose which rooms in the share section").** With More › "Share to several rooms" on, the Share panel shows "Also show in" with a chip per room. Every share you start after that also shows in the ticked rooms. A locked room asks for its code once per session. Your camera isn't a share, so its own menu still lists it. A share's own menu still changes the rooms for that one share.

**A share listed into your room is your room's (Kenton: "let anyone spotlight it as normal").** Anyone in the room can "Spotlight for everyone" a share listed in from another room, even someone who is also watching the room it came from. Before, that person's copy counted as "watched" and the option was hidden.

**Spotlights stay in their room (Kenton: "pin the view to the room, don't follow the person").** A spotlight applies only to its own room's sources and to shares listed into that room; it never pulls in a source from somewhere else.

**Tested** on the two-relay lab with three windows (Alex in qa or wa, Sam and Kenton in qb or wb):
- the eye opened qa's list (Grid, then Alex's camera) and nothing showed until ticked;
- ticking the grid brought the grid plus its two cameras, hidden behind it;
- Alex's Share row listed kept-room, main and wb, and ticking wb listed his next share there;
- Kenton spotlit that share for everyone and Sam's stage followed;
- Kenton's watch list emptied in main and came back in wb.

## v0.21.46 — Southridge's full-quality cameras come back

**Southridge's cameras never opened in full quality (Kenton: "Southridge doesn't seem to be getting the trigger to send full quality video").** Southridge's grid was published as `obs-svr-395f`, but every camera in it was still published as `obs-svr-1980`.
- **Why:** the four-character suffix on a machine's name comes from a network adapter's MAC address, and KASTR re-read it at every launch. On a machine whose adapters come and go (VPN, virtual or USB adapters), a different adapter can answer, and the name changes. The camera feeds KASTR restored after a restart kept the old name. The relay only lets a machine publish under its current name, so it refused every one of them, while the grid, published fresh, kept working. A grid-cell click found no full-quality stream to open.
- **Fix 1 — the name stays put:** the suffix is now chosen once and kept in KASTR's state folder (`host-id`), together with the adapter it came from. Adapters coming and going no longer change it. A cloned disk image on other hardware, or a replaced network card, still gets a name of its own, so cloned boxes never collide.
- **Fix 2 — restored feeds follow the machine:** a feed the server restored under an older name is taken back under the machine's current name and republished, so the relay accepts it again.
- **Southridge needs this update and one page reload** for its cameras to come back. Until then, removing and re-adding its cameras on that box does the same.

**Tested:** on the lab spoke, a camera feed forced onto an old machine name was renamed and republished on the next page load, and a viewer on the other relay received it in full (189 frames). Unit tests cover: the name kept across launches; another adapter answering, or uuid's random fallback, leaving it unchanged; and a clone on other hardware getting a new name.

## v0.21.45 — pin several sources for yourself

**Pin several sources from different rooms, for yourself (Kenton: "I need to be able to pin multiple sources from separate rooms for myself").**
- **Pin for me adds:** each tile's menu (⋯ or right-click) has "Pin for me", which adds the tile to your pins. You can pin up to 9 sources, from your own room and from rooms you watch. Two or more pins share your stage as a grid; one pin fills it. A pin badge marks each pinned tile.
- **Unpin removes just that one:** the others stay. When you unpin the last one, the stage goes back to the room's spotlight if there is one, otherwise to the gallery.
- **Your pins win:** while you have pins, a "Spotlight for everyone" from someone else does not move your stage, and a new share does not take it either.
- **Remembered on this device:** pins are kept per relay and come back after a reload, a relaunch or a room change, once each source is live again. Gallery leaves the pins in place; View › Speaker brings them back.
- **The limit:** a tenth pin asks you to unpin one first. Pins whose source has gone away are cleared first to make room.

**Tested** on the two-relay lab with three windows (Alex in wa with a grid of three test cameras, Sam in wb, Kenton in wb watching wa):
- Kenton pinned wa's grid, Sam (wb) and Alex (wa), and they shared his stage as three equal cells;
- Sam's "Spotlight for everyone" left Kenton's stage unchanged;
- unpinning Alex left two pins;
- a reload brought both pins back;
- unpinning both handed the stage to the room's spotlight.

## v0.21.44 — watch extra rooms

**One window, several sites (Kenton: "one window for several sites" — several rooms on one fleet, stay in one room, watch the others).**
- **Watch a room too:** each room in the left rail has an eye button, and its right-click menu has "Watch <room> too". You stay in your own room; your camera and microphone stay there. A locked room asks for its code in KASTR's popup.
- **Where it shows:** the watched room's cameras, grids and shares appear with yours, after your room's tiles, each labelled with its room, e.g. "Alex Rivera — Gate (southridge)". A grid's cameras stay behind the grid as usual. Pin for me, full screen, Arrange this grid for me and full-quality cells all work on them.
- **Muted until you ask:** a watched room starts silent. "Hear <room>" on the room's right-click menu (or on any of its tiles' menus) turns its sound on; "Mute <room>" turns it off again. Each tile's own mute still works.
- **It stays out of your room:** a watched room never takes your stage on its own, never chimes, and its people are not listed in your Participants. "Spotlight for everyone" and the admin items are not offered on its tiles, and stall reports for its streams are not sent into your room.
- **Remembered:** the rooms you watch are kept per relay on this device and come back after a reload or a relaunch. A locked room's code is kept only for this session; after a relaunch its eye turns amber, and a click asks for the code again.
- **Changing rooms:** a room change keeps watching the others. Joining a room you were watching takes it off the list, because it is your room now.
- **Not on unattended boxes:** publisher, publisher + relay and publish-only devices never watch.

**Tested** on the two-relay lab, with a viewer in room wb watching room wa (a grid of three test cameras plus a person):
- the wa tiles arrived labelled "(wa)", muted and playing, with the three cameras hidden behind the grid;
- the viewer's stage, Participants list and chimes were unchanged;
- the right-click menu and "Hear wa" worked;
- the watch survived a reload;
- the eye stopped and restarted the watch;
- switching into wa removed it from the list and dropped the "(wa)" labels.

## v0.21.43 — the grid layout editor

**Arrange a grid: templates, drag, resize, gap (Kenton: "some cells bigger", "drag, gaps, resize", "viewers' own layouts", "several full-quality streams in one grid").** Three parts, as Kenton chose them.

**The owner's layout, which everyone sees.**
- **Templates:** the grid's ▾ menu offers Equal, One big, Two big, Side by side and Stacked. In One big and Two big the first cameras in the order are the big ones; drag a camera onto the big spot to choose.
- **Edit layout…:** opens an editor over the grid on the stage. Drag a cell to move it, drag its corner to resize it on a 24 × 24 snap grid, and drop a cell on another to trade places, size and all. Cells never overlap. A Gap slider sets the space between cells (0–24 px; 2 px is the old look). There are Reset, Cancel (Esc) and Done buttons, and the toolbar sits above the picture when there is room.
- **It sticks to the cameras:** the layout is kept per camera, so a camera that drops and comes back returns to its place.
- **Viewers get the exact layout:** the owner now sends the cell rectangles it draws, so viewers' clicks, cell zoom and "opening" badges follow any layout. Viewers on 0.21.42 or older still see the new layouts in the picture, but their clicks follow the old math.

**My own view, which only I see.**
- **Arrange this grid for me…:** on a grid's ⋯ or right-click menu, opens the same editor on your screen only. Each cell is cut from the grid picture and placed where you put it, with no extra download.
- **Use the owner's layout:** goes back to theirs.
- **Remembered per grid on this device,** also across room changes.

**Up to 4 cells at full quality, on my screen.**
- **Turning it on:** right-click a cell, then "Full quality in the grid: <camera>". That cell shows the camera's own stream instead of the grid picture, marked "Full quality". It works with or without your own arrangement.
- **The limit:** a fifth asks you to turn one off first, because 4K cameras are 10+ Mbit/s each.
- **Turning them off:** "Back to the grid picture for every cell" turns them all off.

**Tested** with two lab windows on two boxes and four test cameras:
- the owner's One big and the drag that put Yard in the big spot reached the viewer exactly;
- the viewer's own One big left the owner's layout untouched;
- Gate at full quality decoded its own stream (180 frames) while the others stayed on the grid picture;
- a fifth full-quality cell was refused;
- a click on the big cell in the viewer's layout opened Gate.

## v0.21.42 — KASTR's own popup, locked rooms always ask

**Questions in KASTR's own popup (Kenton: "I would like the popup for the room change moved to a stylized popup in the middle of the screen, not just a chrome popup").** Every yes/no question KASTR asks now appears in a KASTR card in the middle of the screen over a dimmed page, with specific buttons (for example "Join vault" / "Stay in main"). That covers changing rooms, closing a room, removing someone, muting everyone, deleting a room group, removing a file, opening the RTMP firewall ports and replacing a camera that is already shared. Enter answers yes, Esc or a click beside the card answers no, and the page's shortcut keys stay quiet while it asks. Tested on desktop and at phone width: the card is exactly centred, and no browser popup appears.

**A locked room asks for its code, wherever it sits in the rail (Kenton: a locked room "at the bottom of the rail, it never pops up the enter code prompt").** Two causes:
- **A room you had created yourself:** it is remembered with its room key, so the click skipped the code question. The relay still wants the code, so the switch failed without a word.
- **The old inline code form:** it opened below the visible part of the rail.

Now a locked room always asks for its code inside the same centred popup, and the relay checks the code before you leave the room you are in. A wrong code says "Wrong room code." and keeps the popup open, with your mic and camera untouched. A refused switch says so, and nothing gets muted. Tested: the wrong code kept Alex in main with the mic and camera on; the right code joined vault, muted with the camera off.

## v0.21.41 — share to several rooms, the mic button, the room rail's people

**Share to several rooms (Kenton: "the ability to share from 1 device to multiple rooms. Maybe a room selection on the share after toggling the feature on ... in the more (ellipsis) menu").** Turn on More ▸ "Share to several rooms". After that, each new share (and your camera) offers "Choose rooms", and every share's menu has "Also show in other rooms…": tick the rooms and Apply. A locked room asks for its code.

The share is sent once and stays in its own room; the other rooms list it, so nothing extra is uploaded. Their members see it as a tile marked "(from <room>)".
- **How it is kept:** the hub keeps the list (spokes forward to it and mirror it, like rooms). A listing needs your token for the share's room plus a member token for each other room. It is refreshed every minute and lapses 3 minutes after it stops being refreshed.
- **Access:** members of a listed room are allowed to read only that one stream, through a separate connection. Unticking a room, stopping the share or leaving the room ends the listing.

Tested with two lab windows in rooms xa and xb: Kenton in xb played Alex's camera from xa (772 frames), and unticking xb removed it. Mixed fleets: a 0.21.39 relay passes the stream on, but only 0.21.41 pages show listings.

**Changing rooms asks first and arrives quiet (Kenton: "When clicking to change rooms, prompt to let the user know they will be leaving the current room ... When changing rooms, mute mic and disable camera").** Clicking another room in the rail asks "Leave … and join …? Your microphone will be muted and your camera turned off." Every room change, including creating a new room, mutes your mic and turns your camera off on the way. Tested: Cancel stayed in main with the mic and camera on; OK arrived in the other room muted with the camera off.

**Shared sound starts off (Kenton: "When sharing something, default to audio off unless it's a media file").** "Include sound" for a screen, window or tab now starts off every time KASTR opens; turn it on when you want the computer's sound. RTSP cameras and camera feeds already start without sound. Media files keep their sound.

**The people in the room rail (Kenton, four requests).**
- **Alphabetical order:** "The people displaying in the rooms on the left rail should be in alphabetical order." Names now sort A to Z in every room.
- **A switch to hide them:** "an option to collapse the users in the rooms and only show the other info". The people icon beside Rooms hides or shows the names under every room, and this device remembers the choice.
- **A ring when someone speaks:** "a highlight or border when audio is playing ... just around their name in the left rail". The name gets the same blue ring as a speaking tile. In the room you are in it follows exactly what your window hears, the same signal the tiles use.
- **The person's menu from the rail:** "allow mute/unmute/spotlight, etc from the left side rail on a user". In the room you are in, hovering a name shows ⋯, and right-clicking a name opens the same menu as their tile (mute, pin, spotlight for everyone, admin items).

Tested with three lab windows: names sorted, the ring followed the person heard speaking, the menu offered mute, pin and spotlight, and the hide switch held through a reload.

**Room cards and the Create room button (Kenton: "move the people and time to the right of the room name, when space allows" -- "Move the Create Room button to the right of the Rooms and server info with just a + in a circle").** A room's people count and timer sit beside its name and drop under it only when the name is long or the rail narrow. Create room is a circled + at the top of the rail, beside the people switch; the collapsed icon rail keeps its + at the bottom.

**Your microphone's own mute button works in KASTR (Kenton: "auto detect when a mic has unmuted and unmute in KASTR? Certain microphones announce this to windows and it works on Teams").** Two ways, both on unless you turn off Mic menu ▸ "Follow my microphone's mute button". KASTR only follows the device and never changes its mute itself.
- **Windows mute:** when the microphone you use is muted or unmuted in Windows (a headset's or USB mic's mute switch, or a laptop's mic key), KASTR's mic does the same within a second. When you join with the device already muted, KASTR's mic starts muted, but KASTR never unmutes on its own at the start.
- **Headset buttons:** for telephony headsets (Jabra, Poly, EPOS, Yealink and others), Mic menu ▸ "Use my headset's buttons…" asks once which headset to use. After that, the headset's mute button mutes and unmutes KASTR, and its mute light shows KASTR's mute. The headset reconnects by itself the next time.
Tested in the lab with a simulated Windows mute and a simulated headset. A real headset still needs testing: KASTR sees Kenton's Yealink BH76 Plus as the default microphone.

**Locking the computer stops screen sharing (Kenton: "Sharing should stop when a computer is locked, and shouldn't reconnect automatically" -- "If it's a relay + publisher box it can keep sharing while locked").** While you share a screen, window or tab, KASTR checks every 2 seconds whether Windows (or the Linux desktop) has locked the session. On a lock it stops those shares exactly as Stop sharing does: they do not come back after you unlock, and a relaunch does not restore them. Cameras, RTSP feeds, grids and media files keep going. Publisher and Publisher + relay boxes (unattended, usually locked) keep sharing. Tested with a captured test tab: the share stopped within 2 seconds of the lock and stayed stopped after the unlock.

**The last switches now come first too.** Three Mic menu switches (Noise suppression, Voice isolation, Keep audio clear) still sat after their labels in 0.21.40; they now lead like every other switch.

**Smaller zoom buttons (Kenton: "the zoom and + - buttons are quite big. The % should only show when zooming in/out").** The − and + are smaller (20 px), and the zoom percentage appears only while you zoom, for about a second and a half. Tested: 150% showed right after zooming in and was gone two seconds later.

## v0.21.40 — your own browser, Deafen, the gallery stays, a cleanup

**KASTR opens in your own browser (Kenton: "use the default browser on each computer and only use the built in browser if they don't have a chromium based browser available or if they are a relay/hub/spoke ... This should allow them to share their tabs more easily").** On a person's computer, KASTR now opens its window in the default browser when that browser is Chromium-based (Chrome, Edge, Brave, Vivaldi, Opera, Chromium), with the person's own profile: Share ▸ a browser tab lists their real tabs, and their sign-ins and extensions stay as they are. KASTR's own browser is used when the default is not Chromium-based (Firefox, Safari), and always on boxes: relay, hub and spoke machines, Publisher and Viewer modes, and any machine that shares cameras or grids (a person's own browser slows a hidden window's drawing, and a grid is drawn by its owner's window). `browser = bundled` in kastr.ini keeps the old behaviour on any machine, and `browser = auto` is the new default.

In your own browser KASTR never closes or kills the browser. The window tells KASTR when it closes: closing the window ends KASTR within about 8 seconds, while a reload or a Relay page tab closing does not, because KASTR counts its open pages. An update or mode switch asks the window to close; if the browser does not allow a page to close itself, the window says that KASTR restarted and can be closed. Not available in your own browser: the NPU person-cutout engine (it needs a browser flag), so video effects use the GPU engine.

**Deafen (Kenton: "an option to mute all audio in the options ellipsis ... mute all inbound audio as well as mute my own mic. Deafen might be the best way to name it").** More ▸ Deafen, or the D key, turns off every sound from the room (people, shares, chimes) and mutes your mic in one step. Deafen again (or D) brings the sound back, and your mic only if it was on before. Unmuting your mic while deafened also undeafens. Tested in the lab through each of these paths. Everyone else sees it too (Kenton: "When deafen is enabled, show other people that it is on"): your camera tile's mute mark turns into slashed headphones ("Deafened" on hover), and your row in Participants shows the same icon. Tested with two lab windows: the mark appeared on the other window within seconds and cleared when undeafened.

**Back to the gallery, and it stays (Kenton: "I need a view button to go back to the gallery ... It does kick me back to the spotlight view if something gets added or removed though" -- "Gallery is showing as selected").** View ▸ Gallery, the G key, the tile menu's Unpin and the full-screen Gallery button now do the same complete reset: they close a camera opened from a grid, release your own spotlit preview, undo zoom, leave Fill window or full screen, and show the gallery. Once you choose the gallery it stays until you pick something yourself or someone spotlights something new. A spotlit share that drops out and comes back, or a new share arriving, no longer pulls your stage back. Tested with two lab windows: the gallery held through a spotlit share leaving and returning, and a new spotlight still took the stage.

**The play badge means something is playing (Kenton: "drones room is showing a play icon, eventhough there is nothing playing in there").** A box listed every camera it had added as video, so a camera that was dark, unplugged or out of range kept its room's play badge lit. A box camera now counts only while its stream actually flows (new data in the last 15 seconds). Tested: a camera that never answers leaves the badge off, a streaming one turns it on, and the badge goes off within about 20 seconds after the stream stops. Boxes still on 0.21.39 keep the old rule until they update.

**Switches before their names (Kenton: "the toggles for items should show before the name/description ... in the sharing menu the camera toggle and the include sounds toggle are right next to each other, which is confusing").** Every switch now sits to the left of what it switches: the video effects list, the audio settings, the Share menu header and the grid header. In the Share menu header, "Include sound" and "Cameras" are now separated by a divider, so the two switches no longer read as one pair.

**Things that were meant to be hidden now hide (found by a cleanup check).** Five page parts ignored their hidden state, because a style rule overrode the browser's: the chat's emoji grid and its empty attachment strip, the "Unusual file" warning when sharing a file, and the launch page's download tile for a platform the host does not offer. Each now hides when it should (checked in the browser: all five report hidden and take no space).

**A cleanup (Kenton: "Lets do another check to see what we can clean up").** Four read-only audits (server, page scripts, page styles, repo) listed what nothing uses any more; Kenton chose what goes. Over 1,000 lines of code are gone, with no change to what anyone sees:
- **The relay LAN mesh is removed.** Its Relay page switch went in 0.21.23, which left a box that had it on with no way to turn it off. Now every relay comes up without it and deletes its leftover secret file. Finding relays on the local network (mDNS, since 0.21.22) is unchanged.
- **Code for boxes older than 0.21.30 is gone** (the whole fleet runs 0.21.34 or newer). This covers the old `.` path names, the single-spotlight and single-grid fields, the old picture-strip latency reader, and `~since` announcements. Relays still accept `~since` from 0.21.3x pages.
- **Unused code is gone:** the retired stats panel and latency-stamp writer, hidden "my streams" rows that still made thumbnails every 800 ms in a second window, four endpoints nothing calls (`/api/ini`, `/api/archive/seg`, `/api/relay/lan`, the spokes table's close-room), and about a dozen functions and many style rules.
- **The docs describe today's KASTR.** ARCHITECTURE.md and REQUIREMENTS.md described v0.7.0; they, README.md, docs/, DOCKER.md and MACOS.md now match 0.21.40.
- **Release files live in the repo.** The kastr.ini and Linux install files that ship with every release were only in the build folders; they are now in `extras/`.
- **The Windows ffmpeg download is pinned.** It is now the exact bundled version (9.0.1), checked by SHA-256 like the Linux and MoQ downloads.
- **The large model files left git.** The NPU and MediaPipe model and wasm files (48 MB) are fetched and checked by SHA-256 when building, so the repository stops growing with every model update.

## v0.21.39 — one row per relay, Linux relays show their address

**A renamed relay is one row on the hub (Kenton: the renamed Linux relay showed its old name and its new one in the federation spokes, the old one stuck on 0.21.34).** Since 0.21.30 a spoke's regular check-in refreshed every row in the hub's spokes table that came from the same network address -- so after a rename the old row, from the same machine, looked alive forever. Now each spoke sends a machine id that a rename does not change: registering under a new name removes the same machine's old row, and a check-in refreshes only that machine's row. Spokes still on 0.21.38 or older refresh only the row registered last from their address, so a renamed box's old row ages out within minutes once the hub runs 0.21.39.

**Linux relays show their address on the hub (Kenton: "why does the Mendon relay show long poll / tunnel-nat instead of the IP address it is on?").** On Ubuntu and Debian the machine's own name points at 127.0.1.1, so a Linux KASTR found no network address for itself: it told the hub it could not be reached (shown as "long-poll (tunnel/NAT)"), and its Relay page listed no LAN addresses. KASTR now also asks which address its outgoing traffic uses, and `hostname -I` on Linux. Checked on WSL's Linux: the address is found where it was empty before.

## v0.21.38 — chat tone, Gallery in full screen, auto-pick keeps codes

**A tone for new chat messages (Kenton: "a tone for if a chat comes in while you're in a room" -- "I don't want the same chime as the enter/exit for the chat").** A short two-note bell (higher and quicker than the join / leave chime) plays when a message from someone else arrives that you have not seen: the chat panel is closed or the window is not in front. A burst of messages rings once; the history loaded when you enter a room stays silent; muting all sound mutes it too. Tested: Alex's message reached Kenton with a badge of 1 and the two-note tone.

**The Gallery button only in full screen and Fill window (Kenton: "remove the gallery button from in the main page when on a grid or in a single stream. Only show it when in full screen or full window ... the icon only unless moused over").** On the normal stage the button is gone (it could overlap the picture); View ▸ Gallery is unchanged. In full screen or Fill window a ▦ button shows at the top-left, reads "Gallery" while the mouse is on it, and takes you out of full screen / Fill window back to the gallery.

**The nearest-relay pick keeps your access codes (found while testing).** 0.21.36's launch-time switch to the nearest relay cleared the codes on the join card, as a relay picked by hand does, so a computer whose nearest relay differed from its last one asked for the code again at every launch. An automatic switch now keeps them; where a relay takes a different code, the join says so.

## v0.21.37 — tile chrome, one fleet clock, relays start with web clients off

**Tile buttons that never overlap or go blank (Kenton: button boxes empty on a black background; "when the browser zoom is used, these boxes overlap").** A new tile's full-screen and fill-window buttons got their icons from a repaint that only reached tiles already on the stage, so they could sit empty until something else (entering full screen) repainted them; they now get their icons when they are made. The three buttons are spaced from their own size, so the larger phone-size buttons (which a browser zoom can trigger) no longer overlap.

**Mute and camera-off marks fade with the controls (Kenton: "the mute icon should only show when moused over and fade when not moving the mouse" -- "when mousing over the user rail, not each separate user only").** The mute and camera-off marks on tiles show while the mouse moves anywhere over the stage and fade with the other tile controls after 3 seconds still; they hide at once when the mouse leaves the stage.

**A stuck tile names its relay as a relay (Kenton: the notice showed "on streams that never had RTSP streams").** "mendon-rtsp" was the Mendon relay's name, not a camera. The caption now reads "waiting on relay mendon-rtsp…", stays on one line under the face (it ran under the name label on rail tiles), and its tooltip explains that the person's stream has not reached your relay from that relay yet.

**Latency is never shown below zero; "skips" spelled out (Kenton: "latency -1404 ms ... Also, what does the skips mean?").** Each page corrected its clock to its own relay host, so a publisher on one relay and a viewer on another compared two host clocks, here 1.4 seconds apart. Every relay now measures its clock against the hub's (every 3 minutes, best of three round trips) and hands that to its pages, so the whole fleet reads one clock. A reading that still comes out below zero (a publisher on an older KASTR, or a relay that has not measured yet) says "latency: clocks out of step" instead of a number. "skips 0/1" is now "dropped 1 video": chunks of audio or video the player threw away in the last minute to catch up after falling behind, counted for the whole page.

**Relay boxes start with web clients off (Kenton: "When setting a device as a relay, keep web-client access off by default").** Switching a device to Relay or Publisher + relay mode turns its Web clients switch off; the Relay page turns it back on. A relay that already serves web clients (the tunnel's hub) keeps them across updates.

**A grid's Audio and Pass through live on the grid (Kenton: "the audio toggle and passthrough toggle to be on the grid, and not on the separate shares when in a grid" -- "This should only change in the share menu").** In the Share menu's sources, a grid's header has Audio and Pass through switches (Pass through only when the grid has a camera that can pass through) that apply to every member; the member rows no longer show their own. Tile menus are unchanged.

## v0.21.36 — nearest relay at launch, play badge, gallery fits, grid cameras switch

**KASTR connects to the nearest relay at every launch (Kenton: "auto selecting a relay based on hops ... auto connect to the nearest private IP ... only select the Public IP when no private IP relay can be found").** At start-up a KASTR in Full or Viewer mode checks every relay it knows: the fleet's, its own recent ones, and any found on the network. A relay on a private address always wins over a public one; among those, fewer network hops wins, and response time breaks a tie. A public address (such as a tunnel) is used only when no private relay answers. Hops are read from one ping's reply (the same hop count a traceroute gives, in a single round trip); a relay that does not answer ping is ranked by response time after those with a known hop count. A toast names the relay it switched to. Camera boxes and relay boxes (Publisher, Relay, Publisher + relay) never switch on their own, and a page reload inside a session does not switch. Measured from this laptop: all seven known relays ranked in 1.7 seconds (mendon-relay 1 hop, logan-roc by time because it does not answer ping, the offline ones last).

**The gallery fits the window and centres only its last row (Kenton: "The user windows should not center justify unless they are the bottom row ... They should also not push off the screen, they should resize to fit").** The gallery planned its layout from three lists (my own panes, other people, view-only tiles) and assumed their on-screen order; when the real order or count differed, a middle row was centred and tiles spilled below the window. It now counts the tiles actually shown, in their real on-screen order, re-sizes when the count differs from the plan, and centres only the true last row. Tested with 7 tiles at 1440 x 900 and 1000 x 620: 3 + 3 + 1 with only the single last tile centred, every tile inside the stage, no scrolling.

**One switch for all the cameras in a grid (Kenton: "Ability to stop all of the cameras in a grid with 1 toggle").** Each grid's header in Sources has an on-air switch: off stops every camera in that grid (their relay pairs and previews; the grid keeps its seats), on starts them all again. The grid's ⋯ menu has **Turn off all cameras in this grid**. While all of a grid's cameras are off the grid leaves the stage, so its switch in Sources turns them back on. Tested with two test feeds: off stopped both on the server and removed the grid; on brought both and the grid back.

**A play badge on rooms with video on the air (Kenton: "another symbol on the circle of a room to denote that there is an active video stream. Maybe a play icon in the bottom right of the circle").** A room's round bubble in the rail shows a green ▶ at the bottom-right while anyone in it sends a picture: a camera that is on, a share, a media file, or a camera box's RTSP feeds and grids. A camera switched off does not count. To make room, the lock badge moved to the top-left; the ∞ stays at the bottom-left and the people count at the top-right. Each page now reports how many of its sources send video; a page older than 0.21.36 counts as video whenever it publishes anything. Tested: the ▶ appeared when Alex turned his camera on and went when he turned it off.

## v0.21.35 — rooms survive a dark hub, chat new means recent, steady spotlight

**Rooms stay visible when the hub is down (Kenton: "Store a local copy of the rooms on each relay, so if the hub goes down, they are still visible").** Every relay asks the hub for its room list once a minute and keeps a copy on disk (`hub-rooms.json` in its state folder), not only in memory. A relay restarted while the hub is offline still lists the rooms, marked as the hub's last known list. Tested on the lab pair: with the hub stopped and the spoke restarted, the spoke still listed the hub's kept room; it went back to live answers when the hub returned.

**A standing spotlight applies when you come back (Kenton: "I'll leave the room and come back and the spotlight will not be set anymore").** Since 0.13.3 a spotlight older than ten minutes did not pull the stage of someone (re)joining, a guard from before anyone could remove a spotlight. Now that **Remove spotlight** exists on every tile, the guard is gone: a standing spotlight applies to everyone who joins or rejoins.

**The rail and the tiles agree on who is publishing (Kenton: "SR on the left shows publisher, but on the right shows view only").** For the room you are in, the room rail now marks someone as publishing only when something of theirs is on screen, the same rule as the view-only tile. Before, the rail believed the member's status ("publishing something") even when nothing of theirs arrived. Other rooms in the rail still use the status, since there are no tiles to compare.

**Chat "new" means recent and unseen (Kenton: "Chats should show new chat until seen or for a certain amount of time, not for everyone new to the room").** The chat badge counted every message newer than the last one you had seen, so someone entering a room for the first time got its whole history as new. A message now counts as new while you have not seen it and it is less than 15 minutes old; older unseen messages drop out of the count on their own. The "new" line inside the chat panel follows the same rule. Tested: a newcomer to a room with two 2-hour-old messages and one fresh one saw a badge of 1 (it would have been 3).

**Room timers without seconds, no symbol after the time (Kenton: "remove the seconds on the room timers and also remove the symbol after the time to denote locked or keep. The symbol on the circle should be indicator enough").** The room rail and the room banner count hours and minutes (`1:05`); Room info still shows seconds. The lock and ∞ badges on the round room bubble are the only markers now.

## v0.21.34 — no room question, fleet relays listed, no rail grip without a rail

**No room question on the join card (Kenton: "remove the room option and have everyone join main by default and whatever room they were in last after that").** The Room row is gone. The first join goes to `main`; after that, to the room you were last in. If that room has closed, or it is locked and its code was not saved on this computer, you land in `main`. A Share invite link that names a room still opens that room. Rooms are switched from the room rail once you are in.

**The fleet's relays are always listed (Kenton: "automatically prefill these relays and show as normal, if they are online or not").** 10.10.105.190, 10.13.20.196, 10.126.104.2 and 10.11.252.203 (port 4443) appear in the join card's Relay picker and the Relay menu, after this computer's own recent relays, each with its online dot and its name once it runs 0.21.33 or later. They are offered, never switched to automatically: the automatic failover still only picks a relay this computer has used.

**No rail resize handle without a rail (Kenton: "When in full window on a share, I can still mouse over and get the resize on the rail").** The handle is hidden in Fill window, full screen, focus on content, and when everyone is in the spotlight grid. Also fixed: with the spotlight grid on the stage, the rail's page buttons sat in the grid's columns instead of under the rail.

## v0.21.33 — frozen grid cells restart, relay names, short relay addresses

**A frozen camera in the grid restarts itself (Kenton: cells stuck for hours, e.g. Main Track at 3:32 AM while the rest were live; "when I click on those previews, it shows the up to date / full quality video. But when I exit ... it goes back to the stuck frame").** Each grid cell is drawn from a small preview player on the box that runs the grid. Its health check watched two things: data arriving, and the playback time moving. A player whose decoder stopped producing pictures (a camera's mid-stream format change, such as a night/day switch, can do this) still got its playback time moved every few seconds by the code that keeps it at the live edge, so it never counted as frozen. The check now also counts the frames the player actually decodes. No new frame for 12 seconds while data is arriving restarts that preview. A second freeze within 10 minutes switches it to KASTR's converted H.264 preview, which survives such changes. A page whose window is hidden and decodes nothing at all is not treated as frozen. Lab, with two test cameras in a grid and one preview's frame counter pinned: it restarted after 14 seconds, switched to the conversion on the second freeze, and was live again at 30 seconds; the other camera was untouched.

**Relay names in the relay lists (Kenton: "show the name of the relay rather than the IP address. Maybe keep the IP if hovering").** The join card's Relay picker and the Relay menu's recent relays show each relay's name (the one set on its Relay page), with the address on hover. Names are remembered on this computer, so an offline relay keeps its name. A relay without a name, or an open relay without access codes, still shows its address.

**The dot says online or offline (Kenton: "just let the color of the notifier tell whether it is online or not").** The words "online"/"offline" and "Available"/"Not available" are gone from both lists; the green or red dot says it, and hovering shows the words with the address.

**Type a relay's address the short way (Kenton: "allow people to just type the IP and have it autofill the http:// and the :4443 ... If they type :4444 it should not auto-add :4443" -- "If they type the full URL, it should still accept it").** In the join card's Relay field and the Relay menu: `10.0.2.14` becomes `http://10.0.2.14:4443`; `10.0.2.14:4444` keeps 4444; a full URL is used as typed; a tunnel address ending `/relay` gets `https://`. The server applies the same rule. (The federation hub field on the Relay page already accepted a bare address.)

**No list of code kinds on the join card (Kenton).** The access-code field no longer says "viewer, publisher or admin code".

## v0.21.32 — several spotlights, downloads ready, web clients off on relays

**Several spotlights share the stage (Kenton: "If multiple things are spotlighted, they will both show in the main viewing area in a grid format, similar to the RTSP grid").** **Spotlight for everyone** now adds to the spotlight instead of replacing it, with no limit. Two or more spotlit things share the main stage as a grid: the best-fit columns for the stage, like the gallery, with a short last row centred. Everyone not spotlit stays in the side rail; when everyone is spotlit the grid takes the whole stage. Every spotlit tile is heard and gets main-stage stream treatment. **Remove spotlight** on a tile takes just that one out, for everyone, whoever set it; with one left it holds the stage alone, and with none the room goes back to the gallery. Clicking another tile or the Gallery pill leaves the grid on your page only; the next change to the spotlight brings it back. Pages on 0.21.31 still see the newest spotlight, so a mixed room works during the rollout. Tested with two people: spotlighting each other's cameras gave both a two-cell grid; a third item (a test feed) made a 2 + 1 grid; one person removing the other's spotlight regrouped both pages; removing the rest returned both to the gallery.

**Web clients can be turned off on a relay box (Kenton: "I don't have the ability to turn off the web client toggle" -- "I am going to turn it off on most relays").** On a box in Relay or Publisher + relay mode the switch was locked on: such a box has to keep its web port on the network, because spokes reach the hub there for updates, rooms, chat and federation. The switch now works there and does what it says: Off stops handing the KASTR page to browsers on other devices, which see "Web clients are off on this relay". KASTR apps and federated relays keep everything they use (every /api/ route and the /relay connection), and the box's own window is never refused. It takes effect at once, with no relaunch, and is saved as `web_page = off` in kastr.ini. A box with web clients off also skips preparing the install downloads.

**The app download is ready before anyone asks (Kenton: "Why can't the app download be readily available instead of having to prepare it?" -- "Only to boxes that serve the webpage").** A box whose web page is open to the network (Web clients on, or a relay mode) now builds both install zips (Windows and Linux) in the background, starting 2 minutes after it launches, one at a time, and keeps them until the next version. A visitor's Download starts at once instead of "Preparing the download on the host". A box that only serves its own window builds nothing. Measured: about 12 seconds per zip from a fresh install folder (306 MB Windows, 284 MB Linux); about 600 MB of disk on those boxes. If the other platform's files have not arrived on the box yet, it looks again every 2 minutes.

## v0.21.31 — GoPros that play, dark cameras stay out, quiet camera boxes

**A GoPro that says "Live" plays (field: "no video from the bridge").** The stream from an RTMP ingest was copied as it came, so every reader (the preview, the publisher, a viewer joining late) had to wait for the device's next keyframe, and a reader that had stopped analysing before that keyframe failed outright ("dimensions not set"). KASTR now re-encodes the picture once, as it arrives, with a keyframe every second; the device's sound is passed on untouched. Lab, with a push whose keyframes came only every 10 seconds: on 0.21.30 one preview failed and the others took 5–7 seconds; now every preview starts in about 3 seconds, even with keyframes 20 seconds apart.

**The RTMP row says whether the device is connected.** Under the push address: "Waiting for the device to connect" (adding "the firewall is closed" when it is), "Receiving from the device", or "The device stopped pushing — waiting for it to come back". A toast says when a device connects. An ingest with nothing pushing is waiting, not failed, so the red "RTSP source failed — no video from the bridge" no longer appears for it.

**Open the firewall for RTMP from the feed itself (Kenton: "it should either automatically ask to open the firewall, or give a button to allow through the firewall without having to go to the relay server page").** On any box, relay or not: after an RTMP ingest is created, KASTR checks the firewall and, when TCP 1935–1944 is closed, asks whether to open it (Windows asks for permission). Cancel leaves an **Allow through firewall** button on the feed's row. Only the RTMP rule is added, never the relay's ports, and the firewall record keeps both.

**A camera that is dark at night stays out of the grid (Kenton: offline cameras "pop back up in the grid showing that it is on attempt 200 or 300 ... They shouldn't open back up until they reconnect").** A camera dropped from a grid came back when its publisher had merely been running for 5 seconds. Against a dark camera, one attempt can hang that long, and the relay lists the camera before any video arrives, so neither proves anything. The bridge now tracks when the camera's video last grew (ffmpeg's own progress report), and a camera rejoins only while video is actually flowing. Lab: a camera that accepted connections, held them 8 seconds and dropped them, next to a real one. On the old rule it came back after 32 seconds while still dark. Now it stayed out for the whole 3 minutes through 10 attempts, and rejoined 8 seconds after it streamed again.

**The latency label no longer covers the name (Kenton: "the latency when shown is covering the muted icon and the window name").** It moved to the tile's top-left corner.

**A relay or publisher box shows a camera only when one is shared (Kenton: "the southridge relay is showing up as a person due to it having OBS saying that it has a camera").** A box put its camera on the air whenever the machine had one, even switched off, so OBS's virtual camera made an avatar tile. A box now joins without its camera unless the camera or mic was turned on there, and turning a box's camera off takes it off the air.

**The join card's room picker is a dropdown again (Kenton: "I still only want 1 showing except when I click the drop-down button").** 0.21.30's open list is gone. The room rail stays hidden while the join card is up.

**A symbol for rooms that stay open (Kenton: "don't put the always open in the rooms, just put a symbol to denote that it will stay. Similar to the lock symbol for the locked rooms").** In the room rail, a room kept open shows ∞ next to its time instead of the words "always open", and a small ∞ badge on its round bubble (the lock badge sits on the other side). Hovering the ∞ says "Stays open when everyone leaves".

## v0.21.30 — GoPro previews, rooms in the join card, Remove spotlight

**A GoPro on RTMP ingest no longer fails with "bind failed: Error number -10048" (field report).** A camera on the host or an RTMP ingest is received once and handed on over local network ports, one port per reader. The monitor had a single port, so a second monitor of the same feed failed at once. A second monitor appears when a monitor reconnects while the old one is still closing, or when the window and a web client on the same box both show the feed. The capture now feeds six monitor ports, and each monitor takes a free one. The ports also come from below the range Windows and Linux hand out to outgoing connections, so another program can no longer take one first. A restarted publisher waits for the old one to exit before it starts. Lab, with a test push into an RTMP ingest and three monitors at once: on 0.21.29 the second and third died immediately; now all three get the stream, and so does a monitor restarted the moment the old one was killed.

**The rooms are in the join card, not behind it (Kenton: "show the rooms in the launch window, but don't show them in the backdrop on the side").** The join card lists the rooms instead of a dropdown, each with its lock, how many people are in it and whether it is kept open, with **+ New room…** last. The room rail on the left is hidden while the join card is up.

**The relay picker shows which relays are online (Kenton: "the launch page is no longer showing which relays are online or not").** Every relay in the join card's Relay picker is checked (the same check the relay failover uses) and marked 🟢 online or 🔴 offline. The answers refresh every 20 seconds.

**Remove spotlight (Kenton: "If something is spotlighted already, then the spotlight button should show remove spotlight").** Every Spotlight item now reads **Remove spotlight** when that tile, share or grid is already spotlit: on other people's tiles, on your own panes and in a grid's menu. Two gaps came out while testing. The person who set a spotlight did not see it as spotlit on their own page, so they still got "Spotlight for everyone". And a removal only withdrew the remover's own vote, so someone else's spotlight stayed for everyone. Now your own vote counts on your page, and **Remove spotlight** clears it for everyone, whoever set it. Tested with two people: the setter removing it and the spotlit person removing it.

**Spokes check in every ~30 seconds (Kenton: "How often do the spokes report to the hub for a keep-alive? I think this should be more frequent").** A spoke used to re-register with the hub only when its relay started, a room opened or closed, and every 10 minutes, so the hub's "Last seen" could be 10 minutes old for a healthy spoke. Every spoke already holds a request open at the hub for kicks and commands, renewed every 25–30 seconds. That request now counts as the spoke's check-in, at no extra traffic. The hub's spokes table is current to within about 30 seconds, and a spoke unseen for 3 minutes (was 30) drops off the table.

**A field check for any box (tools/kastr-field-check.ps1 for Windows, .sh for Linux).** It is read-only and writes one text file: this KASTR's version and mode, relay, federation and cluster status (including what the hub's relay sees of this spoke), relay health, the hub's spokes table, and the relay and launch-log lines about the cluster. Tokens and codes are blanked.

## v0.21.29 — an RTMP address for a GoPro

**RTMP ingest (Kenton: "does a KASTR relay have an RTMP URL that I can point devices to, such as a go pro for streaming the video?").** Share ▸ RTMP feed ▸ **RTMP ingest (GoPro)…** creates an address like `rtmp://10.10.40.120:1935/live/<key>`. It is copied when created and shown on the feed's row with a **Copy** button. Type it into the GoPro app's live-stream settings, or any device that pushes RTMP.
- What the device sends becomes a feed like an RTSP camera: copied without re-encoding (H.264 + its audio), able to go in any grid, and kept after a restart. Nothing shows until the device pushes.
- If the device stops and starts again, KASTR listens again at once.
- The key is random per ingest, so nobody else can push into it.
- Each ingest gets its own port, from 1935 to 1944: one listener per port.
- The Relay page's **Add firewall rules** now also opens TCP 1935–1944 (one rule, "KASTR RTMP ingest") once an ingest exists.
- Plain RTMP only, not RTMPS. A device away from this network can reach it only through a forwarded port or a VPN.
Tested in the lab by pushing a looping clip with ffmpeg: it published and played, and a dropped and restarted push came back. A real GoPro was not tested.

## v0.21.28 — the join screen dims the whole page

**The join screen dims the whole page (Kenton: "the shadow in the back doesn't cover the whole screen, just most of it").** Since 0.12.0 the backdrop behind the join card started a fixed distance from the left, to leave the room rail clickable. That offset missed with the rail collapsed and on the web page, leaving a strip undimmed. The backdrop now covers the whole page, room rail included. Pick a room in the join card's own room list. Verified in the desktop window and on the web page.

**The Profile card no longer scrolls sideways.** The Last name field kept its natural width and pushed the card wider than itself.

## v0.21.27 — one-spoke updates that work, rooms only where they live

**The single Update buttons work (Kenton: "The single update buttons don't seem to be working on the federation page").** 0.21.26's per-spoke Update sent a new command that only 0.21.26 or later understands, and the spokes that need updating are exactly the older ones. The button now sends the ordinary update every KASTR version obeys, delivered only to the address that spoke registers from. Every other spoke sees nothing new. Two spokes behind the same address (one NAT) would both update. This needs the **hub** on 0.21.27; the spokes can be any version.

**Your camera can go in a grid from Sources (Kenton: "The camera source on Logan-ROC isn't showing in the sources section for me to add to a grid").** The toolbar camera runs inside KASTR's browser window and could not be a grid member, so Sources left it out. It now has a row with **Put in a grid…**. Choosing a grid turns KASTR's own camera off (a webcam opens only once) and adds the same device as a camera on this computer (0.21.26) in that grid, published like an RTSP camera. If the browser's camera name does not match a device KASTR can capture, it says so and points to Share ▸ RTSP feed ▸ Camera on this computer.

**Rooms only where they live (Kenton).** The spokes table no longer has a Rooms column: rooms are stored on the hub since 0.21.25. A relay connected to a hub no longer shows the Rooms panel. The hub, and a standalone relay with no hub, keep it.

## v0.21.26 — grids take any source, shares come back, locked rooms are temporary

**Grids take any source (Kenton: "The grids should allow multiple source types in them, including screen, window, tab, RTSP/HTTP, media file, etc").** A screen, window or tab share can be put in a grid from its row in Sources. It starts in **No grid**, so it never lands in your camera grid by surprise. Share ▸ RTSP feed now also offers **Camera on this computer…** and **Add media file…**. Either one becomes a feed published by this computer like an RTSP camera: it can go in any grid and comes back after a restart. A camera added this way is opened once by KASTR and copied over the loopback to its publisher and its grid preview, because most webcams can only be opened by one program. It has no background effects, and KASTR's own camera must be off if it is the same device. A media file loops. Tested in the lab with a test-pattern camera, an RTSP camera and a looping video file in one grid. A real webcam could not be tested here: the build machine's tool sandbox has no camera access.

**A box's camera shows for everyone (Kenton, Logan-ROC: "if a camera starts on a publisher+relay, it should show for everyone and act similar to an RTSP stream").** The camera of a Publisher or Publisher + relay box used to be hidden from viewers. It now shows as a camera feed: no person chimes, not counted as a person, and listed as "Camera box" in Participants. A box's webcam comes back after a relaunch only if it was turned on there: the camera button now remembers its last state for the box's auto-join. To put the box camera in a grid, add it as a camera on this computer (above).

**Shares come back after a relaunch (Kenton: "Reconnect a desktop, tab, window share when still available after a relaunch of KASTR. If not available, drop it").** A screen, window or tab share is now saved like an RTSP feed. At launch it comes back if the thing is still there:
- the same screen;
- the same window, or a window of the same program with the same title (closed and reopened);
- the tab with the same title, even if it moved.
Otherwise it is dropped, and the log says so.

**Window shares work minimized or maximized (Kenton: "I was getting an error on sharing a window until I maximized the window").** A minimized window has no size and paints nothing, so its capture failed. KASTR now restores it without taking focus (it stays behind your current window) before measuring and capturing it. Verified with a real minimized window.

**A share is not an RTSP stream (Kenton).** A screen, window or tab share now has its own row in Sources: a screen icon, a **Sound** switch for the computer's sound, no Pass-through switch, and **No grid** until you pick one.

**"RTSP Grid" is now "Grid"** (a grid holds more than RTSP cameras now), and the View menu section is **Grids and feeds**.

**Sources grouped by grid (Kenton: "tie those sources together ... Sort alphabetically. Grid groups should also sort alphabetically").** The members of each grid sit together under the grid's name, tied by a blue rail. Grids are sorted A–Z with their sources A–Z, then everything that is in no grid, A–Z.

**Locked rooms are temporary too, and "Keep" is now "Keep room open" (Kenton: "Locked rooms should be temporary also if not checked to keep").** A lock never kept a room by itself, but a locked room lasted a day after its last use. Every room that is not kept open, locked or not, now goes about 10 minutes after the last person leaves. The switch reads **Keep room open**, and such rooms are marked **always open**.

**Update one spoke at a time (Kenton).** The hub's spokes table has an **Update** button on every spoke that runs another version. **Update spokes now** says how many are behind, and turns into a quiet "All spokes up to date" when none is. Fixed alongside: the hand-over's re-point command now reaches spokes within a second. In 0.21.25 it was raised but never sent, and spokes only re-pointed when the old hub answered their next check-in (up to about 30 s).

**"connecting…" says more (Kenton: users stuck on "connecting").** A tile whose stream description never arrives now says, after its second retry, which relay is not delivering ("no stream from Mendon yet — retrying"). /api/diag lists every such tile with how long it has waited, its retries and the relay it came through.

## v0.21.25 — the hub owns every room, a hub can hand over, and drags you can see

**Every room lives on the hub and every relay lists it (Kenton: "They should all be stored on the hub and distributed to all relays to see. Some of them are storing on the relays ... I was on the Logan Relay and created a room. I couldn't even see it on the laptop I have connected to the relay").** Until now each KASTR kept its own room records, and a room was stored on whichever relay the creating page happened to use. Plain rooms (no code, not kept) were never stored at all: they existed only while someone was in them. Now a spoke forwards every room create, keep, lock, close and group change to the hub, and lists the hub's rooms, so every relay shows the same rooms within 30 seconds.
- **Plain rooms are stored too** and listed everywhere. One nobody has used for about 10 minutes goes away, unless it is kept. Everyone in a room keeps it alive while they are there.
- **A dark hub refuses new rooms** with "The hub is unreachable — rooms are created on the hub. Try again when it is back." Existing rooms keep working, and the room list shows the hub's last known rooms.
- **Rooms a relay stored itself move up to the hub** the first time it registers after the update. A name the hub already holds differently stays on that relay, and its log says so.
- **The spoke still checks its own codes and admins**, and vouches for them to the hub with its federation token, so a spoke whose access codes differ from the hub's still works.
- **Behind a Cloudflare tunnel:** since 0.21.17 a hub reached through its tunnel address silently skipped every room-lock check (its web port answered those calls as chat). Fixed.

**Move hub duties to another relay (Kenton: "when I toggle on a new hub, it will talk to the old hub, propagate to all relays the new hub info, and disable hub on the old hub, and keep it as a relay ... a pop-up ... move all chats, rooms, etc").** On a relay connected to a hub, switching **This relay is the hub** on opens a prompt that explains what will happen and asks for the address the other relays should use plus the fleet's admin code. Confirmed:
- the current hub checks the admin code and sends its rooms, room groups, chat history, access codes (as salted hashes — everyone keeps their codes) and active kicks;
- it tells every relay to connect to the new hub within a second (one that was offline is told the next time it checks in);
- it switches its own hub duties off and keeps running as an ordinary relay connected to the new one.
Shared files and recordings stay on the old hub. Tested end to end on the two-relay lab: the spoke became the hub, the old hub re-joined it as a spoke with a working federation token, both rooms and the chat history arrived, and a wrong admin code was refused.

**What you drag floats under the pointer, and a drag never highlights text (Kenton).** Dragging a tile to reorder, a room card in the sidebar, or a cell of your own camera grid now shows a semi-transparent copy of it under the pointer (at most 260 × 180): the live picture where there is one, the person's face or the room card otherwise. A click-drag anywhere on the page no longer selects text or picks up images. Chat, text fields and the Room info / About / Help cards stay selectable, so you can still copy from them.

## v0.21.24 — field fixes: the way back from a box mode, box cameras, the hub URL, the iPhone camera

**Every mode can switch back (Kenton: "no way to switch back from Publisher + relay to Full client").** The mode picker lived only on the Relay page. A Viewer or Publisher box hides that page entirely, and on a Publisher + relay box the only way in was a button at the very bottom of the Relay ▾ popover. **More ▸ KASTR mode and relay settings…** now opens the Relay page with the mode picker focused, in every mode, on the box itself. Choose a mode and press **Apply & relaunch**. Web clients never see it, since the mode belongs to the host.

**Publisher boxes with a camera or microphone show their controls (Kenton).** Publisher and Publisher + relay boxes used to hide the camera and mic buttons on principle. They now show the camera controls when the machine has a camera, and the mic controls when it has a microphone, and follow devices being plugged in or removed. A box without them looks as before.

**The hub URL no longer reverts (Kenton: "if I click outside of the field before saving, it reverts to the previous IP").** The Relay page refreshes every few seconds and wrote the saved hub address back into the field as soon as it lost focus. An edited address is now kept until you save it, and the page says "Not saved yet — press Save federation".

**An old hub stops acting as one (Kenton: Agg-Azure "showing all of the other relays as if they are still connected ... the hub toggle is off").** A hub kept every spoke that ever registered, forever. Its Relay page now lists only spokes seen in the last 30 minutes (live spokes re-register at least every 10 minutes) and says how many older ones are hidden. Spokes silent for a week are forgotten. When **This relay is the hub** is switched **off**, the relay refuses hub duties: spoke registration, the spoke long-poll that carries kicks and commands, and minting relay-to-relay tokens. Its spoke table is cleared and hidden. A relay that never set the switch keeps working as before, so the real hub cannot drop its spokes by accident.

**No bottom bar on Go Live (Kenton).** The "Autonomous Solutions, Inc. — internal tool" / Media over QUIC footer is gone from the Go Live page, in the desktop app and on the web portal.

**iPhone camera follows the phone again (Kenton: "in iOS the camera is locked to sideways orientation").** 0.21.5 drew iPhone cameras upright only when the phone could not hand camera frames to a background worker. Newer iOS can, so that check now said "not needed", and frames went out in the sensor's fixed sideways orientation whichever way the phone was held. Safari and every iOS browser (all WebKit) now always use the upright drawing loop, which follows the phone's rotation. Not yet verified on a phone.

## v0.21.23 — a Teams-style tile menu and Participants panel, audio first on a weak connection

**The tile menu reads like Teams (Kenton's screenshot).** A person's three dots now offer **Mute participant**, **Pin for me** and **Spotlight for everyone**, each with its icon; latency and the admin actions sit below a line. Pin and spotlight work on every tile, people included (before, only shares and grids could be spotlit). A pinned tile offers **Unpin**, a spotlit one **Stop spotlighting**. Mute participant is still the mute on this device; the admin's mute for everyone stays in the admin part. **Right-click** any user window to open the same menu (Shift + right-click keeps the browser's own). No "Fit to frame", as asked.

**People is now Participants (Kenton's screenshot).** One row per person: a round photo or initials, the name, a role line (Organizer for the kept room's creator, Presenting, View only, Camera box) and their microphone state, slashed when it is off. Hovering a row shows **⋯**, and a right-click opens the same menu as their tile. On top: a **search** box that filters the names, **Share invite** (copies a link that opens this room, on the tunnel name or this host's network address; the access code is still needed, and the join screen preselects the room from the link), and **In this room (N)**, which folds the list away. **Mute all** appears only with the admin code and asks every microphone in the room to mute. Per-stream volume and watch/park moved under **Streams and volume** at the bottom.

**Audio first on a weak connection (Kenton: "audio drop out for those on slow internet").** Until now, a listener short of bandwidth kept downloading every video in the room, and the audio lost. The page now has a two-step ladder. Late audio is first answered by the wider audio delay (0.21.9). If audio is still late after that, or the player had to skip audio, video from people not on the stage pauses and they show their face, with their sound still playing. If it is still struggling, shares and grids not on the stage pause too. What is on the stage — picked, pinned, spotlit or the opened camera — keeps its video, and no audio is ever stopped. After two quiet minutes it steps back, one level at a time, with a notice each way. **Audio settings ▸ Keep audio clear on a weak connection** turns it off. /api/diag shows the level. On the speaker's side, the publishing library already hands the measured upload to audio before video (priority 80 over 60) wherever the browser reports an upload estimate. **Measured first (WSL lab, relay 0.17.0, a 3 Mbit/s link carrying a 6 Mbit/s camera plus Opus):** the relay does put audio ahead of video — video collapsed to 0.1–7 fps while audio never stalled with it — but in about half the sessions it still dropped roughly one 20 ms audio frame in six (the 'choppy' sound), on the speaker's upload and the listener's download alike. Relay priority alone is not enough; video has to make room, which is what the ladder does. The speaker's side (weak upload) is next: listeners will report audio trouble back to the speaker so their camera steps down.

**Hub toggle on the Relay page (Kenton).** Federation now starts with **This relay is the hub**. On a hub, the spoke-only fields (hub relay URL, federation code, pull updates from the hub) are hidden. A relay that never said either way and already has spokes reads as the hub. Flipping the switch never restarts the relay unless it was federated to another hub (it then leaves that hub; the code is kept).

**Grid cells have a thin black border (Kenton: "a gap between the lower left of the grid and the lower middle").** Cell edges fell on fractional pixels (the canvas width divided by the columns), so two cells could leave a light seam where they met. Cells are now cut on whole pixels and every cell gets a thin black border (2 px between cells on a 1280-wide grid), so streams read apart at a glance.

**More menu, tidied (Kenton).** More now holds Record, Room info, Profile, **About KASTR & updates** and Help. Files and Chat live on the toolbar (a phone, whose toolbar has no Files button, keeps Files in More), and Video effects and Audio settings live under the camera and microphone chevrons. The Settings submenu is gone: Video output and Audio output still open from the camera and microphone menus (More video settings / More audio settings), and **Phone access** is removed — the web portal does that job now.

**"Join same-site relays automatically" is gone from the Relay page (Kenton).** The 0.21.22 network discovery covers what people used it for. The relay-to-relay LAN mesh it switched on stays off unless a box had it on already.

**Background noise removal is on by default (Kenton).** Everyone who never picked a microphone mode now gets RNNoise on top of the browser's own suppression, echo cancellation and gain control (about 40 ms more on the microphone). A choice made in Audio settings is kept. Where RNNoise cannot run, the page falls back to the browser's suppression for that session only, and tries again next time. Turning Noise suppression off and on again returns to background noise removal.

## v0.21.22 — latency only you can see, tabs from any browser, and a tidier launch page

**Latency is the viewer's private choice (Kenton: "white/black blocks again in the bottom right corner ... turn it on for myself on a specific stream and only I can see it").** Nothing is drawn into anyone's picture any more: the View menu's "Latency stamp on my shares" switch is gone. Instead every stream's options (the tile's three dots) offer **Show latency (only you see it)**, remembered per stream on this device. The number comes from the stream itself: the catalog's clock maps each decoded frame's timestamp to the moment it was captured, corrected by both computers' measured offsets to the relay host (each page now shares its offset in its room state). Measured in the lab: a camera at 340-360 ms glass to glass, a camera with background effects at 470-500 ms. Streams from a KASTR older than 0.21.22 are still read from their stamp strip while the fleet updates; a stream that carries no clock says so.

**Finding a live relay (Kenton: "if it doesn't detect a live relay, have it do a quick check over mDNS ... auto-switch to one that is online").**
- Every KASTR whose relay accepts other machines now **advertises it on the local network** (mDNS, `_kastr._tcp`) -- discovery only: its name, address, ports, whether access codes are required, its certificate fingerprint and version. No code, token or secret is ever in it, and joining still needs the relay's access codes. The Relay page has a switch to turn it off. (This is not the LAN mesh, which lets relays join each other and keeps its secret.)
- At **launch** the desktop app checks the saved relay. If it is offline, it checks the relays this computer used before and browses the network for about 1.6 s; it **switches on its own only to a relay it used before whose certificate still matches** what it saw then (one that moved to a new address counts) and says so in a notice. Relays it has never used appear in the relay list as **"Found on your network: ..."** -- one click, never automatic, because any box on the network can advertise anything and an access code typed into a stranger's relay would be theirs.
- **During a session**, a relay down for 15 s brings a notice with a **Switch to ...** button -- nothing changes behind your back.
- Web clients (browsers) cannot browse mDNS; this is the desktop app.

**Share a tab from any browser (Kenton: "share a tab ... pull from the active browser, chrome, edge, etc").** The Share panel has a **Tab** list (collapsed until clicked) of the tabs open in the browsers that are running -- Chrome, Edge and Brave tested; Firefox, Opera and Vivaldi written for but not tested here. A click brings that tab to the front of its window without taking focus, un-minimizes the window without activating it, and shares the window cropped to the web page -- no tab strip, no address bar. The share follows the window: switching tabs there shows the new tab. A browser window that is completely covered or minimized stops painting, so keep it visible somewhere.

**Still pages, windows and screens keep sending (found while testing tabs).** Windows Graphics Capture only sends a frame when the window repaints, and a still page never did -- the share never started. Every native screen, window and tab share now runs on a steady 30 fps clock that repeats the last frame, and KASTR nudges the shared thing to repaint just after the capture opens (a tab flips to a neighbour and back, a screen's cursor moves one pixel and back). Measured: a still test tab reached the viewer in about a second at a steady rate.

**No more black tiles without a face (Kenton's screenshot: John, Mikey and Support Laptop black, no initials, no chips).** A tile shows the person's initials and the camera/microphone chips from the stream's catalog. When a catalog subscription timed out (the library's "browser stream limit reached?" case in a busy room) it was never retried, so the tile stayed black for the whole call -- the 0.21.15 never-painted check only watched the stage, not the gallery or the rail. Now any shown tile without a catalog shows the person's face with "connecting..." after 6 s and re-subscribes at 12, 30 and 90 s; the catalog arriving clears it.

**Smaller things in the room.**
- **Your own preview stays pinned to the bottom of the rail** again (0.21.19 had pulled it up under the others).
- The Share panel's **Window** list starts **collapsed**; a click opens it (and only then are window thumbnails captured).
- **RTSP streams show no muted-microphone badge** -- grids, the cameras behind them and single RTSP feeds (each publisher now lists its RTSP paths in its room state); it covered the camera labels.

**The launch page.**
- **Download** is its own section below Go Live, with the Windows and Linux marks on its tiles; it disappears when the host cannot offer a download.
- A **phone** skips the launch page and opens Go Live directly (a tablet or a narrow desktop window still gets the launch page).
- The introduction and the Go Live card describe what KASTR does today.
- The section headings inside the page keep their spacing (Download and Relay server sat tight under the section above).

**Smaller things.**
- People in the sidebar's room list show an **eye** (view only) or a **broadcast mark** (publishing) instead of a circle or a triangle.
- The footer names the protocol actually negotiated, **moq-lite-06**, on every page (it still said moq-lite-05 from before the 0.21.17 upgrade), and a phone shows no footer at all.

## v0.21.21 — background effects on the NPU, and edges like the other apps

Kenton: "I would like to add the ability to use the NPU if someone has one for the video effects. Our blur is kind of bad at detecting edges of people compared to other apps." Two changes: a new renderer that every computer gets, and a better person model that runs on the NPU when there is one.

**Effects at the camera's full frame rate (Kenton: "very delayed ... about .5 seconds behind my actual movement").** Since 0.21.5 the background-effects loop lost its per-frame callback on its very first frame -- the size check that waits for two agreeing frames returned without re-arming it -- so effects ran on the 120 ms fallback timer: about 6-8 fps, choppy and visibly late, on every computer. Every exit re-arms it now. Measured with the stock clip as the webcam (25 fps): 25 fps with Standard, NPU and GPU alike (was 5-8 fps); the NPU matte arrives every ~40 ms and trails motion less (lighter smoothing for a matte).

**Clean edges and no halo, on every computer.**
- Background effects now draw on the GPU (WebGL2).
- **Edges:** the person mask is refined against the full-resolution picture with a guided filter. The edge follows hair and shoulders instead of a low-resolution mask stretched about 5x, which was the stair-stepped edge.
- **Halo:** blur mode blurs the background *without* the person in it (a mask-weighted blur), so the person's colours no longer smear into a dark halo around them, the other visible flaw next to Teams and Meet.
- Image, video and GIF backgrounds get the refined edge too.
- Computers without WebGL2 float support keep the previous drawing path automatically.

**The NPU.**
- Camera ▾ effects has a new **Processor** setting: Auto, NPU, GPU or Standard.
- **Auto** runs MODNet, a portrait-matting model (Apache-2.0), on the NPU when the computer has one: Intel AI Boost, AMD XDNA, Qualcomm Hexagon. Otherwise it runs on the graphics card, and otherwise on the standard model (MediaPipe, as before).
- The setting shows what is actually running, for example "Auto · running on NPU 64 ms".
- A forced NPU or GPU that isn't there says so and uses the standard model.
- Measured on a Core Ultra 7 265H with the stock clip as the webcam:
  - NPU 33 ms per matte in the lab (64 ms in the page, including preparing the frame);
  - GPU 9.5 ms (18 ms in the page);
  - today's model 10.8 ms.
- Running on the NPU frees the GPU and CPU for video.
- The model runs through WebNN, which the bundled browser keeps behind a feature flag; KASTR now turns it on. Its launcher passes one combined feature list, because Chromium honours only the last one given.

**Download tiles on the launch page (Kenton).** Beside **Go Live**: **Windows Download** and **Linux Download**, each with its size -- shown only for the platforms this host can assemble an install zip for; a first click prepares the zip on the host (the tile says so while it works), then the download starts. More > About lists the same downloads as just the platform and its size.

**Shipped files.** `assets/npu` (about 41 MB, all local, never a CDN):
- onnxruntime-web 1.30.0 (MIT), the JSEP build that carries WebNN;
- `modnet_fp16.onnx` (13 MB).

`vendor-npu.py` fetches them from pinned URLs, verifies each SHA-256 and writes their licences next to them, and `build.py` refuses to build without them.

**Seen in testing.** MODNet sometimes keeps an object touching the person sharp, for example the top of an office chair behind a shoulder. Choose Standard if that matters.

## v0.21.20 — share like Teams, and a stream that fills the window

Share content works the way Kenton showed it in his Teams screenshots. KASTR captures any screen or window itself, so there's no browser picker, and the encode runs on the hardware encoder. Presenter layouts put your camera with the content. While you share, a red border, a Stop sharing bar and a floating mini window are on screen. Also in this build: Fill the window really fills the window, viewers see your own preview as a corner tile in one-on-one calls, the room form's buttons are clearer, and grid camera opens survive an impatient second click.

**The Share content panel.**
- The header holds the title and **Include sound** on one row.
- **Presenter mode** has four layouts (Content only, Standout, Side-by-side, Reporter) and an **Add background** button that opens the camera's background effects.
- **Screen** shows a live thumbnail of every monitor, and **Window (N)** one of every window, refreshed every 3 s while the panel is open. Minimized windows show their name.
- One click shares the screen or window. Chrome's picker doesn't appear.
- Web clients, and hosts that can't capture natively (Linux and macOS for now), keep the Screen and Window tiles that open the browser's picker.

**Native capture on Windows.**
- The host captures with Windows Graphics Capture (ffmpeg `gfxcapture`), scales at capture time to fit 1920x1080, and sends a steady 30 fps. A still screen therefore keeps sending keyframes to people who join late.
- It encodes once on the box's validated hardware encoder (x264 otherwise), at 6 Mbit/s hardware or 5 Mbit/s x264 so text stays sharp, and publishes with `moq import` like an RTSP camera, as `.../screen.hang` or `.../window.hang`.
- Measured in the two-relay lab: the viewer on the other relay decoded 1920x1080 at about 28 fps.
- A screen share is never a grid member and never restarts after a relaunch.
- Starting one is allowed only from the computer whose screen it is. A web client's request is refused, and the picker's routes answer only to the machine itself.

**Include sound.**
- The computer's sound is captured with Windows process loopback that leaves out KASTR's own process tree. Viewers hear the video you share but never themselves.
- Measured: capture latency about 10 ms, about 1 % of one core.
- On Windows older than 10 2004 it falls back to the device loopback, which includes the room's sound, and says so in the log.

**Presenter mode.**
- **Content only** is the native share above.
- **Standout** puts you, cut out from your background, in front of the content at the bottom right.
- **Side-by-side** puts the content on the left and your camera on the right.
- **Reporter** shows the content as a panel with you large beside it.
- The page composites the host's 1920-wide screen picture with your camera at 15 fps. The cut-out uses the same segmentation model as the background effects.
- The composite is re-timed like the grid composite, and the computer's sound reaches the page from the host as an audio track.
- Switching layouts while presenting takes effect at once.
- All three layouts were measured reaching a viewer on the other relay at 1920x1080.

**While you share.**
- A red border frames the shared screen or window and follows the window as it moves. It sits outside the window's edge, or inside at a monitor edge.
- A draggable top-centre bar says "You're sharing a window | Stop sharing".
- Neither appears in what you share; both are excluded from capture, and a real capture confirmed it.
- A floating, always-on-top mini window shows:
  - the elapsed time, and compact or normal size buttons;
  - camera, mic, people count and a red Stop;
  - your own tile (camera or picture);
  - a live preview of what you share.

**Fill the window (Kenton: "fill the whole window, like full screen, but without expanding the window itself").** In the desktop window the page lives inside KASTR's tab shell, whose tab bar stayed visible. The page now asks the shell to hide its masthead and footer too, so the stream gets the entire window: 1440x900 with the stream at 1440x810 in the lab, and nothing else shown. Esc, W or the tile's button brings everything back, and so does an Esc pressed while focus is in the shell. A reload never leaves the tab bar hidden.

**Your preview in the corner (Kenton's screenshot).** When one other person holds the stage and the rail would hold only your own preview, the rail goes away. The stage takes the full width (a 16:9 picture at 1173x660 where it was 1012x569) and your preview floats small in the bottom-right corner. A second person brings the rail back.

**Creating a room.** Create sits at the bottom left in blue, with Cancel beside it in the quiet style. This applies to both the sidebar form and the "+" bubble.

**Opening a grid camera on a slow link.** While a camera opened from a grid waits for its first frame, the cell fills the stage with a "full quality starting…" badge. Any click on it used to cancel the open and drop back to the grid, so an impatient second click restarted the cold subscription from zero every time. That fits the web client's "fails to consistently open". A click now keeps waiting, and the badge says it's still opening. Esc or the Back pill cancels.

**Open, not in this build.**
- A lab run with Chrome's network throttling made every subscription time out at only 50 ms of added delay. Chrome's throttle queues WebSocket frames, so this is unconfirmed until it's repeated behind a real delay proxy.
- The vendored audio library logs one harmless "disconnect" line when a share with sound stops.
- Native capture for Linux and macOS.

## v0.21.19 — fill the window, a full-screen button, wider rail previews, and viewers in the rail

Four requests from Kenton: one stream can fill the app window without going full screen, full screen is a button on the
tile instead of a menu item, the side rail's previews are wide instead of tall, and people who only watch show up in the
rail.

**Fill the window (Kenton: "maximize a video stream in the current window without taking up the whole screen").** Every
tile has a Fill-the-window button beside its options. The stream then covers the whole KASTR window at its own shape: the
header, sidebar, toolbar, rail and footer step aside, and nothing else on the page shows. The same button, W or Esc
returns to the room. Measured on a simulated 1440x1200 window: the stream fills the window's full width at 16:9 (1440x810)
with nothing else shown, and Esc restores the room view. It uses the same one-tile layout as full screen, so there are no
gaps, no border and no speaking ring.

**Full screen is a button.** Full screen left the tile's "⋯" menu and is now an icon beside it (corners out, or corners in
while full screen). F still works. The tile's buttons, from the right: options, full screen, fill the window.

**Wider rail previews (Kenton: "wider user previews rather than taller", with two Teams screenshots).** The rail used to
put two 156 px columns side by side and stretch the rows to fill the stage, so with a few people every preview was taller
than wide (about 156x215). The rail width stays the same, and the column count follows how many people are in it:
- While everyone fits, it is one column of 16:9 previews (320x185 at the default width).
- Once they don't fit, it switches to two columns of 4:3 previews (156x125). A lone last preview sits centred.
- Your own preview spans the rail right after the others, or stays pinned to the bottom when the rail pages.

Rows no longer stretch to fill the height.

**Viewers in the rail (Kenton: "viewers show up in the participant rail, but with an icon so others know they are view
only").** People who only watch (a viewer access code, or a publisher who joined without camera or microphone) get a
tile: their photo or initials in the person's colour ring, and an eye chip with their name. These tiles open no media
subscription and cost no decoding. They come after everyone with media, in the rail and in the gallery alike, and are
hidden wherever the rail is (focus on content, phones, full screen, fill window). The People list marks them with the
same eye.

**Still open (not in this build).** The web client's grid-open reliability; the camera/microphone detection check on
Kenton's desk; the "spawn error announcements are closed" lines in his diagnostics; Southridge's 4K cameras over the
thin link; subscription priorities.

## v0.21.18 — full screen that fills the screen, and a join that never hangs

Five field requests from the 0.21.17 rollout: full screen uses the whole screen, "Joining…" can no longer sit forever, every switch sits on the same row as its words, the Relay page stops breaking words in the middle, and a few stray `—` codes became the dashes they meant.

**Full screen fills the screen (Kenton: "it is leaving a lot of black space around the edges").** In full screen the
stage already showed only the chosen tile (0.21.17), but the layout still reserved the empty rail's width, capped the
height at the rail's row stack and kept the 8 px gaps and the tile border. Full screen now gives the one tile the whole
screen at its own shape -- no stretching, no border, no gaps; only the bands a different aspect makes unavoidable remain
(simulated 1440x900: a 16:9 grid at 1440x810, edge to edge, where it used 63 % of a smaller box before). The full-screen
look rides a `fsfill` class the layout sets from the same test, so CSS and sizing never disagree.

**"Joining…" never hangs (Kenton: "it sits on 'Joining…' forever and never joins").** Join now waited without a limit for
the camera permission, the access-code check and the room registration -- a camera that never answers (another app holding
it, a hidden prompt, no device) or a token service that never replies kept the gate on "Joining…" until the window was
closed. Each step is bounded now: the camera gets 8 s, then KASTR joins without it and says so (log + a warning toast;
Camera ▾ Enable devices tries again later); the access-code check and the room registration get 15 s each and fail with a
message that names the step. The gate shows which step it is on ("Joining… asking for the camera", "… checking the access
code", "… registering the room").

**Switches on the same row as their words.** The pages' generic form rule (`label { flex-direction: column }`) stacked every
label that holds a switch, so the toggle sat on one row and its text on the next (Share content ▸ RTSP, the per-feed Audio
and Pass-through switches, Keep this room). The shared stylesheet now keeps a switch and its words on one row on every page.

**The Relay page: no words broken mid-way, cards sized to fit.** `word-break: break-all` / `overflow-wrap: anywhere` let the
browser split any word at any letter; now only a token wider than its whole line may break. The spokes, rooms and streams
cards take two columns wherever the grid has them, table headers stay on one line, and the certificate fingerprint wraps only
between 16-character groups (copying it still gives one unbroken string). Measured: no mid-word break and no overflowing card
at 558, 860, 1024, 1280 and 1600 px wide.

**Stray codes.** Nine `—` placeholders on the Relay page (the LAN-secret label and the health values) and one tooltip's
`▾` showed as literal text; they are the dash and arrow they meant.

**Open from the field (not in this build).** Kenton's desk app reported 0 cameras and 0 microphones after the 0.21.17 update;
Windows saw only the laptop's built-in webcam and microphone as present (the C920 and the headsets were disconnected) and the
same page lists devices in a test browser -- being checked with Kenton. Viewers in the participant rail with a view-only icon
and the web client's grid-open reliability are next.

## v0.21.17 — the latest MoQ stack, and full quality across sites again

Part 41: Southridge's cameras never reached the hub in full quality and Tremonton's took seconds; the cause was in the relay, not in KASTR, and the fix is the newest MoQ release train -- which hides every '.'-named path, so KASTR's control paths move to '~'. Plus the locked-room bypass, full screen that shows only the content, no speaking ring on content, and two RTSP field requests.

**Why a single camera would not open across relays (found by measurement).** The hub's relay logged `no route can serve
the rest of this group ... err=old` on every pull from Southridge or Tremonton and received NOTHING -- not even the
1.6 Mbit/s grid composite -- while the same cameras played at 10-12.5 Mbit/s on Southridge's own relay. GSO off on
Southridge (`MOQ_QUIC_GSO=false`) changed nothing. Kenton's measurements gave the link: Southridge -> hub RTT ~60 ms
(48-81) with 1.2-1.4 % UDP loss at 20-30 Mbit/s (plenty of capacity), Tremonton ~22 ms with 0.2-0.6 %. A two-site lab
on Linux netem (WSL network namespaces, the relays' Linux builds, a 4K camera clip copied through like passthrough)
reproduced the field exactly: on a Southridge-shaped link moq-relay 0.15.1/0.15.2 delivered 12 -> 3.3 -> 1.6 -> 0.2
Mbit/s and a cold subscribe that lost its first group stayed dead (`no route ... err=old`, 3 of 4 runs), while
**moq-relay 0.17.0 held 13-14 Mbit/s and opened every pull in under a second (16 of 16)**. Larger QUIC windows, MTU
discovery, GSO off and loss-based congestion control did not rescue 0.15.x; 0.15.2 alone does not fix it. The 0.17.0
notes carry the fixes that matter here: a spliced group's end is asked from the seam (not frame 0), a group awaiting
its FIN ack still expires and follows priority, a relayed subscription's start resolves from its source, departed
subscribers are pruned.

**The new stack.** moq-relay 0.17.0, moq-cli 0.14.0, @moq/watch 0.6.2, publish 0.5.2, net 0.4.2, hang 0.5.2, json
0.4.2, signals 0.2.5 (fetch-helpers.py pins + SHA-256 from the releases' SHA256SUMS; vendor-moq.py pins). Every KASTR
moq argv parses on 0.14.0 (import ts, export fmp4, export hls); the bridge's refusal/bounce classifier reads the same
lines (`unauthorized` -> park + re-mint, `session closed, reconnecting` -> soft) and 0.14.0 now rides a 25 s relay
outage by itself instead of exiting; relay 0.17.0 accepts KASTR's generated relay.toml unchanged; the secured
federation (AuthService on both sides, spoke mints from the hub's federation code, pinned hub certificate) works in
every mix -- new/new, hub-new/spoke-old, hub-old/spoke-new -- so a hub-first rollout keeps the cluster up.

**KASTR's control paths moved from '.' to '~'.** Relay >= 0.15.3 never lists a path segment that starts with '.' to a
moq-lite-06 client (scoped or not), and @moq/net 0.4.2 browser publishers never announce one (the relay answers
`unroutable`) -- measured with a browser rig against relays 0.15.1/0.15.2/0.15.8/0.17.0 and both library trains. Every
presence, room-state, member, chat-nudge, spotlight, recording, media-control, grid, files, avatar, stall, admin and
channel path, and the relay's own stats prefix, now live under `~` (`~presence/<room>`, `~state/<room>/<HOST>/<PEER>`,
`<room>/<HOST>/~member/<PEER>`, `<room>/~since`, `~channels/<slug>`, `<room>/~admin`, `~stats/node/<name>` ...):
kastr_relay.NS is the one constant, the minter grants only '~' paths and says so (`ns: "~"` in the mint reply and
`/api/auth`), pages re-mint a token cached without it, relay.toml gets `[stats] prefix = "~stats"`, and the prebuilt
stats page bundle is retargeted at serve time (the file on disk stays byte-identical). '~' never occurs in base64url,
in a room/host/operator slug or in the `/api/watch` and archive path patterns, so no media or HTTP path can collide with
a control path; the side doors refuse both spellings. Mixed fleet: the hub updates first and its spokes follow it
within the hour (update checks ride HTTP, untouched); until a box updates, its pages and the updated ones do not see
each other's presence/chat state -- media keeps flowing.

**Library behaviour kept steady.** KASTR-PATCH audio-maxage-floor is re-anchored on the 0.6.2 player. New
KASTR-PATCH catalog-delay-cap: watch 0.6.2 adds each rendition's catalog `delay` plus measured `jitter` to the playout
delay, and publish 0.5.2 republishes both as lifetime maximums -- on the harness the RTSP grid advertised jitter 148 ->
369 ms plus delay 183 ms within 20 minutes, which would have put every viewer ~0.7 s behind live. The cap keeps
0.6.0's contract: video jitter = one frame interval (100 ms when the frame rate is unknown), the catalog delay ignored,
audio jitter capped at max(frame, 40 ms).

**A locked room is locked (Kenton: "a participant joined a locked room by trying twice").** The gate's "New room…"
and the sidebar's Create refused a locked room's NAME only when the code box was EMPTY; a second try with any code
built a fresh lock from the guess and walked into the existing room. Now a name that matches a listed room always
joins THAT room through its code check (never a create); the rejoin ticket checks the lock too; a lock whose hash the
page has not seen fails closed on an open relay (the secured minter stays authoritative); gate-created locks register
on every relay, so an open relay's room store refuses a second lock over a name; a room is remembered only after it
registered. Server side, locks were per box: a spoke's minter minted a hub-locked room for any code (measured 200).
Now a spoke asks its hub about any room it holds no record for (`POST /api/rooms/fed`, federation token, answers
cached 30 s when open), refuses a wrong code, fails closed for a room the hub said is locked while the hub is dark,
refuses to create a lock over a hub-locked name, and mirrors locks created on it up to the hub; and a member's
successful room-code mint keeps the lock alive past the 24 h record window (it used to lapse a day after the
creator's page left while the room was still in use). Live on the two-box harness: empty -> "That room is locked --
enter its code.", "guess" / "guess2" -> "Wrong room code.", the right code joins. Also fixed while here: a 0.12-shaped
wide VIEWER token was classified as a publisher (the role test only knew the member/since segments); any control
segment now makes a put a control path.

**Full screen shows only the content; rings only on people.** Making a share full screen now shows that tile alone --
no rail, own panes parked (the Focus-on-content path), even when started from the gallery. The speaking ring marks
PEOPLE talking: never on a shared media file, a screen or a camera feed (like 0.21.15's people-only chimes), and not
at all while focused on content or full screen.

**RTSP: names that stick, passthrough per camera.** A renamed camera keeps its name: the label is remembered per URL
(`kastr.rtsp.names`, mirrored by the prefs file) and every later share of that URL wears it -- re-add, another room,
Keep or not. Each RTSP row (and the pane menu) has its own **Pass through** switch that applies live: the one pair is
re-published copy <-> H.264 on the same broadcast path and grid seat (measured: the hub kept pulling it at 15 Mbit/s
right after the flip) and its monitor follows; the box-wide switch stays the default for cameras without their own
choice; the pane menu shows the current mode (`copy · h264` / `encode · h264`).

**Build fix.** fetch-helpers.py stamped binary versions by bare name (`moq-relay`, `moq`) although bin/ holds both platforms' binaries, so a Windows fetch of 0.17.0 marked the Linux 0.15.1 binaries current -- the Linux build would have bundled the old relay. Stamps are now per file (`moq-relay.exe` / `moq-relay`).

**Found, not changed.** `moq export fmp4` (every CLI version, 0.12-0.14) exits on a sample shorter than one tick at the
track's timescale (`cmaf: sample duration is shorter than one tick`) -- seen on a looping test clip; the /api/watch
fallback restarts its exporter. The 'fast start, then native' rendition (Part 41 Step 2) is deferred: on the new relay
the native 4K stream crosses the Southridge-shaped link at full rate.

## v0.21.16 — cameras off without forgetting, and the shared file's sound

Part 40: one switch turns a box's own RTSP cameras off and on to spare CPU/GPU, viewers are told why the cameras left, and the shared-media dropouts Kenton heard on 2026-10-02 are traced to the file player's pipeline.

**Cameras off, nothing forgotten: one switch for the box's own RTSP cameras.**

**Cameras off, nothing forgotten (Part 39 item 4, reading (a)).** One switch now turns this box's OWN RTSP cameras off
and on to spare CPU/GPU: Share content ▸ **Cameras** (header switch), View ▸ **Cameras off (spare CPU)**, the Relay
page's new **This box's cameras** card (for unattended boxes) and, on a hub, a **Cameras** column with an on/off button
in the spokes table. Off stops every ffmpeg|moq pair, low copy and owner monitor the box runs, stops drawing and
encoding every grid composite, takes each composite off air and withdraws its `grid:<id>` announce in the same tick --
viewers lose the cameras cleanly (no dead cells, no loose member tiles). Nothing is forgotten: the rows stay listed and
checked with a `suspended` badge, rtsp-feeds.json keeps every feed and now carries `suspended: true`, grid definitions,
seats, names and Keep stay as they are, and the same switch brings everything back (the page re-posts each feed with
the live token first, so the pairs start on it). Why there was no cheap off before: every restart path of a publisher
(ladder timer, park retry, token renewal, re-token, viewer/no-echo nudge, on-demand wake) funnels into
`Publisher.start()`, whose only gates were `stopping`/`standby`, and the only stop that kept anything (`sleep()`) is
on-demand-only -- so "off" meant `unpublish`, which forgets the record. Now `Publisher.suspend()/resume()` stop and
keep, `start()`, `nudge()`, `wake()`, the park tick and the renewal timer refuse while suspended, a publish request
meanwhile (adopt, restore, a token refresh) is recorded but not started, `Bridge.nudge` stays silent for a switched-off
camera, `GET /rtsp/<id>` answers 503, and the page's monitor ladder, grid eviction, viewer-stall rebuilds and
`syncNative` (which would unpublish) are inert. A relaunch comes back off: launch.log says `rtsp: publishing is
SUSPENDED on this box (rtsp-feeds.json suspended=true)` and `rtsp: recorded (publishing suspended) N persisted feed(s)`,
and the join gate says the feeds are kept but switched off. Every flip leaves one launch.log line (`rtsp: publishing
SUSPENDED by page|relay page|hub command #N -- P pair(s) stopped, M monitor(s) released, K record(s) kept` /
`... RESUMED by ... -- S of K pair(s) starting`), the grids note it in `/api/diag publisher.grids[].events`, and
`/api/rtsp/list`, `/api/instance` (`rtspSuspended`) and `/api/diag` (`publisher.rtspSuspended`) report it. A flip made
on the Relay page or by the hub reaches an open page through its feed poll (a monitor the bridge closed asks at once,
so even a page that is not live follows within a second); a local flip is shielded for 4 s from a poll already in
flight. The hub's `rtsp` command rides the bans long-poll command list like `closeRoom` and `wake` (two flips between
two polls both arrive), and the spoke re-registers right after so the column follows. Everyone else in the room learns
WHY the cameras went: the box's presence (the public `.presence/<room>` record and its state.json) carries
`rtsp: "off"` while the switch is off, re-announced on every flip at once (not at the next heartbeat); other pages
show a quiet line under People (`<box> — cameras switched off`, unattended boxes included) and one info-level
toast per flip (`Cameras switched off on <box> ...` / `Cameras back on on <box>.`; info toasts show with View ▸
Verbose alerts), never a chime and nothing on first sight; the tiles themselves leave exactly as before. Not an idle watchdog: only the
operator (page, Relay page) or the hub operator flips it -- no timer, idle rule or viewer count ever does, and the
on-demand machinery stays off (`ondemand = on` unchanged). No kastr.ini key: the switch is runtime state in
rtsp-feeds.json. `POST /api/rtsp/suspend` is loopback-only like its siblings; `POST /api/relay/spokes/rtsp` is a
guarded relay control. 26 unit tests (`tests/test_rtsp_suspend.py`, `tests/test_relay_rtsp_cmd.py`,
`tests/test_page_rtsp_suspend.py`) run in the build gate.

**Shared-media audio: no hardware encoder opens under the file player; a gap probe for the field.**

**Kenton, 2026-10-02: the sound of a shared file drops out every couple of seconds, for the sharer ('Hear it myself') and for every viewer.** The server side was already clean (a 60 s cut of the same stream: 2813 contiguous AAC frames, no gaps). Because the sharer hears it too, the fault had to be in the sharing page. So the rig tapped that page: an AudioWorklet beside the file's element source and another on the MediaStreamDestination track (the one the earpiece and the Opus encoder share), a 50 Hz trace of the <video> element, and logs of every SourceBuffer append/remove/abort/timestampOffset and every WebCodecs configure/close. Over 14 configurations (headless and headed with the real output device, the real 90 s cut and a 1 kHz tone control, a 7-minute file with the upload throttled, camera + RNNoise mic live, four RTSP test monitors, a full-core CPU burner, a 44.1 kHz context, 5-minute runs), the steady-state MSE player was clean. There were no rebuffers or reopens, no removes outside Chrome's own eviction, and no periodic dropout in the element output, the encoder track or the viewer's playout. The 2 s cadence did NOT reproduce here.

What does put silence into BOTH outputs at once is a stall of the file's own <video> pipeline: the share's sound is rendered by that element (createMediaElementSource -> MediaStreamDestination -> encoder + earpiece). The one repeatable staller is a hardware WebCodecs VideoEncoder being opened in the same page. A lab page (a plain <video> routed through WebAudio, no KASTR) measured this: every hardware encoder open stalled the playing element 138-279 ms (13/13 opens), against a 40 ms frame period. A software open took 22-41 ms, a bitrate-only reconfigure 0 ms, and a hardware VideoDecoder stalled it only on its first open. The first open after playback started came out as 50.7 ms of digital silence plus a `waiting` event. In KASTR the publish library closes a publication's encoder when its last subscriber leaves and opens a new one about 1 s later. So each demand change on the media composite stalled the movie 180-381 ms (31/32 subscriber churns over four runs; baseline 40 ms), and the first of each run cost 18-43 ms of silence on the sharer AND in the encoded audio.

0.21.16 steers the file composite's encoder to SOFTWARE. The library chooses hardware or software once, in its isConfigSupported probe, and reuses that choice for every later re-open. So the existing software-fallback shim also answers 'unsupported' to prefer-hardware probes for 4 s after `startFileMedia` hands the composite to the library, and again after every composite resize. Rig A/B, same churn (a viewer unsubscribes for 2.5 s every 6 s): hardware stalls 201-260 ms and 1 gap (32 ms); software stalls 40-42 ms and 0 gaps, at 25.6-26 fps and about 2.4 Mb/s encoded. `localStorage kastr.media.swenc = "off"` keeps hardware. The fix covers only the composite. A camera or grid encoder that re-opens in the same page still stalls the player, and the probe below names those openings.

Because the field cadence is unproven, the page now measures it where it happens. The `kastr-gap` worklet beside the file's element source reports every run of digital silence >= 10 ms after the first sound. Each gap is stamped with the media time, the element's `waiting` events and the VideoEncoder configure/close events around it. The results land in `__mediaDebug()[].audioGaps` / `gapCount` / `encoderEvents`, plus one launch.log line per 10 s that had gaps (`page: media audio: N gap(s) in 10 s on <file> (a-b ms, from t=... s); near: waiting xK, hardware encoder opens xJ; composite on software|hardware`). It caught 4/4 forced 160 ms holes at 160 ms, and gave 0 false gaps over 62 s of the real programme.

**The media share fed its pacer twice.** Since 0.21.14 the file share's draw loop pushed every frame with `requestFrame()` while the canvas's own `captureStream` capture delivered the same frames, so about 48 fps reached a 25 fps pacer: half were dropped, its queue sat full and viewers saw the picture about 2 s behind the sound. The push now fires only while the window is hidden or the automatic capture has gone quiet (a per-track arrival clock on the pacer), the same rule the grid composite follows.

**Found by the rigs and fixed before the build.** (1) A switched-off or unchecked camera's broadcast lingered at the relay for ~20 s because the pair's moq process was killed outright: KASTR now stops ffmpeg first, moq sees end of input and closes its broadcast in 0.03 s. (2) Viewers flashed an ex-grid member as a loose tile while its removal was pending; it now stays hidden. (3) A page that had left the room, or was joined but not live, never followed a switch flipped from the Relay page or the hub; the 3 s feed poll now runs whenever the page owns camera rows or is switched off. (4) A hub's Cameras column showed nothing until the spoke's next 10-minute registration; a spoke now re-registers when its first camera appears, its last one goes, and after the launch restore. (5) With another window covering the sharer, the media composite's automatic canvas capture throttled to ~13 fps and never went quiet, so the fallback push never fired: the composite now uses captureStream(0) with exactly one push per video frame and the file's frame rate passed to the pacer (covered and visible both 25/25 fps, queue max 3). Verified on the harness: the toggle rig 31 of 31 steps, the hub-to-spoke command (secured lab hub + spoke) in 0.22 s, the media churn 21-42 ms stalls with zero audio gaps and the pacer in = out; viewer picture behind sound fell from ~940 ms to ~485 ms raw. The remaining ~0.4 s is the viewer tile's 400 ms buffer, which delays video but not audio, on every tile class -- queued for the latency programme.

## v0.21.15 — the cell that never went black, and five fixes from the field

Kenton's Part 39, built from the 2026-10-02 measurements: a camera opened from a remote grid never shows a black pane; a grid whose cameras all go offline stays on the air; the Share-content row switch works again; the join/leave chimes ring for people only; a camera left off no longer warns about effects; the page's broadcasts keep 5 s like the native pairs, and the decode probe uses the whole rendition. The own-RTSP toggle (item 4) ships on its own as v0.21.16; the priorities programme follows.

**The switch that was a span: a camera row can be unchecked again.**

**Share content: a camera row could not be unchecked (since 0.21.0).** The row's On-air control became a brand switch in
0.21.0, but it was rendered as a `<span class="switch sm">` — the one switch in KASTR not inside a `<label>`. The shared
stylesheet hides a switch's real checkbox (`assets/asi-brand.css` `.switch input`: opacity 0, 0×0), and only a label's
activation behaviour forwards a click on the `<i>` face to it, so the click reached nothing and every RTSP row stayed
checked for good (keyboard Tab + Space still worked; the sibling Audio switch in the same row, a label, always toggled).
The change handler behind the checkbox is byte-identical to 0.20.0's and was never the problem. The control is a
`<label>` now, like every other switch. Unchecking a camera unpublishes its relay pair (`POST /api/rtsp/unpublish`),
closes its monitor (the 0.21.10 WebSocket pump ends with it) and drops it from the grid composite (its seat is kept; a
two-camera grid losing one member tears down to a loose tile, the 0.15.0 rule). The row says so in the status bar
(`Disabled <name> — relay pair unpublished, monitor closed, grid seat kept`), the box's launch.log carries the same line
as `page: Disabled ...` through the 0.21.5 `/api/rtsp/note` bridge (loopback only, so not from a web client), and the
room hears the source list change at once instead of at the next 4 s re-announce. Nothing in 0.21.10 was involved: the
0.21.9 → 0.21.10 page diff (144 lines) touches the row only for the on-demand gate and the `__rtspRerender` repaint. A
unit test (`tests/test_page_switches.py`, run by the build gate) now requires every `.switch` in both pages — plain
HTML, HTML strings inside JS and `createElement` builds — to sit inside an open `<label>`, and names the line when one
does not. Not changed, noted for item 4: an unchecked row does not survive a KASTR restart (the server's
`persist_feeds()` forgets the feed, the page's `rtspPersist` list re-adds it enabled), and a web client's uncheck
reaches the loopback-only unpublish route and is refused (it could never uncheck before either).

**A grid survives all of its cameras going offline.**

**Mendon's grid 2 cameras "split up in the presence" (2026-10-01).** When every camera on one switch went down together, the grid they belonged to vanished and the cameras came back one at a time as loose tiles on every viewer, flapping in and out as the server ladder retried them, until two were back and the grid re-formed. The announce was identical for grid 1 and grid 2; the bug showed on grid 2 only because a small grid loses all of its members at once far more easily.

**The cause was the 0.14.0 keep rule.** Since 0.14.0 a grid with one camera evicted lived on while one member was still up; with every member evicted it had zero live entries and `updateRtspGrid` tore it down. That withdrew the `grid:<id>` announce (viewers forgot the grid 2.5 s later and stopped hiding its members), emptied the hidden-member set on the owner, and let every reconnecting pair publish on its own path in mode Both and Grid alike. Readmitting the first camera gave one live entry and no grid object, so the `g && …` clause could never fire; only the second readmit rebuilt the grid. launch.log could not even say so: `gridNote` posts at most one line per 2 s per grid to the bridge, and the `torn down` note fired in the same tick as the last `evicted …` line, so the log shows `page: grid 2: evicted <camera> (publisher attempt N)` and then nothing about grid 2 until `page: grid 2: built …` when the second camera was readmitted.

**The fix.** A grid that exists keeps existing while any of its seats is evicted: `entries.length >= 2 || (g && evicted.length > 0)`. The composite stays on the air with one "cameras offline — reconnecting (N)" cell instead of a black frame, every seat is announced as `out`, viewers keep one tile and never see a reconnecting member alone, and the first camera back lands in a one-cell grid. Nothing else moves: Separate still withdraws every grid, a removed feed still clears its seat, a grid with nothing evicted still needs two feeds, and the one-down case behaves as in 0.14.0.

**Evidence.** The owner notes the transition once each way — `grid 2: all 2 members offline -- grid kept on the air, members hidden as out` and `grid 2: 1 live, 1 out` — in the status bar, in `/api/diag publisher.grids[].events` and in launch.log (`page: grid …` through `/api/rtsp/note`). The transition note resets the grid's 2 s bridge throttle (`g.noteAt = 0`) so it is not swallowed behind the `evicted …` or `readmitted …` line of the same tick; the `relayout` note that follows it is counted as `(+N more)` on the next line. Before the fix nothing about an all-evicted outage could be noted because the grid no longer existed. The viewer remembers for 60 s which paths a forgotten grid listed (`__switcher.state().gridForgot`, in the diag paste) and warns `KASTR: "<path>" was a member of <grid> N s ago -- shown as its own tile (owner withdrew the grid)` when such a path gets a tile of its own; this names the failure in a rig and in the field without changing what viewers see (Separate withdraws grids on purpose).

**For the rig.** `window.__gridSeats.evict(url, on = true)` evicts or readmits a grid member by hand and holds it (`evictWhy: "rig"`), because a harness test camera (`test://pattern`, lavfi) never fails on its own. The real ladder can still be proven by killing a pair's `moq` child from `rtsp-children-<pid>.json` six times inside 60 s.

**Field confirmation owed.** In Mendon's launch.log inside the outage window: `page: grid 2: evicted <camera> (publisher attempt N)` and then no grid-2 line until `page: grid 2: built …` (the `torn down` note was throttled behind the last eviction) confirms the trace; after the update the same shape of outage should show the `all N members offline` line, `readmitted …` lines, and no loose tiles. Known trade: a grid with one evicted seat and no live member now persists, and when that camera returns alone the grid tears down and it shows as a single tile — one layout change at recovery instead of loose tiles throughout.

**Join and leave chimes are for people only.**

**Kenton's Part 39 item 5: every RTSP camera, grid and pair restart rang the join and leave triads.** The chimes were tile-driven (0.8.2) and keyed by the operator segment of the path; every broadcast a box publishes carries its operator (`<room>/<HOST>/<op>/rtsp-test.hang`, `<op>/rtsp-grid.hang`, `<op>/screen.hang`), so a camera box's first RTSP tile was "the person `<op>` arriving", a pair restart (announce inactive, 4 s / 8 s removal debounce, announce active again) was a departure and an arrival, and the classifications the page already had (`isContentPath`, `boxHiddenPath`, `isGridChild`, `gridMeta`, `LOW_RE`) were never consulted by the chime.

One classifier now decides what a broadcast is: `pathClass(name)` returns `low` (a `-low.hang` thumbnail copy), `grid` (a composite), `gridchild` (a feed behind a grid), `content` (any leaf other than `camera(-N)`: RTSP cameras, screen / file / media shares), `box` (the camera of an unattended box, presence mode `publisher` / `publisher-relay` / `relay`) or `person`. The tile gate in `createTile`, the 0.21.2 late-presence sweep, the People head and `personChime` all read it. A chime rings only for class `person`; a JOIN is judged after `CHIME_SETTLE_MS` (1.5 s) with the tile still present, so a box whose presence lands after its camera tile (the 0.21.2 race) is known before the tone and a tile that flaps away inside the window is no arrival; a LEAVE is judged at once (it already sat behind the removal debounce). The first-in / last-out test counts the person's PERSON-class tiles only, so a person with a camera and a screen share rings once on arrival and once on departure (the camera's removal is the last person tile even while the share row is still listed) -- before, the share both suppressed the leave tone and rang its own. The room-switch fifth (`chimeRoom`, a user gesture) is untouched.

The People head for a group with no person-class row whose operator is an unattended box reads "Box -- 2 feeds (box)" instead of "2 streams". That head is painted inside the 1 s `applyState` loop, so it reads a cache (`tileClasses` / `boxOps`) that `reclassifyTiles()` rebuilds once per tile, presence or grid diff (`createTile`, `removeTile`, `roomsChanged`, `rebuildGridChildren`) -- the classifier itself walks the presence table and never runs per paint. Every chime verdict (played / held, with the path, its class and the reason: `not a person`, `already here`, `still here`, `debounce`) is kept in `chimeLog`; `__switcher.state().chimes` and `.classes` carry it, and the diag POST puts it in `/api/diag` as `watcher.chimes` / `watcher.classes`, so the field can say why a tone did or did not play without a log line per announce. Unit test `tests/test_chime_people_only.py` (page markers + the classifier table under node when present); rig recipe `v02115/rig_chimes.md` (an oscillator spy counts 3 per triad, 2 per room switch; `pw_chimes.py` is written from it).

**No effects warning for a camera that is off on purpose.**

A camera that is off on purpose no longer warns "Video effects unavailable — the camera produced no video track" half a minute after every join. Every camera starts paused (the meetings default in `addSource` and the join contract's `videoPaused`), and `publish.invisible` disables the vendored library's capture outright (publish@0.5.0: `#n = !invisible` feeds the Camera source's `in.enabled`, whose effect refunds and stops the getUserMedia tracks), so there was never a track to wait for — yet `loopWanted` read neither the pause nor the 0.8.6 auto-pause, `applyFx` armed `armFxOnTrack` 800 ms after every camera start whenever a saved effect, the latency stamp or the WebKit upright loop asked for the light loop, and the arm's 30 s give-up toasted. The loop is now simply not wanted while the camera is paused or auto-paused (`camOff(slot)` gates `loopWanted`, so `applyFx` stops the loop and never arms), a pause stops the loop (`stopBlur` before `invisible` flips, so the raw track handed back to the capture source is still live), and a resume re-applies it through `applyFx` — the stamp and upright loops included, which the 0.15.0 resume path (`a.fx || a.blur` only) had left out, so a stamp-only or upright-only camera resumed after the arm had died never got its loop back. An explicit resume also clears the 0.8.6 auto-pause: on publish@0.5.0 `invisible` ENDS the muted track, so the `unmute` that was meant to clear `autoPaused` never comes and the flag stuck forever (pre-existing; it had silenced the stall gates and the self-view's state). The auto-pause handler stops the loop too and its unmute path re-applies (probably unreachable on this library, kept for one that keeps the track). `armFxOnTrack`'s poll stands down quietly (`armOff` trace) if the camera is paused mid-wait by a path that did not pass `stopBlur`. A camera that is ON and still gives no track keeps the warning and now says which case: `fxNoTrack` reads the library's device signals (`permission` / `available` / `active`) — "camera permission is not granted", "no camera is connected", "the publisher holds the camera but its track never reached the encoder" — and when those only say a camera is there and nothing opened it, runs ONE probe getUserMedia of its own whose DOMException name the vendored publisher swallows: NotReadableError = "another app holds the camera (or its driver failed)", NotAllowedError/SecurityError = "camera permission was refused", NotFoundError/OverconstrainedError = "the camera is gone". A saved camera that is missing from `available` is a NOTE on the text, not a cause (the library's `device.requested` falls back to undefined and it opens any camera), and the probe then asks for any camera. A probe that succeeds means the publisher merely ran out of its four getUserMedia attempts (retry LIMIT=3, refused when the count exceeds it): it is nudged once through its enable gate (`invisible` true→false, the 0.8.6 stall nudge's lever) and re-armed, and only a second miss toasts. Every toast is guarded by `slots.has || camOff` so a camera removed or paused meanwhile warns about nothing. Rig and field: `window.__fxArms()` lists every camera slot's `{camOff, paused, autoPaused, invisible, loop, armed, failed, nudged}` (the existing `__fxDebug()` lists only slots that HAVE a loop), the same block rides each camera slot in `/api/diag` as `fx`, and `__fxTrace` gains `armOff` and `noTrack` entries. Verified on the bundled Chrome for Testing with the page served from disk (no relay): a camera born paused with the stamp on shows `applyFx` with loopWanted false, zero `poll` entries and no effects toast over 36 s; a stamp-only resume over the control channel starts the loop on a fake 1280×720 track and the pause takes it down without a toast; a camera turned on where nothing can be opened toasts once at ~31 s with "camera permission is not granted" and the status line carries the same text.

**The cell that never went black.**

**A camera opened from a remote grid showed a black pane for 1-45 s (Southridge: for ever).** A grid child holds a connection and a catalog but no video subscription; the cell click was the camera's FIRST video subscribe at the viewer's relay, and a cold pull delivers nothing until the camera's next keyframe (UniFi: up to 45 s). Meanwhile the composite was parked (canvas removed, `visible="never"`) and the library paints black while it holds no frame. Now the click shows the composite's own cell zoomed at once with the 0.21.7 'full quality starting…' badge (`gridOpenStart`), the camera subscribes OFF-STAGE (`visible="always"` needs no canvas: the library gates the subscription on the renderer's visible signal, which `always` sets without one, and `video.out.frame` lands on the first decoded frame), and the stage swaps on that frame (`gridOpenTick` → `select`). Only a tile that is currently subscribed may take the instant path: a parked child keeps the last frame it ever decoded under `visible="never"`, the library re-creates the decoder on the way back to `always`, and trusting that stale frame put a black pane on the stage (found by the rig; the swap also needs a chunk received since the click). The parked composite stays subscribed (`GRID_PARKED_WARM`), so returning is instant. The badge says which wait it is and for how long; a zero-byte wait re-subscribes once at 15 s and gives up at 90 s with a warn toast and a reason. The Gallery pill, a click / double-click / zoom-label un-zoom, a room change or leaving the composite abandons the wait; a hidden window holds its clock. Never on fallback (`<video>`) clients, which have no decoded-frame signal.

**A shown tile that never painted says why.** `stallReport` needs bytes > 0, so a tile with zero bytes (Southridge: SUBSCRIBE_OK, 0 bytes for 150 s; Tremonton: `remote error: 0`) was silent for ever. `paintNeverPainted` puts a `.pwait` notice on the pane 8 s after its subscription began ('no data from the relay' / 'waiting for the camera’s next keyframe'), re-subscribes once at 20 s with zero bytes, and removes the notice the moment a frame lands. It rides the 1 s tick BEFORE the bytes-advance `continue`, so it also clears while bytes flow.

**Full-config decode probe (P12c).** `decodeSupported` now hands the whole rendition (codec + hvcC/avcC description + container) to the library's `Video.Decoder.supported`, the same probe the player's decoder uses (with its avc3→avc1 retry), so a box without hardware HEVC shows the 0.9.2 face instead of a black tile that a bare `hvc1` string had approved.

**Retention follows the native pairs (P12a).** The page's Broadcasts (RTSP slots, grid composites, camera / screen / file shares) now carry `maxAge: 5000`, matching `moq import --max-age 5s`; hang's default kept 30 s of every page-published track at every relay hop. The archive (2 s) and the fMP4 fallback (4 s) ask for less than the window and are unaffected. The `<moq-publish>` element builds its Broadcast in its constructor, so the page sets `broadcast.in.maxAge` right after `createElement`, before `url`.

**Rig** (`rig_cell-open-ux.md`, hooks `window.__cellOpen()` / `window.__tilePicture(name)`): t_badge, t_swap against the predicted next keyframe, and the return time -- to be filled from the harness run.

**From the three bundles (Agg, Southridge, Tremonton, 2026-10-02).** The vendored publish encoder runs only while a downstream
subscriber has requested the track, so a flat composite frame counter means "nobody is pulling the grid from this relay", not
"encoder dead"; the 0.21.5 self-heal read it as a fault and rebuilt Southridge's composite four times in 22 minutes, each rebuild
being the subscribe close and restart every viewer saw. The viewer-stall gate now reads the encoder's `active` signal: flat and
inactive is noted (`nobody is pulling the grid from this relay ... not rebuilding`) and `/api/diag` carries `encoderActive` per grid;
flat and active is a genuine local stall and rebuilds as before. The Relay page's "Streams on this relay" probe opens a loopback
`role=relay` session every 5 s; its session-end lines were 96 to 100 percent of launch.log and the whole relay-log tail on every
box, erasing the cluster and subscribe evidence. Those sessions are counted (`auth.probeEnds` in `/api/relay/health`) and no
longer logged, and `/api/relay/status` carries `logRemote`, the relay's last lines without a loopback remote.

**Verified on the harness (bundled Chrome for Testing 153, rig relay, two test cameras).** Item 1: a pointer click on the On-air face unchecks the row, the pair unpublishes within 0.1 s, the status bar and `/api/rtsp/note` carry the line, re-checking publishes a fresh pair (18 steps). Item 2: with both grid-2 members evicted the owner keeps the grid (members 0, evicted 2, encoder ~15 fps), the viewer keeps one tile for the whole 60 s outage, the 1-cell and mosaic returns work, Separate and a removed feed still tear down. Item 5: 17 of 17 chime verdicts as specified (cameras, grids, pair restarts and a person's share silent; a person's arrival and departure ring once each). Item 6: no arm, no poll and no toast for a paused camera; the stamp loop resumes with the camera; the toast survives for an ON camera and names the case. Item 7b: badge at 0.00 s, off-stage decode, swap at 0.22 s on a warm relay with zero black samples on the stage, return 0.01 s, the zero-byte notice at 8.9 s and one re-subscribe at 21.9 s, every abandon path, the hidden-window clock hold. The rig also caught the stale parked frame (fixed before the build) and two swallowed evidence lines (fixed). Not reproducible on one box: a second-machine web client, a camera held by another app, the two-relay cold swap -- the lab measured that one separately.

## v0.21.14 — the push that went nowhere: a generator track has no requestFrame

**Southridge on 0.21.13, from its own diag.** Page 0.21.13, window reported visible, composite encoder frozen at 5362
frames with no growth in twenty seconds. Not a hidden-capture problem any more, and the harness could not reproduce it:
on the bundled browser the stream played through batched delivery, a spoofed hidden page, a publisher restart and two
forced grid rebuilds. The fault was in 0.21.12's own change. The 0.21.11 fix pushes a frame with `requestFrame()` on
the grid's track whenever the window is hidden or the encoder has stalled; since 0.21.12 that track is the pacer's
`MediaStreamTrackGenerator`, which has no `requestFrame()` (checked in the bundled browser: a canvas capture track has
it, a generator does not), so every push since 0.21.12 was a silent no-op. A window that is covered or minimised reads
"visible" under the app's own backgrounding flags while its automatic canvas capture stays silent, so the starved
check fired, the push did nothing and the encoder froze — on Southridge within minutes of each start.

**The fix.** One helper, `pushCaptureFrame(track)`, sends the push to the capture track behind a paced track (the
generator now remembers its source) and counts it in `window.__restamp.pushes`; the grid, the camera-effects composite
and the file share all use it. `/api/diag` now carries `publisher.restamp` (frames in and out, dropped, queue depth,
burst size, pushes) so the field shows the pacer's state without a console. A rig hook `window.__rigRebuildGrid()`
forces the grid's self-heal rebuild.

**Verified on the dev harness, bundled Chrome for Testing 153.** Pushes land only while the page is hidden or starved
(213 during a 12 s hidden phase, none while visible and flowing); encoder and viewer 14 to 15 fps in every phase. The
genuinely covered window is Southridge's to confirm: `publisher.grids[0].encoded.frames` growing while
`publisher.restamp.pushes` climbs.

## v0.21.13 — the pacer: a hidden window's frames arrive in batches, and now leave one at a time

**Southridge on 0.21.12, read at the tunnel.** The re-stamp was active (the composite's frames now carried the page's
own clock) and the picture was still frozen: the viewer decoded about one frame every two seconds — the keyframe
cadence — with a stalled buffer. The dev harness reproduced it once the captured frames were held and handed over in
batches: stamped at arrival, a whole batch sits within microseconds, and the publish library keeps one frame per
batch; spread across the frame interval instead, the earlier frames of a batch are stamped in the past and the library
drops them as late. A hidden document does hand its captured frames over in batches, so neither re-stamp could work.

**The fix.** The re-stamp pass is now a pacer: captured frames queue, and a timer releases one per frame interval,
stamped with the wall clock as it leaves. Steady delivery passes with at most one interval of delay; a batch plays out
as continuous video delayed by its own span; a queue longer than two seconds drops its oldest frames.
`window.__restamp` adds `qMax`, `dropped`, `gapMax` and `burstMax` so a box can show whether its capture arrives in
batches.

**Verified on the dev harness (two browsers).** With frames held for 1.5 s and released in batches, the encoder
produced 14.5 fps and a viewer received 14.4 fps of distinct frames, no drops, where 0.21.12 produced 1.2 fps; visible
and spoofed-hidden delivery stayed at 14 to 15 fps. The genuinely hidden case is Southridge's to confirm at the tunnel:
distinct frame timestamps advancing and a buffered range wider than a point.

## v0.21.12 — frames with a frozen clock: every canvas composite re-stamps what it captures

**Southridge on 0.21.11, read at the tunnel and on the box.** The 0.21.11 push worked as built: the composite's encoder
produced frames at 15 fps with the window hidden, and the box's own grid events said `window hidden -- composite frames
pushed by the timer`. The viewers still saw nothing. The probe at the tunnel showed why: the composite's frames arrived at
about 15 fps, in H.264, with every frame carrying the **same timestamp** — the player's buffered range was a single
point — while Mendon's composite arrived with advancing timestamps and played. A frame pushed into a canvas capture from
a hidden document is stamped with the time of the last visible paint, so the pictures were new and the clock was frozen,
and no player advances on a frozen clock. That was also yesterday's "bursts and holes": a visible window for a few
seconds, then frozen frames.

**The fix.** Every canvas composite — the RTSP grid, the camera-effects composite and the file share — now feeds the
encoder through a re-stamping pass: a `MediaStreamTrackProcessor` reads the captured frames, each is re-created with the
wall clock as its timestamp (monotonic, never repeating) and written to a `MediaStreamTrackGenerator` the library
encodes from; the generator reports the capture's settings so the encoder is sized as before. Browsers without those
interfaces keep the plain capture track. `window.__restamp` counts frames in and out and shows the gap between the
capture's clock and the page's.

**Verified on the dev harness (two browsers).** With the pass in place a viewer received 14.0 fps visible, 14.2 fps with
the publisher page told it was hidden, and 14.6 fps restored — identical to the encoder's output — with every frame
re-stamped and none dropped; the capture's clock sat a constant 11 s off the page's, which is why re-stamping is
harmless while visible. The genuinely frozen clock is Southridge's to confirm: the tunnel viewer's distinct frame
timestamps must advance while that window is hidden.

## v0.21.11 — the grid that drew into the dark: a hidden window no longer stops the composite, monitors follow the publisher's passthrough

**From the Southridge box's own diagnostics (2026-10-01, 0.21.10).** The grid composite's encoder had produced zero
frames since launch while the page reported itself hidden; the five camera monitors were healthy, the relay link to Agg
was up with no drops, and the box was registered with the hub. Viewers everywhere saw a frozen or empty grid because
the picture was never produced, not because of the cameras or the link. The grid is drawn by the KASTR window's page
onto a canvas whose capture stream feeds the encoder, and a hidden Chromium document — a minimised window, a locked or
disconnected console, the Go Live tab behind the Relay tab — silences the automatic canvas capture even though the
page's 15 fps timer keeps drawing. The file-share composite had already carried the cure since 0.16.0 (an explicit
`requestFrame()` after each draw); the grid did not.

**The fix.** After every grid draw the page pushes the frame itself whenever the automatic capture is silent: the
document is not visible, or the encoder has not advanced in 1.5 s although the timer is drawing. While visible and
flowing nothing changes. The camera-effects composite gets the same push when its frame clocks fall silent. The grid
notes `window hidden -- composite frames pushed by the timer` and `window visible again` in its event ring (and so in
`/api/diag` and launch.log), and the encoder sampler no longer counts a first reading of zero as "advancing", which had
let a viewer's stall report be dismissed with "grid live here" over an encoder that had never produced a frame.

**Monitors follow the publisher's passthrough.** The same bundle showed every monitor re-encoding — five software 4K
H.265 decodes, about a core each — although the cameras were passed through: the page asks for a copied monitor only
when its own localStorage switch is on, while the pairs had been restored from rtsp-feeds.json with the operator's
persisted `passthrough: true`. The monitor now copies whenever the camera's running publisher copies; a copy the page
cannot decode still falls back to a transcode on its own, so this only ever removes work. launch.log says
`rtsp monitor: feed N follows its publisher's passthrough (copy, hevc)` once per feed.

**Verified on the dev harness (Windows, Edge, two browsers).** A publisher with two test cameras and a viewer on its
grid: 14.3 fps at the encoder and 14.3 fps at the viewer while visible; with the page told it was hidden, 15.2 fps at
both — the explicit pushes do not double the rate when the automatic capture is also running; the grid events show the
hidden and visible transitions. The genuinely hidden case is the field's to confirm: on Southridge,
`/api/diag` → `publisher.grids[0].encoded.frames` must grow while `visibility` is `hidden`.

**On the box until then:** keep the KASTR window restored and its Go Live tab in front; the composite follows that.

## v0.21.10 — full quality always: on-demand pairs and low copies off behind one switch, the monitor outside the six-connection wall

**Kenton (2026-10-01):** "The video streams are better now all around, but not smoothly streaming. Maybe we should just
get rid of the on demand video and go back to full quality always for the time being. I think this may have been the
change that broke it. We also don't need the low quality for thumbnails." And: "This will also get rid of the egress on
the agg server for the announce of 400Kbps."

**Full quality always.** Every published camera runs its full pair from the moment it is published, as before 0.18.0.
No pair sleeps in standby waiting for a viewer, no 640-wide low copy is started, the two per-camera switches ("On
demand", "Low for thumbnails") are gone from the Share panel, a quadrant tap on a grid opens the already-published full
feed, and the demand plumbing (viewer page → relay host `/api/ondemand` → hub → spoke `wake`) goes quiet because nothing
asks and nothing sleeps. Each on-demand camera had cost the publishing box an always-on 640p encode, a third RTSP
session to the camera and wake/sleep churn against it, and every grid viewer pulled its low copy continuously — 400 kb/s
per camera per viewer leaving the hub. A relay pulls a full pair across the cluster link only when a viewer subscribes,
so full-always costs the spoke nothing upstream until someone watches.

**Behind one switch, not deleted.** The code and its tests stay. `ondemand = on` in the kastr.ini beside the exe (or
`KASTR_ONDEMAND=1` in the environment) brings both features back; it is read once at launch and launch.log says which
way it went (`ondemand: off -- every camera publishes its full pair always ...`). The demand travels camera box → relay
host → viewer page, so when it is switched on the key belongs on every KASTR of the fleet. Flags already stored in
rtsp-feeds.json and in the page's own memory are preserved and ignored, not cleared: a camera that asked for on demand
or a low copy is published as a plain full pair and logs `rtsp: <camera> asked for on demand/low -- ignored ...` once,
and the pair-reuse rule ignores those two flags while the switch is off, so a page reload never restarts a healthy
camera over a flag that has no effect. `/api/instance` and `/api/client` carry `ondemand: false`; the page hides the
switches, drops an older spoke's `-low.hang` announces and sends no demand. The 0.21.9 advice to switch On demand and
Low on per Southridge camera is withdrawn. `hook_read` no longer fires for on-demand wakes; it still fires for HLS and
fMP4 fallback viewers.

**The monitor rides a WebSocket — the six-camera wall.** From Mendon: "KASTR isn't letting me add more than 6. If I hit
add, it appears to do nothing. If I close another stream, I get the camera that I added and it shows up once for each
time I hit add." Chromium allows six concurrent HTTP/1.1 connections per host, and every camera's monitor stream on the
box's own page held one of them open for as long as the camera ran, against an embedded server that speaks HTTP/1.0.
Six cameras filled the pool; the seventh Add — and every other request the page made, prefs, the diag post, the feed
poll — waited in the browser's queue until a stream closed, and every queued Add then landed at once. The monitor now
rides a WebSocket, which sits outside that pool; the HTTP pump stays as the fallback for an older host, and the server
answers the browser's close frame so a detached monitor releases its ffmpeg reader at once instead of after Chromium's
60 s close timeout. `/api/diag` shows `monitor.ws` per slot.

**Verified on the dev harness (Windows, Edge).** Eight test-pattern cameras on one page: all eight monitors delivering,
all over WebSocket, the page's own fetch answering in 4 ms after each Add — before the change adds one to five answered
in under 10 ms and the sixth camera's monitor left the page's next fetch unanswered until the renderer gave up. A monitor
socket closed by the page released its ffmpeg reader in 1.5 s. The switch, off: `/api/instance` and `/api/client` say
`ondemand: false`, the Share rows carry no On demand / Low switches, a publish asking for both answers a plain pair
(`ondemand false, standby false, no low sibling`), re-publishing with different flags reuses the pair (gen unchanged),
and rtsp-feeds.json keeps `ondemand: true, low: true`. On (`KASTR_ONDEMAND=1`): the switches are back, the pair sleeps in
standby with its low sibling, and `/api/ondemand` lists it. Four unit tests in `tests/test_ondemand_switch.py` cover the
Publisher, the record and the reuse rule in both states; `build.py` runs the unit tests before every build.

**Rollout.** Hub first, as always — the version match also downgrades, so a 0.21.10 spoke under a 0.21.9 hub would be
put back. A spoke still on 0.21.9 whose cameras were set to On demand stays dark on 0.21.10 pages until it updates,
because those pages send no demand; update such a spoke first, or run the hub with `ondemand = on` for the rollout hour.

## v0.21.9 — audio that adapts to the path, the speaking ring and noise removal back, what a tunnel viewer really sees

**Measured from the tunnel (a web viewer at kastr.madlabs.app, 2026-09-30 afternoon).** Kenton's own camera audio
arrived late 21 times in 40 s on the multi-hop path (app → spoke → hub → tunnel host → browser); every late frame is
20 ms of speech the player drops, and a run of them is the "almost static" heard in a conversation. The Mendon grid
arrived at 15 fps with gaps under 0.2 s over the same last hop; the Southridge grid arrived at 1 to 2 fps in bursts,
with holes of 1 to 9 s — frames come in clusters at the encoder's 15 fps spacing and then nothing, the signature of a
starving or lossy link between Southridge and Agg, not of a slow encoder. The southridge room published only the
composite (no per-camera broadcasts, no on-demand feeds), so a quadrant tap had no full-quality camera to switch to.

**Adaptive audio delay.** A fixed 150 ms delay cannot know the jitter of the hops upstream of the viewer's relay. The
page now listens for the player's own late-frame reports and widens the audio tiles' delay a step at a time while they
keep coming (LAN 150 → 250 → 400 ms; through a web relay 150 → 300 → 450 → 600 ms), stepping back down after two quiet
minutes; each step is one re-tune. On the rig, through a proxy holding the connection 300 to 600 ms every 2 s, the delay
stepped to 600 ms and the late-frame reports stopped completely. `window.__audioDelay` and `state().audioDelay`
(in `/api/diag`) show the steps and the counts.

**The speaking ring and RNNoise were dead since 0.16.0.** The publish library moved the microphone into an
`Audio.Capture` at 0.5.0; the own pane's analyser tap, the noise-removal chain and its watch still read the 0.4 field
and got nothing, so the speaking ring never lit, the mic meter had no live tap, and every microphone went out raw
without the background-noise removal the operator had switched on. All three read the capture now; the analyser's
AudioContext is also resumed on the next gesture (an auto-join creates it suspended). `window.__ownAudio()` shows the
tap, level, context state and denoise state per slot.

**What to check on Southridge** (only that box can tell): `/api/diag` → `publisher.grids[].encoded` frame count and
`encFlatS` (a steady encoder), `/api/relay/health` → `federation.link` drops and re-pins, the relay log for
`cluster peer error`, and the box's CPU while OBS runs; a LinkTest between Southridge and Agg for loss and jitter. To
get full quality from a Southridge camera, publish the cameras as well as the grid ("both"), with On demand and Low
for thumbnails switched on per camera.

## v0.21.8 — the regression hunt: no restarts on a viewer's say-so, a fallback that stops asking, a fixed audio delay, the firewall check in under a second

**What the 0.20.0 → 0.21.x hunt found.** Six readers went over every change in the window and two skeptics
checked each finding; the code of the RTSP pipeline, the vendored player and the relay had not changed. What had
changed was the field: secured relays everywhere, phones and web clients through the tunnel, and a release a day.
Three pre-existing rules were being exercised for the first time, and every one of them turned a viewer's stall
report into a cut for everyone:

- **A native camera's pair restarted on a stall report with no evidence.** The 0.13.3 rule asked the relay whether
  it still listed the camera; a secured relay's listing is empty, so the answer was "no evidence", and the code
  treated that like "not listed" and restarted the pair. One starving remote viewer (a phone, the tunnel, two cluster
  hops) restarted a healthy Mendon or Southridge camera for every viewer every 45 s for as long as it kept reporting,
  and each restart starved more viewers into reporting. Now a running pair with no evidence against it is left
  alone and the report is written to launch.log (`page: pair <name>: viewer stall noted -- no relay evidence`); the
  server refuses a viewer-report restart of any pair that came up in the last minute (`rtsp nudge refused …`).
- **A speaker's camera and mic were torn down on a second stall report.** The camera-slot branch was the one
  report-driven rebuild that never got a gate; every listener lost that person for the seconds it took to re-acquire
  the devices. It nudges the encoder again instead; the encoder's own watchdog rebuilds when the encoder really is
  wedged.
- **The grid's eviction ladder could evict a camera whose pair was fine.** 0.21.5 let a pair vouch for its camera
  only after 60 s of age, and the restarts above kept resetting that clock. A pair vouches by state now: running,
  not in standby, no exit in the last 30 s; a running pair also readmits a monitor-evicted member.
- **Audio's jitter buffer on the LAN was the measured RTT alone (43 to 54 ms).** `delay: "auto"` sizes the audio
  ring from the RTT; `buffer` is only the skip ceiling. Main, rail and grid tiles ride a fixed 150 ms delay everywhere
  now, as web pages already did since 0.21.7.

**The bursts on KASTR-Test and Mendon.** A 250 Mbit/s spike every couple of seconds, with every viewer's session
appearing and vanishing together on the relay's stats, is a client re-subscribing to everything at once: each time,
the relay hands out the latest group of every stream (a full GOP of every camera), and the spoke's cameras are
pulled again over the cluster link. Two loops can do that and both are now bounded and visible: the fMP4 fallback
player (a browser without WebCodecs, or a codec it cannot play) asked again every 2 to 3 s and each ask spawned a
`moq export` child pulling the last 4 s of every track; it backs off now (3, 6, 12, 24, 48 s, capped at 60 s) and
stops after five failed tries with a toast, and the relay host refuses a fallback viewer that starts the same stream
three times in 30 s (429, `watch: fallback viewer <peer> is looping …`). The library's connection reload (1 to 5 s
back-off) re-subscribes every tile per reconnect; the page counts them (`window.__netEvents`, in `/api/diag`),
toasts past three a minute and parks every tile for 20 s past six. The relay host logs `/relay` pipes that lived
under 15 s (`relay pipe: <peer> opened N short pipes in 60 s`), the auth service counts session opens per remote
(`relay auth: <remote> opened N sessions in 60 s`), `/api/relay/health` carries `auth.churn` and the Relay page's
Auth line names the remote; the masthead reloads for a host update at most once per ten minutes. The tell in
KASTR-Test's launch.log is one of those lines; ask for it when the spikes are next seen.

**Also in this release.** The Windows firewall status check reads `netsh` (0.6 s, was 8 s) with the CIM cmdlets
as a fallback; a field host assembles the other platform's install zip by fetching the pinned Chrome for Testing
zip itself (browser.json ships in the app; About says "the host fetches the browser first"); the avatar circle is a
little bigger, its initials size from the circle (one letter 48 %, two 40 %, three 30 % of the diameter) and sit
centred, on remote tiles and on the own pane's standby face alike.

**Not regressions**, checked: the RTSP pipeline's ffmpeg and moq arguments, the vendored player and encoder, the
tile classes and budgets through 0.21.6, the relay configuration and its restart triggers, and the update paths.
Still to prove in the field: which loop KASTR-Test's viewer was in (the log lines above), and Southridge's
launch.log against a blackout.

## v0.21.7 — field fixes round four: the update port, no pane pop-up, download the app, click-to-picture, the spoke grid, audio that does not clip, a firewall prompt that stops

Seven items from the field after 0.21.6, each with its cause.

**The Relay dropdown expected updates on port 8000.** The masthead asked the server to probe the relay host without a
port; the server defaulted to 8000 and never consulted the hub web port every spoke already learns (Agg and Mendon run
their web on 8001), and the failure line was a literal `:8000`. Now the server resolves the base itself (a web relay's
origin, an explicit port, the learned base, the learned port, its hub default, in that order), a probe about this very
machine answers our own instance, and the reply says which base it asked; the line names that. A web client is on the
relay host's own web service, so its dropdown reads "Relay host: KASTR vX — this page follows it" with no port at all.
The Relay page's firewall hint and web-port line follow the server's port too, never the page's.

**A "which server" pop-up stuck on top of every window.** One line set a `title` on every remote pane, grid tile and
collage cell every ten seconds ("via <relay>"); the bundled Chrome drew it as an OS tooltip that outlived focus. The
titles on panes, labels, RTSP rows and grid rows are gone — "via" already lives in People.

**Download the app from the web client.** More → Settings → About lists Windows and Linux with the full install zip
(`KASTR-windows-v0.21.7.zip`, `KASTR-linux-v0.21.7.zip`). The host assembles the zip on the first click from what every
install already carries — its own binary and pruned browser folder, the other platform's mirrored binary and browser
zip, and the templates the feed now carries (`updates/<plat>/extras/`: `kastr.ini` and the Linux `README.txt`,
`install.sh`, `kastr.svg`; a host never ships its own edited `kastr.ini`) — with build.py's entry names and modes,
caches it under the state folder (`downloads/`, one release per platform, a sha sidecar), and streams it with a
`Content-Disposition` name. Routes: `POST /api/update/zip?platform=` prepares, `GET` streams (409 while building), the
manifest carries `zip` and `extras`, `/api/update/extra` hands out a template, binaries and browser zips get download
names. A page whose certificate the browser distrusts (a LAN https page without the local CA installed) has its
download blocked by Chromium itself; a trusted page — the tunnel, the LAN with the CA, plain http — downloads.

**Click-to-picture on an on-demand camera.** The low copy of an on-demand camera stays on the air in standby (one
RTSP pull and a 640p/15 fps encode per camera); viewers get a tile on it at once, under the camera's own name. A click
spotlights the low picture immediately with a "low quality — full starting…" badge and asks for the full pair, which
takes over in place when its announce arrives — no tile is torn down. A quadrant click on a composite whose feed has
no low copy fills the stage with the composite's own cell while the camera starts. Demand now travels the federation
the way bans and room closes do: a relay host that does not know the camera forwards the demand to its hub with the
federation token (`POST /api/ondemand/forward`), the hub pushes a `wake` over its command channel to every spoke, and
the spoke that registers the camera wakes it (Kenton's web client at kastr.madlabs.app → Agg → Southridge). A hub
before 0.21.7 answers 404 and the page says so instead of waiting 90 s. Rail thumbnails on the low copy ask for nothing,
so an idle camera stays asleep until someone actually opens it.

**Southridge's grid for remote viewers.** The likely cause is the cluster link itself: every hub restart mints a new
hub certificate, the spoke re-pins and restarts its relay, and the grid (and its `.member` state) blinks for everyone
downstream. The spoke now reads the link's state off its relay's own log — `relay federation: cluster link to <hub>
up|down (…)` in launch.log, `federation.link {up, since, drops, repins}` in `/api/relay/status` and `/api/relay/health`,
the Relay page's Hub line ("link up 12 m, 3 drops, 1 re-pin, hub sees 2 nodes") — and asks the hub what its relay sees
(`GET /api/spokes/link` → `federation.hubSees`). The owner page's viewer-stall gate reads both: a link that flapped in
the last 60 s is noted, not rebuilt. When the hub is unreachable the stored pin is kept and said once (no restart storm);
composites are a tile class of their own (`grid`, the rail budgets, never `instant`) and get an 8 s removal debounce.
Still owed from the field: Southridge's launch.log with these lines against the next blackout.

**Audio that clipped for everyone.** The library drops the oldest buffered audio group when the buffered span exceeds
`maxAge = delay + buffer`; every 20 ms Opus packet is its own group, legacy audio frames carry no duration, so one
skip registered as a discontinuity — the worklet ring was flushed, the shared sync clock and the decoder reset — and the
budget (200 ms on the rail tile everyone hears; the min-RTT estimate shrinking it further) made skips routine on a
tunnel or a two-hop path (`skipping slow group: track=audio` climbing). Four layers: a 1 s floor on the AUDIO consumer's
`maxAge` in the vendored player (video keeps the library's budget; `vendor-moq.py` now carries `PATCHES`, re-applies
them after every mirror, `--patch`/`--check`, build.py checks, `tests/test_vendor_patch.py`); rail 200 → 400 ms and
fixed web budgets (`delay 150 ms + buffer 800 ms` on main/rail/grid through a web relay — a tunnel, `/relay`); a
tile-class rule that never lands unknown audio on `instant` (which never subscribed audio at all — composites with
sound played silent); and `frameDuration` in ms (the ×1000 failed the library's check and the config was dropped). The
latency badge shows `· skips A/V` for the last 60 s and totals in its title; `window.__slowGroups` counts them.

**The Linux box asked for the firewall on every launch.** `ufw status` was run as the user ("need to be root" →
unknown → pkexec every launch), the web port was set after the check, and a substring match stood in for the ports.
Now the wanted set is computed first, `<state>/firewall-applied.json` remembers what an earlier launch added (or
printed once, headless), the checks are unprivileged and exact (firewalld `--query-port`, ufw's rules file, `ufw status`
as root only), a box with neither tool is told once, Windows joins the port filter so a changed port counts as missing
and each rule is removed before it is re-added (no duplicates). The Relay page names the missing ports.

**Verified.** Unit: the assembler on a scratch root (entry names, modes, prune, `browser/VERSION`, cache, stale sidecar,
old-version prune), peer/instance resolution, the vendored patch, firewall decisions with fake tools, the wake relay's
dedupe and hop rules, the link classifier. Harness rig (Edge): the app's Relay line names the host's version with no
`:8000`; the web client's line follows the host; no `title` on panes or labels; About lists both platforms and the
browser downloaded `KASTR-windows-v<ver>.zip` equal to the manifest's size with the release layout inside; a spoke's
on-demand camera showed on a hub-side viewer as a low tile at once, the truth badge, and the full copy took over 2.6 s
after the click with the spoke logging `hub relayed a viewer's demand … -> woken here`; a hub relay restart wrote
`cluster link … down/up`, `drops`/`repins` climbed and the Relay page said so; a viewer through a proxy holding the
connection 300–600 ms every 2 s heard 65 s with zero audio skips.

## v0.21.6 — a deleted chat line stays deleted

Found on the first secured live test at kastr.madlabs.app (0.21.5): an admin deleted a viewer's line, the host
answered 200, and the line stayed on every screen — the admin's own panel showed it again a moment later. Two causes
in the page's live chat window. A tombstone for someone else's line carries only the store id (the deleter has no
client id for a post that is not theirs), and the window handler dropped any record without a client id before it
looked at the tombstone flag, so no receiver ever removed the line. Then the window replayed the original post and the
deleter's own panel took it back, since nothing remembered that it had been deleted. The handler now honours a
tombstone by store id or by client id, whichever it carries, and every page remembers the ids it has seen deleted so a
replay cannot resurrect them. Verified on the rig: an admin's delete leaves the admin's panel and the viewer's panel
within seconds. Rooms whose chat is kept on the host were already fine, since their history is re-read with the
tombstone applied; this fixes the rooms that only live on the window, which is every room a web client creates.

**The secured half of the live test, done (0.21.5 at kastr.madlabs.app, relay "kastr-test" behind Cloudflare).**
Publisher, viewer and admin joined with their codes and got their roles; both state links connected over the
tunnel; the viewer listed both members, found the camera and decoded the tile and the latency stamp; the encoder
counted frames; chat crossed through the hub; an admin stop reached the publisher in 0.1 s and an admin kick sent it
back to the gate in 0.2 s while the viewer, behind the same Cloudflare address, stayed joined with its state link up.
The moq CLI published and pulled a test pattern through `https://kastr.madlabs.app/relay` over WebSocket as valid
H.264. The one defect it surfaced is the chat tombstone above. Every room the test created was closed afterwards.

## v0.21.5 — the iPhone that fits, an upright camera, a grid that stays up

Kenton's report after 0.21.4: on his iPhone (Safari, iOS 18) "things don't seem to be constrained to the visible
area, it's collapsing some parts and I can't resize", the camera is "always stuck sideways" for him and for every
viewer, the Southridge box's RTSP grid is steady on the box but remote viewers see it "go black, come back for a few
seconds, go black again", a camera that failed more than five times never left the grid, and Southridge never appears
in the hub's spoke table. Four separate causes, one release.

**The phone layout was being undone by source order.** The phone block of the stylesheet came BEFORE the desktop
base rules that use the same selectors, so at equal specificity the desktop rule won: the sidebar stayed a 236 px
column in the page flow, the join gate started beside a rail that is not there, sheets kept desktop widths and `vh`
heights, the drawer showed only bubbles (its "Create room" form landed in a `display:none` box), the 16 px input rule
lost to 11–13 px rules so iOS zoomed into every field and never zoomed back, and `touch-action:none` on every
mainstage meant no pinching back out. The two phone blocks now sit last in the sheet, on purpose and with a comment
saying so. Around that: phone inputs are 16 px (the one `!important` that is warranted), `dvh` twins for every
phone-facing `vh` height, side and top safe-area insets for the notch, `overscroll-behavior:contain` on the sheets and
the stage, a phone always starts with the sidebar collapsed whatever an old session saved, the gallery column is the
full width, a landscape spotlight no longer keeps a 64 px rail-row floor it has no rail for, `touch-action:none` only
where the stage zoom applies (shared content; a camera keeps native scroll and pinch), the sidebar grip hides on
landscape phones too, and a tap on a hidden control while the chrome is idle only wakes the controls instead of
switching the spotlight underneath. Verified in WebKit at iPhone 14 and 15, portrait and landscape.

**The camera was sideways because the vendored publisher loses the frame's orientation on WebKit.** Safari has no
`MediaStreamTrackProcessor`, so the library takes camera frames through its `<video>` polyfill: sensor-oriented
pixels, no rotation in the catalog, sideways for everyone including the phone's own tile. Drawing the `<video>` into a
canvas applies the phone's orientation, and the page already has that loop (the one Rotate, Mirror and the latency
stamp use) — it just never ran with no effect on. A probe (`window.__frameLoop`) now decides: on WebKit without the
processor the light loop runs at 0° for every camera, following the phone as it turns (a new frame size is committed
when two consecutive frames agree; the encoder reconfigures itself). A Rotate saved before 0.21.5 on such a device was
compensating for the sideways picture and is reset once. The portrait constraint swap is skipped there (the loop
already follows the phone). Chromium keeps its raw path; Firefox too (it lacks the processor as well, but its frames
are upright). `localStorage kastr.frameLoop = "1"/"0"` forces either way. With Verbose alerts on, a toast reports
"Camera upright via canvas loop — 720×1280". Also fixed on the way: effects that never started when the camera was
slow to produce its track (the re-arm captured a source that did not exist yet and could never see the track).

**The grid blacked out because any single viewer's stall report rebuilt it.** The grid is composited in the box's
own browser page and published from there; a viewer that starves for five seconds tells the owner, and the owner
closed and re-dialled the grid's connection on every report — at most every 45 s, with no check that anything was
wrong on its side. Single cameras got an evidence check in 0.13.3; the grid never did. One viewer on a weak link cut
the grid for everyone, the cut starved the others into reporting, and the cycle sustained itself while the box's own
canvas never blinked. A report is now a hint: the grid rebuilds only when its own encoder has stopped emitting frames,
its connection is not connected, or its relay no longer lists it — none of which a remote report can cause. Reports are
counted; every decision, build, teardown, relayout, eviction and readmit is a grid event: on the status bar, in
`/api/diag` (`publisher.grids[]`, with encoder stats, connection, last rebuild and reason, stall reports, a ring of
recent events) and in launch.log as `page: grid …` through a loopback `/api/rtsp/note`. A renewed token re-dials the
grids too (one two-second cut instead of the daily gap when the relay closed the old session).

**A dead camera now leaves the grid.** Eviction keyed on the per-camera publisher's restart ladder, but the cell is
drawn from a separate local monitor — so in Grid-only mode, in on-demand standby, or with a camera that accepts TCP and
never streams, the cell said "reconnecting… (attempt N)" forever. The monitor's own ladder evicts too (after the same
five attempts), unless a publisher for that camera has been up for a minute and vouches for it; the cell is readmitted
five seconds after its monitor delivers frames again. The Share row says which ladder removed it.

**An open spoke says so.** A spoke registers with the hub only when its own relay runs secured and holds a hub
federation token; an open relay never registered and never said why, which is how Southridge went missing from the
hub's spoke table. launch.log now carries one line per change of reason ("not registering with the hub: this relay
runs open …", "registered with the hub as <name>"), the Relay page's Federation card and Health line say it too, and a
hub token that could not be cached to disk is kept in memory instead of being re-minted — with a relay restart — on
every ten-minute check.

**Verified on the rig.** WebKit at iPhone 14 / 15 portrait and landscape (gate, join, drawer, sheets, gallery,
landscape spotlight, idle tap) plus an Edge desktop pass unchanged; the upright loop forced in Edge (loop at 0° with
the source's dims, a viewer decodes it, stamp on/off keeps it, rotate 90/0), Firefox and Edge keep the raw path, WebKit's
real probe says the loop is needed; the grid gate (three stall reports and a real `.stalled` announce → no rebuild; a
closed connection → rebuild), `/api/diag` grid entry, monitor-ladder eviction and readmit; an open spoke logs once and a
secured one registers. Both frozen smokes, the frozen two-build update test 0.21.4 → 0.21.5.

## v0.21.4 — the shell that would not update: a stale service worker stands aside

**An iPhone showed "v0.20.0" under a 0.21.3 host for a week, and reloaded forever.** The 0.20.0 service worker
(the offline shell) served everything under `/assets` from its own version's cache, and that included the masthead
script — the file that paints the version and runs the "host updated, reloading" poll. The page itself was fetched
fresh, so the poll saw the host's newer version, said so, reloaded, and got the same old masthead back. A new worker
should have installed on the first visit after the host updated; on that phone it never did (86 files, one at a
time, through the tunnel, and a cut-short install started over from nothing). The server side was fine: the page
and the worker came through Cloudflare fresh and `no-store`. The design let one failed install freeze a browser
for good, and that is what changed.

**Every response now says which build sent it** (`X-KASTR-Version`). A worker that fetches a page and reads a
version other than its own is stale: it stops answering from its cache, passes assets through to the network so
the fresh page runs with an equally fresh shell, and asks the browser to fetch its replacement. The replacement's
install runs six fetches at a time and skips files already in its cache, so a phone that cuts an install short
resumes it. The masthead registers the worker with the HTTP cache out of the way, asks for an update whenever the
tab comes back, reloads **once** when a replacement takes over (and not at all when the page already runs the
host's build, which is what standing aside achieves), and never reloads twice for the same host version.

**The page has a last resort for browsers still holding a pre-0.21.4 worker** — every phone and laptop that visited
during 0.20.0–0.21.3. The page compares the masthead's version with its own; a masthead older than the page can
only mean a stale worker, so the page drops the worker and its caches once and reloads. A second disagreement for
the same build gives up quietly instead of looping. That is how the stuck iPhone heals on its first visit after the
host runs 0.21.4, with nothing to clear by hand.

**Verified on the rig** with one Edge profile against four servers on one origin in turn: 0.21.3 installs its
worker and takes control; 0.21.4 with a worker that cannot install (the stuck case) — the shell check drops the old
worker, the masthead reads 0.21.4, no loop; 0.21.4 proper installs without reloading a first-time page; then 0.21.5
under the 0.21.4 worker — the first load already shows 0.21.5 with no reload at all, the replacement installs and
the old cache goes. Plus the frozen two-build update test (0.21.3 → 0.21.4 through the swap helper) on Windows.

## v0.21.3 — the Windows relaunch, found and fixed; admins on spokes; purge chat; box UI; a readable stamp

**Why Windows relay boxes updated and never came back.** Reproduced on the build machine with two frozen builds
(0.21.1 updating to 0.21.2): the new build started, renamed itself into place, wrote "updated and relaunched" — and
was gone a second later. The cause is PyInstaller's single-file bootloader: it reads the bundled Python archive from
the executable's path lazily, and when the running image is renamed it aborts ("appears to have been moved or
deleted since this application was launched"). The 0.21.0 takeover renamed the new build while it ran; the older
classic path renamed the OLD build while it ran (before it had spawned its successor). Neither can work on Windows.
Now no running image is ever renamed: the updater writes a small helper (`swap-<ts>.cmd` in the state folder),
starts it hidden (its own console, outside KASTR's job) with the scrubbed relaunch environment, and exits; the helper waits for
the old process to be gone, renames `KASTR.exe` → `KASTR.old-<ts>.exe` and `KASTR.new.exe` → `KASTR.exe` (up to
20 s of retries for a scanner's lock), starts `KASTR.exe` at its final path and writes what it did to
`launch.log` — and if the new file could not be placed it puts the old build back and starts that, so the box
always comes back. Verified here: a 0.21.2 box updated from a 0.21.3 authority came back serving 0.21.3 (the
`swap:` line in its launch.log, the old build aside). The takeover stays in the code behind `update_takeover = on`
for experiments only. Linux is unchanged (its relaunch has worked in the field).

**An admin on a spoke could not delete chat.** Chat is forwarded from a spoke to the hub under the spoke's
federation token, and the hub cannot verify a member token the spoke's minter issued — so the admin's delete was a
stranger's. The spoke, which verifies every chat caller anyway, now vouches for its admin (`X-Kastr-Admin: 1`
under its federation bearer); a secured hub honours the vouch only from a federation token it verifies.

**Purge chat from the Relay page.** The rooms table (and each spoke room in the Federation card on a hub) gets
"Purge chat": the transcript and attachments stored on that machine go, the room stays. The relay operator's own
page also sees the delete on every chat line and every shared file (the host already allowed it).

**Unattended boxes have no webcam or microphone controls.** In publisher, publisher-relay and relay modes the
camera/mic toolbar groups, the gate's camera/mic switches and preview, and the audio/video option entries are hidden.

**The latency stamp is readable.** Beside the machine strip the publisher now paints the same clock as text
(`HH:MM:SS.mmm`, relay-host-corrected), and the viewer's badge says "latency 282 ms" instead of a bare number.

**Still to hear from the field:** Southridge did not appear in the hub's spoke table and did not update — a spoke
registers with the hub only when its own relay runs secured (the registration needs the hub's federation token and
its own auth service). Its Relay page Federation card and its launch.log say which it is.

## v0.21.2 — field fixes, round two: boxes, grid quadrants, closing rooms, admins, web cameras

Kenton's second list after 0.21.1 on kastr.madlabs.app, with relay/publisher boxes, on-demand RTSP grids and web
clients through the tunnel.

**An unattended box has no camera tile.** A relay, publisher or publisher-relay box is not a person: since 0.15.0 it
stayed out of People and the counts, but its own webcam still made a tile in the rail. Every viewer now hides that
camera (the box's RTSP feeds and grids are content and still show). The mode travels in the box's presence, so
nothing changes on the box.

**The grid quadrant is the play button.** Clicking a quadrant of an RTSP grid whose feed was on demand (or down)
used to zoom into the composite — low quality, and not the camera. The click now wakes that feed on the relay host,
shows "starting…" over the cell, and opens the feed at full quality the moment its tile exists; in every grid mode,
since the owner announces each member's path. The "On demand" chips disappear for feeds that belong to a grid (the
quadrant does their job); they stay for stand-alone on-demand feeds.

**Nothing leaves its card on the Relay page.** The rooms and spoke tables overflowed a 340 px card by up to 120 px
and the page scrolled sideways, so buttons sat outside their box. Tables scroll inside their card, long addresses
and fingerprints wrap, inputs never exceed the card, and a card is never wider than its column.

**Close a room from the sidebar — and from the hub.** The room's creator, and anyone joined with the admin access
code, sees a ✕ on the room's sidebar card (hover) that closes the room for everyone; the relay operator keeps the
Relay page. The hub's Federation card now lists each spoke's rooms, each with a Close that rides the command channel
to that spoke (it acts within a second and re-registers), so a hub operator closes any room in the federation.

**Admins remove files and chat lines.** An admin-code holder sees a delete on every chat line and a ✕ on every
shared file, not only their own; the relay host accepts the admin's member token for both. Loopback pages (the
operator) could always do this.

**File links through the tunnel.** A web client that shared a file announced it under the host's LAN address (the
page guessed a "reachable" address the way the app window has to), so nobody through the tunnel could download it.
A page reached by any address but loopback now announces the address it was reached by — the tunnel name through
Cloudflare, the LAN https on the LAN — and a viewer whose relay host is public fetches a file announced under a
private address through that host.

**Web clients add RTSP cameras through the host.** A browser has no ffmpeg, but the relay host does: a web client
joined with the publisher code can add a camera address (Share ▸ RTSP feed) and the host pulls it, transcodes it on
its hardware encoder and publishes it into the room under the adding person's name — offered only when the host has
a hardware encoder and its relay requires access codes; the feed is kept across the host's restarts, and only the
person who added it (or an admin) can remove it. A host that has never joined a room with its publisher code says
so instead of adding.

Verified on the rig (Edge): the box camera never becomes a tile; a quadrant click on a down member starts a wake
instead of a zoom; the creator's and the admin's sidebar cards show Close and the creator's click closes the room;
an admin deletes another poster's chat line and another member's file; a web client's file link carries the page's
own origin; the web client's Share menu offers RTSP through the host and an add round-trips; the Relay page keeps
every element inside its card at 1100 and 375 px. HTTP checks: admin close without a key, viewer refused; admin
chat/file deletes from another address; remote RTSP add refused without a token and with a viewer token, accepted
with a publisher token (published under `<room>/<host>/<adder>/`), another publisher cannot remove it, the adder can.

## v0.21.1 — hotfix: a hub never hands out another release's binary

**Mendon "updated" to 0.21.0 and came back as 0.20.0.** The hub at the public name ran 0.21.0 and its manifest said
so, but the Linux file in its `updates/linux/` folder was still the 0.20.0 build: releases are built Windows first,
then Linux, and the Windows zip carried the Linux binary as mirrored at that moment — the previous release's. The
manifest hashes whatever file the hub holds, so the checksum verified, the spoke swapped, relaunched as 0.20.0, saw
0.21.0 on the hub again and would have repeated it every hour. Nothing in the chain carried a per-platform version.

Now every update binary travels with its version (`BUILT_VERSION` beside it, written by `build.py --publish` and by
the hub-to-spoke mirror), the manifest reports a `version` per platform, and a client refuses a binary whose version
is not the one the hub runs — logging *"relay host runs v0.21.1 but its linux binary is v0.21.0; staying on v0.21.0
(the hub's updates/linux/ folder needs the v0.21.1 linux build)"*, shown in amber on the Relay page — instead of
downgrading and looping. A relay box mirroring from its hub skips such a binary the same way. A release zip ships
another platform's co-located binary only when it is the same release, `--publish-only --rezip` rewrites the first
platform's zip once the second is built (part of the release ritual now), and the frozen smokes check that every
platform in the manifest is the release version.

Fixing a hub already holding a stale file: put the right binary in its `updates/<platform>/` folder (a 0.21.1 zip
carries the right ones), or let it re-mirror from its authority; spokes then update on their next check.

## v0.21.0 — the field report: phones, media, relay, fleet

Kenton ran 0.19 and 0.20 through the real tunnel at a public name with phones and other people, and filed 36 items.
This release is every bug and interface fix from that list. Rooms and permissions (waiting room, per-room passcode,
five permission levels, raise hand, kick to the waiting room) are v0.22.0; update hosting on GitHub Releases and a
build guide for every platform are v0.23.0.

**Phones, portrait and landscape.** One phone rule covers both (`max-width: 720px` or `max-height: 500px`), so a
phone held sideways gets the phone layout too. Every popover is a bottom sheet — the share sheet, the People and
chat panels, the camera and microphone menus, and the tile menus behind the chevrons, which used to open off-screen.
Menus that "would not open in portrait" were being closed by the page itself: a phone's address bar fires a resize
and a scroll as a menu opens, and the menu closed on both. Now a height-only resize re-places the open menu and a
phone never closes a menu on scroll. Sheets fit a 375 px tall viewport with one scrolling body.

**Sideways camera.** The Camera menu has Rotate (0°, 90°, 180°, 270°) and Mirror. Rotation alone runs the light
canvas loop (no person segmentation), the output frame swaps its sides for 90° and 270°, backgrounds stay upright,
and the setting is saved and rides the join like the other effects. A phone with Auto resolution asks for a portrait
capture when it is held upright (checked once at start — 0.21.5 corrects the claim that it was re-asked on rotation, and
skips the request where the upright loop already follows the phone); the gate's preview asks for the front camera when
no device is saved.

**Media shares: the scrub that "restarted the file", and the sharer who heard nothing.** The scrub bug had two
causes, both found on the rig with a two-minute file. First, ffmpeg's fragmented-MP4 muxer starts every stream's
clock at zero whatever the seek position was: the real offset only ever lived in an edit list, which MediaSource
ignores — so a seek to 1:30 buffered as 0:00–0:30 and the page's settle step moved the playhead to the start. The
server now reads the real start off the muxer's edit list (`X-KASTR-Start`; it used to carry the requested time,
wrong by up to a GOP for a copied file) and the page places the data there with `timestampOffset`; the copied video
and the re-encoded audio are seeked the same way, so they share one start (the accurate seek had moved the audio to
the exact second and left the video at the keyframe — six seconds of skew on the fixture). Second, a seek orphaned
the previous reader but left its last, half-received fragment queued; it was appended after the buffer was cleared,
the new stream's header followed the torn fragment, and the SourceBuffer raised the "sourcebuffer error" of the
report. The seek now fetches first and clears second (nothing is dropped until the server has answered), flushes
the orphaned bytes, retries a SourceBuffer error once at the same position with a fresh MediaSource, and a re-attach
never ends the share (the old MediaSource's end-of-stream used to fire `ended`, which with loop off ended the share).
A rejected video copy escalates to a transcode again (the page checked 502; the server has said 503 since 0.20).
Rig: seeks to 60, 5, 90, 117 and 0 s land within a keyframe, no restart, no escalation, two seeks back to back
settle on the last one.

The person sharing a file heard nothing because the sharer's monitor was created inside the microphone tap, which
never saw a streamed file's audio track. It now attaches straight from the file's own audio, retries on the next
gesture when autoplay refused, and the media bar has "Hear it myself" (only you) beside "Mute for everyone".

**Media chrome hides itself.** Three seconds without pointer or key input hides the media bar, the file-name bars,
the chevrons, the zoom controls and the Gallery pill; the pointer resting on a control, a control with focus, or a
scrub in progress keeps them; on a phone any tap shows them.

**A resolution picker for every shared file.** After the probe, a small card shows the file (size, codecs, frame
rate, duration, container), warns about unusual files that KASTR will re-encode as they play, and offers "Same as
source" or any rung below it (2160/1440/1080/720/480/360). A web-safe file is scaled in the composite (no server
work); anything else is re-encoded at the chosen height (`&h=`, `X-KASTR-Height`), with a bitrate table for the
hardware encoders and the low ladder one rung below. Web clients get the same card from the browser's own metadata.
The file encoder follows the chosen or source size instead of the camera's cap: a 1080p file share now leaves at
about 2.5 Mb/s (was 1.2).

**The latency stamp is a thin strip in the bottom-right corner.** 48 cells of `max(4, width / 200)` px — about a
quarter of the width from 800 px up, one row tall — with sync cells at both ends, in place of the 0.18 bar across
the top of the picture. Viewers calibrate the cell size from the strip's own sync cells (the decoded picture is the
encoder's size, not the publisher's), sample 3×3 averages against the strip's own levels, and still decode the
0.18–0.20 top-left stamp. A plain camera with the stamp on runs the light canvas loop just to draw it. Rig: the
strip decodes at 1920, 1280, 640, 426 and 320 wide, and a viewer read 282 ms on a file share and the stamp on a plain
camera.

**Spotlight follows the participant.** A spotlight used to be the spotlighter's vote; when they left, everyone's
stage fell back to the gallery. The spotlit participant now mirrors the spotlight into their own room record and
every viewer counts that mirror as a vote, so the spotlight survives the spotlighter leaving and a late joiner lands
on it; the participant re-announces it after a reload within 30 minutes. Another spotlight, the spotlighter's
explicit un-spotlight, the share ending, a room switch or a kick clears it.

**Full screen is the stage.** F, or the full-screen button, puts the whole stage in full screen instead of one tile,
so the RTSP grid, cell clicks, the back pill, chevrons and zoom keep working inside it, and every tile keeps
downloading. **Dead RTSP previews** are gone: the grid owner announces every member's path, which are down and which
are out, in every grid mode, and a viewer never shows a down or evicted member's lingering broadcast as a tile.

**Toasts, switches, small things.** Toasts are a neutral surface with a blue accent; amber for warnings; red only for
errors. Setting toggles (latency stamp, feeds mode, "re-encoding as it plays") are verbose-only. The "a viewer
reported your share frozen" toasts are gone (the nudge and the rebuild stay). Every checkbox on the page and the
Relay page is a switch. The share preview's options button is three dots (it was the same chevron as minimize).
The sidebar's "+" opens the create-room form in a bubble beside a collapsed rail instead of expanding it. The
gate's relay field is a real select (the old datalist filtered to its own value and "did nothing"); choosing an
entry applies at once, "Other…" reveals the address field. Four ASI backgrounds (swoosh, blue motes, light sweep,
horizon) join the scenes.

**Relay: the federation code that vanished after an upgrade.** Five causes, all fixed: the access-code store opened
its file without tolerating a BOM and returned silently on any read error, so the next save wrote every code as
null; every state writer shared one `.tmp` name (a predecessor and its successor, or two threads, interleaved); no
fsync; the hub fingerprint note rewrote the cluster file with the fingerprint alone when its read failed, dropping
the hub address and the code; and the Relay page's Save posted a blank hub address before the field had painted,
which cleared the code. State files now load BOM-tolerant with retries and save through a unique temp name with
fsync and a `.bak`; the code store recovers from the `.bak`, else moves the bad file aside and records LOST (shown in
red on the Relay page, with each code's set date); the fingerprint note merges or refuses; a blank hub address keeps
the code; the page confirms before leaving a hub.

**RTSP feed that kept coming back.** Closing a feed never told the bridge: the page only forgot its own list, the
running pair stayed in the bridge's session file and came back at the next launch or rejoin. Closing now removes it
at the bridge, which keeps a tombstone in `rtsp-feeds.json` so a restore never re-adds a closed address; adding it
again clears the tombstone.

**Windows relaunch after an update.** The shell-escalation path started the new KASTR with no environment, so the
child inherited the frozen loader's variables and became the "bootloader with no child" of the field reports. Both
launch paths scrub the environment; a launched child writes a ready marker as its first act and the parent counts
success only when the marker appears (a silent bootloader is killed and retried); every attempt is logged. Updates
take over in two phases: the new build is downloaded as `KASTR.new.exe` and started FIRST; once it is ready and the
old process has quit, it renames the old file aside and itself into place (finished at the next launch if a file is
locked). `update_takeover = off` in kastr.ini keeps the classic swap. Verified with stub children and on copies; the
frozen two-build test on the dev box is part of the release ritual.

**Update the spokes from the hub.** The hub's Federation card lists the spokes federated to it (name, address,
version, last seen) with "Update spokes now"; the command rides the ban long-poll every spoke already holds at the
hub, so a spoke reacts within a second and relaunches only when its version differs. "Check for updates" on a spoke
asks the federation master, not the LAN relay.

**Relay page.** A responsive card grid (one column on a phone, the log across the bottom), the Server panel split
into Server, Access codes, Startup & mode and Network, the duplicate "allow other machines to update from this one"
switch removed (it fought Web clients over the same setting), the printed firewall command gains the mDNS rule (it
never matched the seven rules the button adds), and the misleading texts fixed (the streams note blamed room codes;
the web-clients hint named a switch that does not exist; the Clear tooltip said three codes; the admin field stayed
filled after a save).

**Not in this release.** Rooms and permissions (v0.22.0); GitHub Releases as the update host and `BUILDING.md`
(v0.23.0); an iPhone pass of the new phone layout waits for the host to run 0.21; the secured-relay half of the
live test (admin stop and kick through the real tunnel) still waits for the host to require access codes.

## v0.20.0 — the tunnel for real, kicks that reach tunneled spokes, an offline shell

**Verified on a real Cloudflare Tunnel.** Kenton's relay host at a public name ran 0.19.0 behind cloudflared. Read-only
probes, then Edge under Playwright: the page was handed `https://<name>/relay`, the WebSocket upgrade got the relay's
101, every host control answered 403, a fake camera published and played, chat crossed, and the latency stamp read
about 0.5 s glass-to-glass through Cloudflare's edge. The moq CLI published and subscribed through the same name over
WebSocket (valid H.264 back). Two defects came out of it, both fixed below.

**An open relay behind a tunnel is public, and KASTR now says so.** With no access codes a relay trusts "the LAN";
through a tunnel that is the whole internet: anyone with the name can list cameras, read chat, pull recordings and
watch. The operator chose to keep it working and be warned: the Relay page's One-port card shows a red line, the
launch log says it once an hour, and every browser visitor sees an amber note on the gate until codes are set.
Setting codes also means starting the relay with "Require access codes" — saved codes alone leave it open.

**Cloudflare swaps origin 502s for its own page.** On an open relay the room-code service does not run, and KASTR
answered 502 for `/api/auth`; Cloudflare replaced that with `error code: 502`, which `watch.html` read as "no KASTR
here". An open relay now answers its own shape with 200 (`secured: false, open: true`), and no KASTR error is a 502
any more (503 passes a tunnel untouched).

**A kick reaches a spoke behind a tunnel or NAT in about a second.** The hub's ban list is versioned, and a spoke
keeps one request held at the hub (`GET /api/bans?since=<ver>&wait=25`) that answers the moment a ban is added or
cleared. Measured on the rig with the spoke federated through a tunnel: 0–2 s from the kick to the spoke's refusal,
against up to 10 minutes before. Un-bans propagate the same way (a ban cleared on the hub's Relay page is lifted on the
spokes), the hub nudges its reachable spokes in parallel, and the 10-minute tick stays as the backstop.

**Browser clients keep an offline shell.** Over https a browser client installs a service worker that caches the app
shell (the page, the masthead, the vendored MoQ library, icons; about 2.5 MB) under the KASTR version that served it.
An installed KASTR opens at once, still renders when the relay host is unreachable and says "Offline" in a toast; rooms,
chat and video need the host and are never served from the cache, nor is anything under `/api/`, the `/relay` pipe or
a request with a query string. A new KASTR build's worker drops the older cache, and the existing version poll reloads
the page. Verified in Edge (registered, 86 files cached, offline boot, API not cached) and Firefox (all but the
"back online" toast, which Firefox does not fire under Playwright's offline switch).

**Firefox was loading the MoQ library from the internet.** The page's import map, which points the library at the
vendored copy, sat below the masthead's module script; Firefox refuses an import map that arrives after a module has
started loading, so every Firefox client fetched `@moq/*` live from esm.sh at whatever version esm.sh served that day.
It passed on 25 September and failed on the 28th, when esm.sh moved to publish 0.5.1 / net 0.4.1: Firefox pages
connected but saw no members and no chat. The map now comes first in the head, and a rig check keeps it there. Edge
and Chrome always honoured the map, so they were never affected.

**Not in this release.** The secured-relay half of the live test (admin stop and kick through the real tunnel) waits
for the host to run with access codes required; an iPhone test of the installed shell; Docker and Mac smokes.

## v0.19.0 — everything on one web port (Cloudflare Tunnel)

**One name, one port.** The relay host's web port now carries the video too: `/relay` on it is a WebSocket pipe to
the relay. So a single Cloudflare Tunnel hostname pointed at `http://localhost:8000` serves the page, the API,
chat, files, recordings, updates and the media. Browsers open `https://<your name>/` and get the full client.
KASTR apps, RTSP cameras on other machines and federated spokes use `https://<your name>/relay` as their relay
address. A relay address ending in `/relay` means "that KASTR's web port carries everything", everywhere KASTR
takes a relay address. On the LAN nothing changes: direct QUIC stays the fast path, and the direct ports keep
working. `docs/cloudflare-tunnel.md` has the recipe. The Relay page has a "One port (Cloudflare Tunnel)" card
with the origin to give cloudflared, the addresses to hand out, the last proxied visitor and the live pipe count.

**Behind a proxy, a visitor is a visitor.** cloudflared connects from 127.0.0.1, and it can rewrite Host to
`localhost`. KASTR used to trust exactly that combination as "the machine itself". Now any request carrying a
proxy's headers (`Cf-Connecting-IP`, `X-Forwarded-For`, ...) is another device. The quit route had its own older
check, and a tunnel with Host rewritten could stop KASTR; it now uses the shared check. Wrong-code lockouts, bans,
chat lockouts and logs count the visitor's address, not the tunnel's. A kick never bans 127.0.0.1, which would
have removed every tunnel visitor.

**Verified on the rig through a local stand-in for cloudflared.** It had one TLS port, cloudflared's headers, and
Host rewritten to localhost. Edge and Firefox joined, published a camera, watched it and chatted. An admin stop and
kick worked, and the other visitor stayed connected. The moq CLI published and subscribed through the tunnel over
WebSocket (valid H.264 back). A spoke federated to the hub through it: token minted, relay linked over WebSocket
after QUIC failed, media crossed the link, and a kick on the hub reached the spoke. Every host control answered
403 through the tunnel. No real Cloudflare tunnel was used, because it would publish the build machine.

**Limits.** A tunnel has no UDP, so media rides WebSocket: a little more delay than QUIC, and head-of-line blocking
on a lossy link. A spoke behind a tunnel cannot be nudged about bans; it pulls them on its federation tick (about
10 minutes). Cloudflare Access in front of the name blocks the native clients unless KASTR's paths bypass it.
Other reverse proxies that send no forwarded headers need `single_port = true` in kastr.ini.

## v0.18.0 — cameras that wake for viewers, cheaper thumbnails, recordings on the relay host

**RTSP cameras can sleep until someone looks.** Each RTSP row has an **On demand** switch (off by default). With it on,
the camera is registered with the relay host but not pulled: viewers see it in an "On demand" row above the stage, a
click wakes it (1.4 s in Firefox and 4.5 s in Edge on the rig from click to tile), and 60 s after the last viewer stops
watching it goes back to sleep. Every watcher keeps it awake: a tile on screen, the relay host's fMP4 or HLS player,
and a recording. The relay's own metrics count no subscribers per broadcast, so demand is KASTR's own signal: the
camera's machine asks the relay host every 5 s which of its cameras are wanted. A grid composite keeps its members on.
Limitation: demand goes to the viewer's relay host, so a camera publishing to a different federated relay does not see
it.

**Thumbnails can pull a small copy.** A second switch, **Low for thumbnails**, publishes a 640-wide, 15 fps, 400 kb/s
copy beside the camera (`<name>-low.hang`, always an encode). Viewers show it on rail and grid tiles and switch to the
full stream when a tile is spotlit; the stats panel says which rendition a tile is on. The low copy sleeps and wakes
with its camera.

**The relay host can record.** The Relay page has a **Record** button per live stream. The host writes one-minute MP4
segments under the state folder's `archive/<stream>/`, keeps them 24 hours (`archive_hours` in kastr.ini) and lists
them on the Relay page with "last 10 min / last hour / all" downloads. Members of a room find that room's recordings
in the Files panel; a download is one MP4 cut from the segments, checked against the member's token like live video.
Recording keeps an on-demand camera awake. Pick a stream while it is live; the pick survives relay restarts.

**Hooks.** `hook_ready`, `hook_notready` and `hook_read` in kastr.ini (or `KASTR_HOOK_*` in the environment) run a
command when a camera has been up 5 s, when it stops, and when a viewer asks for it. The command gets `KASTR_EVENT`,
`KASTR_BROADCAST`, `KASTR_FEED_ID`, `KASTR_RELAY` (without its token), `KASTR_REASON` and `KASTR_VIEWER`, runs
detached, and is killed after `hook_timeout` (30 s). The launch log names the hooks that are set.

**Older iPhones get HLS.** A browser without MediaSource that plays HLS (iPhone before iOS 17) asks the relay host for
`/api/watch/<stream>.m3u8`. The host checks the token, hands out a private playlist address and runs one HLS exporter
per stream, shared by its viewers and stopped 45 s after the last request. A playlist address dies with its token, a
kick, or two minutes unused. Verified with ffmpeg through the proxy (720p H.264); no iPhone was on the rig.

**Glass-to-glass latency on screen.** More ▸ **Latency stamp on my shares** draws a small strip into shared files, RTSP
grids and effected cameras; every viewer decodes it and shows the latency in the stats panel. Measured on the rig:
about 0.5 s in Edge and 1.5 s in Firefox for a shared file. A plain camera without an effect carries no stamp.

**A kick reaches every spoke.** Spokes tell the hub where they answer; a kick on the hub, or one forwarded to it by a
spoke, now nudges every spoke, which pulls the hub's bans with its federation token and applies them. Verified with
two instances: the spoke refused the removed device within five seconds. A removed member is also refused by the
relay host's side doors (on-demand, recordings, HLS).

**Fixed on the way.** Two quick option toggles on an RTSP row could race and lose one (publishes are now serialised per
feed and the page waits 400 ms). `watch.html` retries a transient server error instead of printing the exporter's log,
and keeps the lower-latency MediaSource path on desktop Safari.

**The failed-relaunch path, tested.** The owed negative case ran on the rig: a 0.17.0 client updated from a 0.18.0
authority while the swapped exe was held locked. The swap landed, every restart attempt was refused, the update note
said `relaunch-failed`, the dialog asked for a manual restart, and the old window kept serving 0.17.0. The test also
showed the retry window ending at 10 s instead of 30 s, because the shell launch step raised; and without the "no UI"
flag Windows could put up its own error box. Both are fixed for updates from 0.18.0 on: any launch error is retried
inside the window, and the shell reports a locked file at once (verified from source against a locked exe: started
through the shell 19 s in, once the lock lifted).

**Not in this release.** Per-subscription priority on tiles (the vendored player has none), Let's Encrypt, a service
worker, the Docker and Mac smokes (no Docker or Mac on the build box), and an iPhone test of the HLS path.

## v0.17.0 — open KASTR in any browser: the relay host serves the client

**No executable needed any more.** Point a phone, tablet or laptop browser at the relay host's web address and you get
KASTR — the same page the app shows, served by the relay's own KASTR, so browser clients always run the relay's version
(they reload themselves when the host updates). Over **https** (port 8443) a browser client does everything a full client
does short of the host's own hardware: rooms, People, chat, spotlight, the admin code's Stop / Mute / Remove, and it
publishes its camera, microphone and (on desktop browsers) its screen. Over plain **http** (port 8000) the browser blocks
its camera, microphone and its own decoder, so the page is a lobby with video: rooms, People, chat and admin work, and the
spotlit stream plays through the relay host as fragmented MP4 (one stream at a time). What stays on the host: the RTSP
bridge, media-file transcoding, relay controls, updates, preferences. Each browser is its own device (`web-<id>` host, so
two phones never collide), and a page on another device can no longer keep the host's window alive, move its window,
rename its operator, spawn feeds on it or read its diagnostics — every host control now checks Host, peer and Origin,
not the Host header alone. Chrome/Edge and Firefox were verified end to end on the rig (lobby, https publish + view,
admin stop and remove, chat, PWA manifest); Safari, iPhone and Android are best-effort this release.

**Trust has two doors.** The relay host's KASTR certificate authority still works as before — install `/ca.crt` once per
device (the Phone access card shows the QR and the addresses, now including `<hostname>.local`) — and an operator can
drop a real certificate in instead: `tls_cert`, `tls_key`, optional `tls_chain` and `tls_hostname` in kastr.ini serve
both the web page and the relay's wss listener, with a daily check that picks up a renewed file (certbot / win-acme write
into those paths) and one log line a fortnight before expiry. Automatic Let's Encrypt is not in this release: it needs a
public name and an inbound path the robot-site relays do not have. The Relay page gained a **Web clients** switch that
writes the host and https settings, adds the firewall rules and lists the addresses to open; it also warns when the relay
is bound to the machine only (browser clients need it on the LAN). Installable as an app: `manifest.webmanifest` + icons,
"Add to Home Screen" opens KASTR full-screen (https only).

**A removed member is removed at the relay too.** An admin's Remove used to ask the page to leave; now it also tells the
relay host, which bans that device's identity in that room for an hour (`relay-bans.json`), closes its live sessions at
once (the relay re-validates every session on request — measured: a refused re-validation closes the session within two
seconds) and refuses its re-entry with an honest gate message. A kick on a spoke is forwarded to the hub with the
federation token; other spokes still rely on the page-side announce. The Relay page's Health panel lists removed members
with a Clear button.

**Measured and recorded.** moq CLI 0.12.1 against relay 0.15.1 prints the same session strings 0.11.2 did (`Error:
unauthorized` for a refused token — the pair parks and re-mints; `session closed, reconnecting` on a bounce — it survives),
and a 25 s outage lets the CLI's backoff expire and the pair ladder, never park. The LAN mesh discovered a second relay on
the same box over mDNS within 20 s (`advertising on the LAN … app=kastr`, `dialing LAN cluster peer`, `accepted LAN
peer`). The auth server's revalidate cadence: measured on the rig at about 605 s after connect for every session (the grant's 600 s plus the relay's tick), and the token rides the revalidate request, so a ban lands at connect, at revalidate and at the minter. The pane's per-site sandbox blocks WebSocket
from a LAN-address page, so browser verification moved to real browsers (Playwright: Edge, Firefox, WebKit).

**Not in this release.** HLS for iPhones older than iOS 17 (the CLI can export it; the endpoint waits for 0.18), a
service worker / offline mode, per-subscription priority on viewer tiles, Let's Encrypt, the Docker and Mac smokes (no
Docker or Mac on the build box — the commands are in DOCKER.md / MACOS.md), and the media items from
`docs/moq-landscape.md` (3, 5, 6, 8, 12) which form v0.18.0.

## v0.16.0 — relay stack 0.15, an admin code, a relaunch that comes back, shares that end

**The relay stack moved to moq-relay 0.15.1 / moq 0.12.1, and KASTR now answers the relay's questions.** A 0.15 relay no
longer checks tokens itself: for every session it asks an HTTP auth server (`connect`, `revalidate`, `end`) and gets back
what that session may publish and subscribe to. KASTR's token service on the relay host (relay port + 1) is that server,
and it still verifies the very same tokens the gate has minted since 0.13 -- so a 0.15.1 client, a 0.15.1 native
publisher and a 0.15.1 spoke keep working against a 0.16.0 relay, and the reverse holds too: a 0.16.0 client publishes
and watches through a 0.14.18 relay (both directions rig-proven before this shipped). Roll out hub first:
the Agg hub, then Mendon/Southridge follow within the hour, clients on their next launch. The relay's config is the new
shape (`[listen]`, `[auth] url`, `[connect]`, `[internal]`; the old spellings are gone and a `renamed` line from the relay
now surfaces on the Relay page), the native publisher speaks `--connect` / `--max-age 5s`, and the vendored web library
is `@moq/watch` 0.6 / `@moq/publish` 0.5 / `@moq/net` 0.4 (everything goes through the connection's origin; the state
tracks ride at priority 200 so presence and room state win under congestion). Tiles are tuned per class: the spotlit
tile buffers 400 ms, rail thumbnails 200 ms, grid composites and audio-less grid members run at the live edge.

**One admin code, honoured across the hub's relays.** Beside the viewer and publisher codes the relay operator can set an
admin code (Relay page ▸ Access codes). A client that enters it joins as an admin: every remote tile's menu gains "Stop
sharing", "Mute" and "Remove from room", and the target's page obeys within a second (toast on the target, the removed
page lands on the gate and does not silently rejoin). A spoke with no admin code of its own asks the hub whether the
code is the hub's -- so one code set on the hub works on every federated relay. The Relay page itself can push "Stop" to
any stream on the relay (a relay operator's stop reads "Relay operator stopped your share"). Admin commands travel as
announces under `<room>/.admin/...`, a path only an admin token may publish; a forged command from a publisher or viewer
is dropped by the relay and counted as a refusal on the relay's health panel. Removal is cooperative in 0.16.0 (the page
leaves); server-side session revocation is on the 0.17.0 list.

**Federated relays pin each other's certificates.** A spoke learns the hub's certificate fingerprint from the hub's token
service (or `/certificate.sha256`), writes it into `[connect] tls.fingerprint`, and re-learns it within 30 s when the hub
restarts with a new certificate (the relay's log wording for the mismatch is matched). `tls.insecure` remains only as the
fallback when the hub's web port is unreachable, and the Relay page says which of the two is in force. Same-site relays
can also find each other over mDNS (Relay page ▸ Same-site relays: enable + a shared secret generated on the page; the
firewall gains a UDP 5353 rule -- expect one more firewall prompt on Windows boxes that host a relay).

**Health and metrics.** `GET /api/relay/health` reports the relay (sessions, cluster nodes, internal API), the auth server
(sessions, publishers, grants, refusals, the last refusal), federation (hub, token, pinned/insecure), LAN peers, every
publisher pair (`gen`, `restartsTotal`, `sessionFails`, `sessionKills`) and the helper versions; `GET /api/relay/metrics`
(loopback) is Prometheus text: the relay's own counters plus `kastr_*` gauges. The Relay page shows both in a Health
panel.

**Windows self-update now comes back.** The updater swapped the exe and then fired one blind `Start-Process` at a file
Defender was still scanning; when that failed, the old KASTR kept running with the new exe on disk. The relaunch is now
spawn, verify, retry, escalate: it retries the direct spawn while the file is locked, respawns a child that died at once
("bootloader with no child"), escalates to the shell's own launch path after 10 s, and only exits once the successor is
confirmed. If nothing comes up within 30 s it says so (`relaunch-failed` in `update-check.json`, a dialog) instead of
vanishing. Switching relays checks for updates on the new host's real web port (learned first), never on `:8000`.

**Field fixes.** The grid chevron menu is a body-level popover that clamps to the window and scrolls (it was clipped inside
the pane). Your own camera can be spotlit again: the pane keeps its id through the rebuilds that used to drop the
spotlight, and its menu offers "Spotlight for me" / "for everyone". A GIF background animates (decoded with WebCodecs,
frame by frame; a still first frame only on a browser without `ImageDecoder`). A grid member opened on its own wears its
label ("Kenton — Gate cam"), on the owner's pane and on viewers' tiles.

**Shared files: health readout, a nicer transcode, loop off by default, and paused means paused.** Mikey's file share
hitched while his camera from the same machine was fine: two encoders on one CPU. The server transcode now runs below
normal priority on half the cores, the composite follows the file's own frame rate (a 24 fps film is no longer drawn at
30), the owner's media bar shows a health pill (`24 fps · 1248 kb/s · hw · h264_qsv · 44 s`, amber when the page's encoder
sags, red while buffering), and a sagging encoder asks for the lighter transcode ladder after three seconds instead of
waiting for two rebuffers. Loop is OFF by default; with loop off a share ends at the end of the file (`playing:false`,
then the source is removed, with a "Play again" toast). A paused share stays paused: every path that could restart it
(reopen, buffer tick, retry, control replay) now honours the user's pause, reopens keep the position instead of
restarting at 0, and `__mediaDebug()` lists the last restart causes.

**Not in this release.** Per-subscription priority on viewer tiles (the element does not expose it yet); the native
publisher's hard/soft exit strings were not re-measured against moq 0.12.1 (the 0.11.2 strings are still matched -- if a
dead token ladders instead of parking, that is the place to look); the auth server's `revalidate` cadence has not been
observed on the rig; media items 3, 5, 6, 7, 8, 12 from `docs/moq-landscape.md` are the 0.17.0 plan.

## v0.15.1 — hotfix: shared files publish in H.264 with the hardware encoder

**A shared file was still choppy from a laptop.** Two encoders sit behind a shared file and both were software: the
server-side transcode ran libx264, and the page published the composite with the library's default VP9, which has no
hardware encoder on most laptops. Now the transcode uses the same validated hardware H.264 encoder the RTSP path uses
(NVENC / QSV / AMF / MediaFoundation / VA-API, libx264 superfast otherwise) and drops to a 960-wide / 24 fps ladder after
two rebuffers; the page publishes a shared file as H.264 (`avc1`, hardware preferred) unless the operator picked a codec.
Every viewer decodes H.264 in hardware too. The response carries `X-KASTR-Encoder`; `__mediaDebug()` shows `encoder`,
`lowQ` and the audio path (`actx`, `atrack`, `pubMuted`). The "no audio" report turned out to be the share's own mute
button; the rig confirms audio leaves the owner and arrives at viewers.

**Release notes show the running build.** The version pill's notes open on this build's section only, with
"Show previous versions (N)" folding the history underneath (the "this build" tag now matches headings that carry a
title after the version).

## v0.15.0 — the hub's web port everywhere, groups and grids, quieter alerts, backgrounds that stay

**Chat, rooms, files and updates follow the hub's web port now.** 0.14.0 let a hub pin its web port, but every page still
built its hub URLs from the literal `:8000` (chat poll/send, room list/register, files, avatar), spokes learned the port
only from a secured hub and only inside the federation refresh, plain clients never did, the hub itself could decide it
was a spoke of itself once its own port moved, and the version follow used `kastr.ini update_port` (8000) no matter what.
Now every machine that knows a relay learns that relay host's web (and https) port at launch -- from the token service
(`/api/auth`) or, on an open relay, by asking `/api/instance` on the likely ports -- BEFORE the first update check, then
every five minutes; the result lives in `hub-web.json`, feeds `/api/instance.hubWeb`, the chat proxy, the update follow
(`update_port_for`: an explicit `update_port` still wins) and the page (`window.__auth.web/https`), and a failed chat probe
re-detects the port so a move heals within 30 s. Relay boxes now also **mirror the hub's other-platform binaries and browser
zips** into their `updates/` folder after each update check (about 300 MB once per version; `update_mirror = false` in
kastr.ini opts out), so the machines behind a spoke update to the same version instead of the version the spoke was
installed with.

**Rooms can be grouped.** Groups are defined on the relay (relay-auth.json), managed by the relay operator or the room's
creator, and shown to everyone as collapsible headers in the sidebar (collapsed state is yours). Drag a room onto a group,
or use the room menu's "Move to group…"; operators rename, ungroup or delete from the header. The collapsed sidebar's "+"
now opens the sidebar instead of a hidden form.

**Many RTSP grids, and the grid grew controls.** Each RTSP feed row has a Grid picker; grids are nameable ("Vehicle 7"), keep
their own seats, order and layout, and each is its own tile in the room (grid 1 keeps its old broadcast name, so nothing
existing changes). Hover a cell on the stage to remove that feed (Undo in the toast), spotlight a grid for yourself or for
everyone from its menu, rename a feed's display name without republishing it, and turn on "Show names on grid cells".

**Quieter alerts, a room tone, honest People.** Toasts have levels; the default shows room events and anything that needs a
hand, and hides the informational echoes (View ▸ Verbose alerts brings them back). Switching rooms plays a short two-note
tone. Publisher and relay boxes announce their mode and no longer appear as people in the room.

**Backgrounds that stay, move, and cut out better.** The saved background effect survives a rejoin or a room switch (the
join path never passed it to the camera). Four built-in looping scenes (Drift, Grid, Rain, Aurora), your own GIF or video
as a background (stored locally, never sent to anyone), and a tuned segmenter: GPU delegate with CPU fallback, 15 fps
masks drawn at 30 fps, temporal smoothing and a feathered edge, plus a "Best" quality option using MediaPipe's landscape
model. Everything stays offline.

**Smooth media shares.** A shared file that needs conversion no longer plays from the transcoder's live edge: playback
starts from a four-second cushion, pauses quietly ("Buffering…") when the cushion runs dry and resumes at three seconds,
the transcode is capped at 1280 wide with a faster preset, and viewers keep seeing "playing" through a rebuffer.
Effected cameras (blur, backgrounds) keep moving when the app window is minimised: a timer takes over from the frame
clock the browser stops.

**MoQ landscape.** `docs/moq-landscape.md` records what MediaMTX, MainStreaming/OpenMOQ, moq-dev 0.15, the IETF drafts,
Cloudflare and Meta are doing, with a ranked backlog of twelve realistic improvements. Nothing from it is implemented yet.

## v0.14.0 — the same port every launch, a camera that stays dead leaves the grid, media files stream as they convert, source on GitHub

**A box whose port 8000 is taken forgot everything on every launch.** The app page keeps its memory in the
browser's localStorage, which is scoped to `http://127.0.0.1:<port>`. When 8000 was held by another program
(Southridge: System PID 4) the launcher took an OS-assigned port -- a different one on every launch -- so
every upgrade (and every restart) started with an empty page: no last room, no RTSP history or kept feeds,
no grid seats, no profile. The cameras themselves kept publishing (`rtsp-feeds.json`), only the page forgot.
Now the launcher scans 8001..8040 deterministically and remembers the port it bound in `port.json` in the
state dir, so a box moves once and stays there (`--port`, or a kastr.ini `port` other than the default 8000,
still wins; delete `port.json` to go back to 8000). Belt and braces: the page mirrors its settings to the server (`prefs.json`, loopback
only, `GET/POST /api/prefs`) and seeds an empty origin from that file, so a profile wipe or another port
change no longer costs the operator their setup. Access codes are stripped before mirroring -- the standing
rule that codes never leave the loopback-guarded state files and are never echoed by a GET holds -- so after
an origin loss the gate preselects the room and relay and the code is typed once. A box that already lost
its storage is rescued from `rtsp-feeds.json`: the room, the relay and the kept camera URLs come back.

**A camera that is offline for more than five attempts leaves the grid until it reconnects.** The grid used
to keep a "reconnecting… (attempt N)" cell forever. Now, once the bridge has restarted a pair five times in a
row without it living (about 40 s into a hard outage; the counter resets after a minute of good video, so a
blip never evicts), the owner drops the member from the grid: the mosaic relayouts, viewers' hidden
full-quality tile stays hidden (`out` in the grid geometry), the Share row says "offline — removed from grid
(attempt N); retrying", and the seat is kept so the camera comes back into its old cell about five seconds
after the pair is publishing again. The viewer also stops hiding a feed forever once its grid no longer
lists it (a latent 0.13.x bug).

**Sharing a media file that needs conversion starts in seconds instead of minutes.** The old path uploaded
the whole file, ran ffmpeg to completion into an MP4 (plus a faststart rewrite and, on a copy failure, a
second full pass) and only then started playing. Now the file uploads while it plays: `POST /api/media/upload`
registers it at once, `GET /api/media/<id>/stream?t=` transcodes from any position into fragmented MP4 that
the page feeds through MediaSource with real file timestamps (`-ss` before `-i` + `-copyts`), so the media
bar, seek, loop and the viewers' mirrored bars keep working; a seek or a loop re-opens ffmpeg at the new
position (about a second of gap), a paused share stops reading and ffmpeg idles, one ffmpeg per share is
killed on stop, page close or DELETE, and a rejected video copy escalates once to an H.264 re-encode. Files the
browser plays natively (H.264/VP8/VP9/AV1 with AAC/MP3/Opus/Vorbis/FLAC/PCM) keep the instant no-ffmpeg path.
`/api/media/convert` is gone.

**Choose the web port on a hub or relay, and let everyone find it.** The Relay page gains a "KASTR web port"
field: Set pins the port in `port.json` (applies at the next launch; Apply & relaunch moves at once and the tab
follows to the new port), Clear forgets it. Precedence: `--port` > the pinned port > a kastr.ini `port` other than 8000 > the
remembered port > 8000 (the shipped kastr.ini template says `port = 8000`, which is the default, not a pin). The hub's token service (relay port + 1) now advertises the web port on `GET /api/auth`,
so spokes store it in `relay-cluster.json` (chat forwarding, peer lookups, version follow) and pages use it for
peer lookups instead of assuming 8000.

**Source on GitHub.** The repository `OccuviteASI/KASTR` holds the source (not `dist/` or `bin/`; run
`python fetch-helpers.py` to restore the helper binaries). README.md describes the layout and the build.

## v0.13.3 — a room opens on the grid again, viewer reports stop restarting healthy cameras, two overlay fixes

**Joining a room showed one RTSP feed maximized instead of the grid.** 0.13.0 moved the grid's cell
geometry from a `.grid` announce onto the owner's `room.json` state track. The `.hang` tiles still arrive
synchronously in the announce loop, so the first `applyState` ran before the geometry and the newest
feed — a grid child, but not yet known as one — became the auto-selected "content"; when the geometry
landed, its siblings hid behind the grid, the grid parked and the child stayed maximized, self-sealed by
the content check accepting a grid child. (Re-announcing `.grid` beside the state field was tried and
dropped: the identity-scoped publisher token has no claim on `<room>/.grid`, so the relay silently discards
it -- the viewer must not trust arrival order at all.) Fixes: an automatic pick that turns out to be a grid child is handed back to the grid (`gridSelectionFix`; a
human click on a child is remembered as `manualPick` and left alone); a spotlight older than ten minutes
in `room.json` is history, not an order, and a spotlight on a grid child means the grid; and `connect()`
starts every room in the gallery with nothing carried over.

**A viewer's starvation is a symptom, not an order.** On Southridge three cameras restarted every 40–60 s,
"going around": two of them deliver no video at all, so every viewer starved on them, reported a stall,
and the box dutifully restarted a pair that cannot be helped — forever; the healthy one was restarted
whenever a viewer's own subscription blinked. The viewer-report path now restarts a native pair only with
evidence the pair itself is unwell (an exit or a severed session in the last minute, or the relay no
longer listing the path); a pair the relay lists live is left alone and the report is logged. The same
relay check is shared with the no-echo heal, which additionally stands down while moq is reconnecting
(a severed session leaves both processes alive). Every viewer-driven restart is now counted where it
belongs (`nudges.viewer`; 0.13.1 counted them as `api`), and the box's launch.log gets one line per pair
generation start and exit with the counters read BEFORE the 60-second reset that made a one-minute cadence
look healthy. `/api/rtsp/list` gains `gen`, `restartsTotal`, `lastSessionAt`; `--diagnose` finds the
instance even when port 8000 is taken (the launcher writes its bound port to `http-port` in the state
dir); camera URLs are redacted for non-loopback readers; the ladder timer is armed under the lock (a
nudge could double-restart); a relay URL with and without a trailing slash is the same relay (an adopt
used to tear every pair down once).

**Overlays.** The zoom controls (and the mic/video chips) step above a visible media bar instead of
sitting on the shared file's mute button and volume slider; the owner's media bar sits on the same row as
a remote pane's. The room-name pill no longer reserves 19 px for a hidden speaker icon.

## v0.13.2 — hotfix: RTSP cameras publish again; Enter joins

**Every native RTSP pair died at start on 0.13.1.** The `-rw_timeout` flag added to ffmpeg's RTSP
input in 0.13.1 is not an option the RTSP demuxer accepts: ffmpeg prints `Option rw_timeout not
found`, exits, and the ladder restarts it forever (`restarts: 61`, `lastExit: ffmpeg code
2880417800 after 0.5 s` on Southridge). The rig check that let it through used a refused
connection, which ffmpeg fails before it validates options — a live source rejects the flag on the
first attempt. The flag is gone; `-timeout` stays. Fields from 0.13.1's own instrumentation
(`lastExit`, `error`) named the cause from the box's `/api/rtsp/list` in one read.

**Two guards from the same investigation.** A camera box republishing its kept feeds four seconds
after its own secured relay started could get "no minter" from the token service (still binding),
treat the relay as open, dial bare and park every pair on `code=6 unauthorized`; the restore now
keeps waiting while the hosted relay reports secured, and a parked publisher that held a token
never falls back to a bare URL because the minter blinked.

**Enter joins.** On the launch gate, Enter in the access-code, room-code, new-room-name or name
field presses Join.

## v0.13.1 — a Discord-style room rail, noise removal that works, Mac + Docker, the relay-only relaunch, RTSP drop instrumentation

**The room rail is the whole picture now.** The top-bar banner names the room you are in and
nothing else (hover for the facts, click for Room info); your room sits in the LEFT rail with
the others, marked with a white pill on its left edge and a blue ring, so the rail reads like
Discord's server list. Rooms are alphabetical with `main` pinned on top, and each operator can
drag cards into their own order (mouse or pen; saved per operator name, so two people sharing a
laptop keep separate orders). The expanded pane is resizable from its right edge (180–440 px,
remembered on the machine and restored before the first paint). The 0.13.0 live thumbnails are
GONE — they were a live view of every room's video and cost every publisher uplink and every
lobby downlink; live video is for the tracks in your current room only.

**Background-noise removal is real now.** The 0.8.9 "voice isolation" was a hand-rolled gate
chain that never isolated anything, and Chrome's `voiceIsolation` constraint is listed on every
platform but only acts on a handful of ChromeOS devices. Audio settings now offers two levels of
noise suppression: "Browser built-in (light)" (the browser's own AEC/AGC/NS) and "Background
noise removal (RNNoise)" — the open-source RNNoise neural denoiser (xiph, BSD-3) running in an
AudioWorklet on your machine via the vendored `@sapphi-red/web-noise-suppressor` (MIT,
`assets/noise/`, no CDN), on top of the browser's suppression, mono at 48 kHz, ~40 ms added.
Measured on the rig: white noise at −31 dBFS comes out at −85 dBFS (−54 dB) while a voice-shaped
tone passes within 0.1 dB. If the worklet cannot start on a machine you get a toast and the mode
falls back to the browser's suppression — never a switch that looks on while nothing happens.
"Voice isolation (system)" survives only as a switch that appears when the selected microphone
actually reports the effect back; on today's Windows fleet it does not appear. The mic meter in
the Audio card shows INPUT, not the noise floor: dBFS against a tracked floor, dark until
something exceeds it, and "No input from this microphone" after three silent seconds; the test
tap opens the mic with the same constraints as the live path and, in RNNoise mode, listens after
the denoiser.

**Relay-only "Apply & relaunch" comes back on Windows.** The relaunched child booted while the
old instance still answered `/api/instance`; seeing the same build on the port it took the
hand-off branch and exited, so nothing came back (a `--no-browser` box silently moved to port
8001 instead). The child now knows it is a relaunch (`KASTR_RELAUNCH`, `KASTR_RELAUNCH_PID`),
waits up to 20 s for the predecessor to leave the port and die, never hands off, and the parent
logs `relaunching (mode)` and closes faster; `KASTR_UPDATED` is set for real updates only. The
Relay page shows "Stopping… / Starting…" and follows the new instance.

**RTSP drops: instrumentation first.** Every path that can restart a native camera pair is now
attributable: `/api/rtsp/list` (and `--diagnose <file>`) show `nudges {viewer, noEcho, api}`,
`lastNudgeWhy`, `lastNudgeAt` and `lastExit {who, code, lived}`; every nudge is logged on the
box with its reason and the pair's counters. The page's "no echo" self-heal — which could restart
a healthy publisher whenever the page's own bookkeeping lost the echo — now asks the relay's
`/announced/<room>` first and restarts only after two consecutive misses with the pair up over
60 s (lockout 120 s); a relay that lists the path is logged as bookkeeping, not a drop. ffmpeg's
RTSP input gets `-rw_timeout` beside `-timeout`, and the last 8 stderr lines are kept. When the
next drop happens: `KASTR.exe --diagnose drop.txt` on the box + `launch.log` + the viewer's page
log name the row in ARCHITECTURE's restart table.

**Mac.** `build-mac.sh` + `MACOS.md`: Apple Silicon only (moq-cli/moq-relay publish
`aarch64-apple-darwin` tarballs, pinned by sha256; no Intel builds), ffmpeg via Homebrew until a
static build is pinned in `FFMPEG_MAC`, Homebrew's bin searched by the helpers, the system Chrome
as the window. The update feed gains `darwin`: the feed serves `KASTR.app/Contents/MacOS/KASTR`
as `updates/macos/KASTR`, the client swaps the executable inside the bundle and re-signs it
ad-hoc; `build.py --publish-only` assembles the three-platform feed on the machine that has all
three trees.

**Docker.** `Dockerfile` (ubuntu:26.04 — the WSL binary is glibc 2.43 — plus the WSL-built
`dist/linux/KASTR` and the Windows/macOS feed), `docker/entrypoint.sh`, `docker-compose.yml`
(host networking, `/data` volume, `KASTR_MODE`/`KASTR_RELAY`), `docker-build.sh`, `DOCKER.md`.
The container updates itself over the internet the way the fleet does: the in-app update swaps
the binary on the volume and exits 75, the entrypoint restarts it; a newer pulled image re-seeds
the volume, an older one does not. `KASTR_STATE_DIR` and `KASTR_CONTAINER` are the two new
environment switches.

## v0.13.0 — state as tracks, identity-scoped tokens, chat and previews on the wire, and eight field fixes

**Room state rides JSON tracks now, not announce paths.** Since 0.7 every non-media fact
(presence, speaking, spotlight, recording, stall reports, shared files, avatars, grid
geometry, media control, the chat pulse) was a track-less announce whose PATH carried a
base64 payload, re-dialled on every change. A page now publishes two small broadcasts:
`.state/<room>/<HOST>/<PEER>` (public prefix: `state.json` — who I am, my join time, what
I publish, speaking, typing, my picture — plus a `preview` track) and
`<room>/<HOST>/.member/<PEER>` (behind the room token: `room.json` — spotlight,
recording, stall reports, control pulses, grid geometry, media state, shared files — and
`chat.json`). Values are whole snapshots written with `@moq/json`, so a late joiner reads
the latest state on arrival instead of reconstructing it from announce churn; a change is a
new group on an open connection, not a new dial. Only the room registry (`.channels`) stays
an announce — its lifetime is deliberately decoupled from any member. Step-0 findings that
shaped it (ARCHITECTURE ledger): the producer prunes closed groups after `latencyMax`
(5 s default) so state tracks keep 60 s and a 20 s heartbeat rewrites them; a live
subscriber is not moved onto a resumed broadcast, so consumers re-consume on error or
after 2.5 silent heartbeats; group sequences are seeded from the wall clock so a resumed
broadcast never regresses below what subscribers already saw (which silently drops values
until the heartbeat catches up — the bug the rig found first); the relay serves a cached
group first and then the live one, so every value is applied in order.

**Tokens are scoped to the machine that asked for them.** `/api/token` takes the page's
`host` slug (hostname + MAC hex) and mints `put` claims under it: a publisher gets
`<room>/<HOST>`, `.state/<room>/<HOST>` (+ the one-release compat kinds `<room>/.since`,
`.presence/<room>`); a viewer gets `.state/<room>/<HOST>`, `<room>/<HOST>/.member` and the
same two compat kinds — narrower than the publisher's, so a viewer token still cannot touch
media. The relay drops anything outside those prefixes, so no member can overwrite
another's state by accident, and a leaked viewer token writes four narrow prefixes instead
of a room-wide list. The relay's public list gains `.state`; `/api/auth` says `state:
true`; a token minted before the relay grew state tracks is re-minted. Native RTSP
publishers mint with the same host. A page without a usable host slug gets the 0.12-shaped
wide token; a 0.13 page on a 0.12 relay behaves exactly as 0.12.

**Chat is delivered live over the relay; history stays on the hub.** Each member's
`chat.json` is a 50-record window: a post goes to the hub's store (4 s budget) and then
onto the window with the store's id; when the store does not answer (Agg's KASTR web port
was unreachable from the field while the relay port was fine — "Chat doesn't appear to be
working") the message still goes out live, marked "not saved", and the hint names the
host:port that failed instead of "Failed to fetch". Local (unsaved) ids never move the
history cursor; deletes ride as tombstones; "<name> is typing…" shows while someone types.
The 0.12 `.chat` pulse and polling stay for 0.12 members. A laptop's own KASTR is used
for history only when `/api/instance` says `chatHub: true` (it is the hub or forwards to
one) — never a private empty store.

**Previews.** A publishing page writes a 224 px WebP frame every 2 s (grid canvas, else the
first slot) to its `preview` track — on the public broadcast for an open room, behind the
token for a locked one. The sidebar shows it on the room card and as the collapsed bubble's
picture; subscriptions exist only for the first eight visible cards and stop when the page
is hidden.

**Field items (Kenton, 2026-09-21).** Idle publisher/relay boxes measured: an idle native
publisher into a spoke pulls 0 bytes through the cluster link (the relay subscribes
upstream on demand and cancels when the last reader leaves); the remaining suspect was a
viewer somewhere, so: own panes and Share rows show "N pulling" from the relay's `.stats`
(`subscriptions − subscriptions_closed`), `/api/instance` reports `viewing {n, ageS}` from
the pages' diag snapshots (`null` when no page reports — never a false 0; the Relay page and
`--diagnose` show it), a publisher-mode page never creates viewer tiles, and a tab hidden
for 60 s drops every non-selected tile's subscription (warm audio kept them alive with
`visible=never`) and re-arms them when shown. The left sidebar defaults to collapsed and
the choice persists (set before the module graph loads, so no flash). Opening one feed
from an RTSP grid parks the grid tile (`visible=never`, no pane in the rail, canvas
detached) so only the chosen feed downloads; Gallery/back restores it. People sharing
content are listed first in the rail (screen/file/RTSP/grid, then their cameras, then the
rest) while the collage order is unchanged. The launch gate has a Relay field with the
last five relays (hidden in viewer mode and off-loopback; a refused switch is a toast, not
silence; the access-code row and stale rooms clear on a switch). The Relay Server tab moved
into the Relay ▾ popover ("Relay server settings…", hidden in viewer and publisher modes)
and opens as a tab with a ✕ that disappears when closed.

**Kept for one release, removed in 0.14:** the `.since`/`.presence` compat announces, the
`.talking`/`.chat` publics, the no-host minter branch, the announce parsers.

## v0.12.0 — cameras that heal, a rooms sidebar with a banner for yours, speaking before you join, room chat with attachments, persistent rooms, four machine modes, occupancy timers on every room

**Cameras heal themselves — why the RTSP boxes went dark.** A native camera feed is
`ffmpeg | moq` with the relay URL and its token baked into the command line. When
the relay's signing key rotated (or the codes changed), the relay severed every
session ~30 s later; moq retried the same dead token, gave up after 10 s
("reconnect timed out … unauthorized") and exited; KASTR's retry ladder restarted the
pair with the SAME stale token, forever — `restarts` climbing while nothing reached
the relay. Nothing re-minted, because 0.11.0 stopped auto-joining and an unattended
box had no page joined. Now: moq runs at `--log-level warn` (where the reconnect
lines live), a classifier tags a hard refusal (`unauthorized`, `code=6`, expired /
invalid token), and a refused publisher PARKS instead of hammering the camera — it
asks the minter for a fresh token (once a minute, from the session the page saved),
and restarts the moment one arrives (from the minter or from a page re-posting with
its fresh token). A plain relay outage still walks the ladder. `--backoff-timeout 10s`
and `--client-quic-idle-timeout 15s` are explicit (a dead relay is noticed in 15 s
instead of 30). The reuse path is evidence-gated: a page reload or rejoin mints a
new token but never restarts a healthy pair (the 0.9.8 promise); it restarts only a
pair that is parked, recently refused, or whose token is about to expire.

**Feeds and the session are remembered on the machine.** `rtsp-feeds.json` in the
state dir holds the room, the codes, the relay and every kept feed (written on
operator intents — publish, unpublish, remove, Keep — never on shutdown). At launch
the launcher waits for the relay, mints a member token (or dials an open relay bare)
and republishes the kept feeds with no page open; a refused code is logged and left
for a hand. The gate says "N camera feeds are on air from this machine in room X".
`GET /api/rtsp/persist` never returns the codes.

**Rooms are a subscription, not a scan — why rooms vanished for 15 s.** The 0.11
room list opened a fresh connection every 10 s and armed a 1.5 s deadline before the
dial; on a WAN relay the handshake plus the first announce batch often lost that
race, the scan returned `[main]` and the list collapsed until the next scan. One
anonymous connection now lives for the page's life with permanent consumers on the
public prefixes (`.presence`, `.channels`, `.talking`, and everything on an open
relay). Entries age out 8 s after they go inactive, never while the connection is
down (the list dims instead), and a reconnect re-stamps the grace so the relay's
replay wins before anything is pruned. The relay host's room store is polled every
30 s (last good answer kept), so a kept-but-empty room never blinks.

**A Discord-style sidebar; the current room is a banner.** The ☰ expands and
collapses a left sidebar listing every room but yours (all rooms at the gate): an
initials bubble, the name, a lock, "kept", the people count, an occupancy timer
(`h:mm:ss`, starting when the first member arrives and running while anyone is in —
`main` included), a speaking icon when anyone in there talks, and the members (▲
publisher / ○ viewer, each with its own speaking icon). Collapsed, the cards become
the 0.11 bubble rail; on phones the sidebar is a drawer. Click a room to switch (a
locked one asks for its code inline; at the gate a click preselects it). "Create
room" lives at the bottom with a Keep-this-room box. Your own room moved out of the
list into a top-bar banner: `main · 2 people · ⏱ 0:12:03 · 🔒 · kept · publisher`
(click = Room info). The chip and the bubbles of 0.11 are gone.

**Speaking shows before you join.** A page whose mic is loud for two 250 ms ticks
announces `.talking/<room>/<ts>/<b64 {peer}>` on one persistent connection (toggled
with the broadcast's own `enabled`), and drops it after 2 s of quiet; muted mics never
announce. Others resolve the peer through presence, so nobody can light another
operator's icon. Relays 0.12.0 publish `.talking` in their public list; older secured
relays simply show no icon.

**Room chat.** A Chat button opens a panel docked right (a bottom sheet on phones):
text, emoji (a curated grid plus your system keyboard), pictures inline and files as
rows, Enter sends, Shift+Enter a new line, drag-drop and paste attach. History is a
JSONL file on the relay host's KASTR (`state_dir/chat/<room>.jsonl`, attachments beside
the shared files); a spoke's KASTR proxies to the HUB's, so a federation shares one
history per room name — including `main`. Delivery is a pulse: the poster announces
`.chat/<room>` for 2.5 s and everyone fetches "since my last id"; polls back it up (10 s
open, 60 s closed). Unread badge on the button; "seen" means the panel was open while
the page was visible. Delete your own messages with ✕. Viewers chat too (a member
token's `get` covers the room). A secured relay requires the room token; an open
relay trusts the LAN like shared files.

**Persistent rooms.** A room can be kept (gate "New room…" → Keep this room; the
sidebar's Create form; publisher access code required when the relay has codes). Kept
rooms survive everyone leaving and relay restarts, keep their chat, are listed with
"kept", and are closed by their creator (Room info → Close room…) or the relay
operator (Relay page → Rooms table). Closing deletes the record, the chat and its
attachments and leaves a one-hour tombstone; members learn from the STORE (an
announce only hints) and go back to the lobby — except publisher-mode boxes, which
lose chat and keep publishing. Temporary rooms behave as before.

**Four machine modes.** `kastr.ini` `mode = viewer | publisher | relay |
publisher-relay` (absent = the full client, unchanged), also `--mode`, chosen on the
Relay page (5-way select + Apply & relaunch). Viewer: no Share, camera or mic controls,
no relay address (the "Relay ▾" badge keeps its health light), "Join a room". Publisher:
Publish-only forced, AUTO-JOINS its last room at launch (video on by default; a failed
attempt retries 10 → 60 s, a wrong code waits for a hand) — the exception to 0.11's
no-auto-rejoin rule, because an unattended camera box relaunched by the fleet must
publish with nobody at the keyboard. Relay: boots to the Relay page as before.
Publisher + relay: both. The app shell hides the Relay tab in viewer and publisher
modes; the masthead badge is "Relay ▾" in every mode, with the address inside.

**Also.** `[cluster] linger = "20s"` on federated relays; the Relay page's `@moq/watch`
import is vendored (no esm.sh at run time); a Rooms table on the Relay page; presence
keeps its original join time across re-dials (a solo box's timer no longer resets);
`GET /api/relay/rooms`, `POST /api/relay/rooms/close` (loopback), `GET /api/rooms/list`,
`POST /api/rooms/register`, `POST /api/rooms/close`, `GET|POST /api/chat/<room>`,
`DELETE /api/chat/<room>/<id>`, `POST /api/chat/<room>/files`, `GET /api/chat/<room>/files/<id>`,
`GET|POST /api/rtsp/persist`, `POST /api/rtsp/keep`; `/api/mode` → `{mode, relay, running}`;
`/api/instance.mode`; `/api/auth` gains `talking` and `chat`.

**Deploy order.** The hub (Agg) first — chat lives there — then Mendon, then the fleet.
Set `mode = publisher` on the RTSP boxes so they auto-join and republish.

## v0.11.0 — rooms as bubbles, federation with a code and one update master, an honest "via", room codes back at the gate, no auto-rejoin, relay 0.14.18

**Rooms as bubbles.** Next to the room chip, every room in use on the relay is a
circle: the room's initials, a people count, a lock glyph on locked rooms, a ring on
the one you are in — always visible, like Discord's server list. Click a bubble to
switch (a locked room asks for its code); more than eight rooms fold into "+n". The
☰ keeps the detailed list, now with who is in each room. The chip itself just names
your room again (0.10.0 had made it a second copy of the ☰ menu). Counts work on
secured relays too: every member announces a copy of its presence under a public
`.presence/<room>` prefix, so the list counts people without a token.

**Federation with a code — and why Mendon ↔ Agg broke.** Both relays now require
access codes, and a relay that requires codes refuses every session without a
token, including the other relay's cluster link, which never carried one. A hub now
holds a third relay-wide code, the **federation code** (Access codes block on its
Relay page). A spoke saves the hub URL and that code (Federation panel); at every
relay start it asks the hub's minter for a 30-day relay-to-relay token and dials
with it (`connect = ["https://hub:4443/?jwt=…"]`, the relay's documented form). A
watchdog re-mints and restarts the spoke's relay when the hub rotates its key or
fewer than 7 days remain. A wrong code shows as "hub refused the federation code"
on the spoke's Relay page and as a refusal in the hub's log. Verified with two
relays on one machine: streams both ways, denial on a wrong code, recovery after a
key rotation. Open hubs keep working untokened.

**Federation master = one update point.** A spoke's KASTR now pulls its own
updates from the hub's KASTR — at launch and every hour it matches the hub's version
(up or down), the way clients match their relay host at launch. Relay-host machines
never updated themselves before: their relay is on their own machine, so there was
nobody to ask. Untick "Pull KASTR updates from the hub" to opt out. A relay-only box
relaunching on a version change restarts its relay for about 15 s.

**"via" names the relay a person dialled.** Presence now carries the relay a member
connected to (and its name when that relay's KASTR answers), and People and tile
hints use that first. The old guess read each relay's stats table and took the
first node listing the stream — in a cluster every node lists every forwarded
stream, so it named whichever relay answered first. The Relay page's streams panel
now says "announced into <node>", which is what that table measures.

**Room codes back at the gate.** Rooms persist on the relay since 0.10.0, so an
empty locked room was invisible at the gate: re-creating it via "New room…" with a
new code hit the stored one ("wrong room code"), and locking a new room needed the
publisher code, whose refusal was only logged (the room came up unlocked). The gate
now lists the relay's remembered rooms as locked so their code can be entered; a
locked room is registered before the join so a refusal is shown ("Only the
publisher access code can lock a room." / "That room already exists and is
locked…"); and a publisher re-keys a room by creating it again with the publisher
access code. Pages older than 0.10.0 talking to an older minter get their room code
in the field that minter reads.

**No auto-rejoin at launch.** Launch lands on the Join screen with your last room
preselected and its codes prefilled; you press Join. A reload inside the same
window still rejoins silently.

**Toolchain.** moq-relay 0.14.12 → 0.14.18 (credentials are no longer logged in
relay URLs — relevant now that the federation token rides the cluster URL;
WebSocket sessions end with their credential; moqt-20/21; rustls patch) and the moq
CLI → 0.11.2. The web library stays at @moq/watch 0.5.3 / @moq/publish 0.4.6
(0.5.4 / 0.4.7 exist; not re-vendored in this release).

**Deploy order.** Agg (the hub) first, then set its federation code in the Access
codes block. Then Mendon with Agg's URL, that code and "Pull KASTR updates from the
hub" ticked; Mendon's KASTR then follows Agg's version by itself. The fleet keeps
updating from its relay hosts.

## v0.10.0 — a relay on a public IP admits only code holders; the room chip switches rooms; the Relay page tells the truth about binding

**Access codes (why this is 0.10).** "Require room codes" did start moq-relay
with JWT auth, but as access control it leaked: the minter checked a code only
for a room somebody had registered in an in-memory table (emptied at every relay
restart), `main` could never be registered, so tokens for main and for any
unregistered room minted for free; one code granted publishing and watching
alike; the minter had no rate limit; and the relay's control API answered any
machine. A secured relay now carries two relay-wide **access codes**, set on the
Relay page: a **viewer code** (watch) and a **publisher code** (watch, publish,
create rooms). With codes set, every room including main refuses to mint without
one — the code decides the role, the room decides the paths. A viewer token can
subscribe and announce its presence, stall reports, spotlight votes, recording
notice, media controls and avatar, but carries no publish claim on media; the
relay drops such an announce and keeps the session (verified against the bundled
binaries). Room codes remain an extra per-room lock, and creating a locked room
needs the publisher code. Codes are stored hashed (PBKDF2-SHA256) beside the room
records in `relay-auth.json`, so a relay restart forgets nothing. Five wrong codes
in a minute lock that client out for 30 s, doubling to 10 minutes; refusals and
lockouts are logged. The relay control plane (start, stop, repoint, federation,
name, autostart, firewall, codes, key rotation) answers only the machine that
hosts the relay. A relay secured *without* codes keeps working as before and says
so in red on the Relay page. **Rotate keys** invalidates every outstanding token
at once; pages re-mint with their codes within a minute and publishers reconnect.

**At the gate.** A relay with access codes asks for one — viewer or publisher —
above the room code. Wrong codes say which one was wrong; too many attempts say
how long to wait. The codes ride the rejoin ticket and the last-room memory, so a
restart rejoins silently. A viewer code joins as a viewer: Go live is disabled
with the reason, feeds are not published, the Share panel says so.

**The room chip is the switcher.** Click **Room: main · 3 ▾** in the top bar for
the rooms in use on this relay — a header names the relay; each row shows the
people count (now including members who publish nothing), up-time, a lock glyph,
✓ on the current room; "Create new room…" is at the bottom; the list refreshes
every 5 s while open. Clicking a room switches in place (your shares republish
under the new room), and a switch is remembered like a join. The ☰ still opens
the same menu.

**The bind-all box tells the truth.** "Allow other machines to connect" — and the
port and secured boxes — now show the shape the relay actually runs with, or the
remembered one while it is stopped. They used to stay unticked whatever the relay
did, so a Stop/Start from the page silently dropped a LAN relay to loopback and
the autostart box re-saved "lan: false" from an always-empty checkbox. Starting
the relay also remembers its shape. The printed firewall hint lists all six rules
the button creates (it stopped at four). `[::]` accepts IPv4 on this Windows build
(probed), so the bind is unchanged.

**Not combined yet:** federation with access codes — a clustered relay still
carries no token relay-to-relay.

**Upgrade order.** Deploy 0.10.0 to Mendon (the fleet authority) first, let the
fleet update, then set both codes on the public relay's Relay page. Pages older
than 0.10.0 send only a room code, which a relay with access codes accepts only
when it is that room's own code.

## v0.9.10 — cells keep their places through a restart, audio off until you turn it on, older leftovers swept, publish-only devices

**Cell lock, for real.** The lock flag itself always survived a restart; its
*effect* did not. The remembered cell order was rewritten on every grid pass with
only the cameras present at that instant, so a restore that brings cameras up one
by one erased the others' positions and put late arrivals last; and a seat (what
lets a camera that is still connecting hold a placeholder cell) lived only in
memory and was wiped whenever fewer than two feeds were up — the first second of
every restore. Now the order is **merged** into what is remembered (cameras that
are not up keep their slots; a drag-swap still moves cameras), and seats persist
(`kastr.grid.seats`): a restored camera holds its remembered cell, marked
"connecting…", from the moment it is re-added. Only an explicit switch to
*Separate feeds* or removing a feed gives a seat up.

**Audio is off by default.** A camera's audio is published only when you turn it
on — the box at the top of the Share panel (now unticked and remembered) for new
feeds, the per-row Audio box for existing ones. The per-feed choice stores both
states now, so an explicit "on" survives restarts and re-adds too.

**Leftovers from older versions are swept.** 0.9.8 made children die with KASTR
and reaped the ones a *0.9.8-or-later* run recorded. Publisher pairs left by an
older version (no Job Object, no registry), and any orphaned monitor, probe or
`moq-relay`, were invisible to it. The most likely reading of South Ridge's five
cameras arriving twice (grid plus separate, hitching) after their KASTR restarted
is exactly that: the previous instance's `ffmpeg | moq` pairs kept publishing the
same paths while the new one published them again — two publishers per path and
double the encodes on that box, until stop-and-reshare let the old pairs die. KASTR
now also sweeps by what a helper **is**: at start it lists `ffmpeg`/`moq`/
`moq-relay` processes running from a bundled-helper location (`_MEI…\bin` or this
install's `bin`) whose parent is no longer a live KASTR (or Python) process, and
ends them. A second live KASTR keeps its helpers. Logged as "swept N helper
process(es) left by earlier KASTR runs"; `/api/instance` reports `swept`;
`--diagnose` lists the registry and what the sweep would reap.

**Publish only.** View ▸ *Publish only* makes this device publish without
watching: no tiles, no subscriptions, no decoders, no meters for other people's
streams. Your own camera, feeds and the grid still show and publish; People keeps
its counts (from the room's presence announces), and the owner-side stall nudges
still arrive. Remembered per device; a badge on the View button and a note on the
stage say it is on. Trade-off: with nothing subscribed, other members read as
"watching" in People.

## v0.9.9 — a corrected picture fills the stage without a zoom

Hotfix on 0.9.8's shape correction. Kenton, viewing South Ridge: "not squished
any more, but smaller and not filling the space; zooming fixes it." His viewer
diagnostics (`state().shapes`) showed the cause: two of South Ridge's 4K cameras
are announced by the publisher's `moq import` with a **square** display size
(3840×3840) while the decoder produces 3840×2160 -- a wrong catalog size, not a
pixel-aspect problem -- so the 0.9.8 correction engaged (factor 1.78) and removed
the squeeze. But its transform was computed once, against the pane's shape at
that moment, and only a zoom recomputed it; the pane was reshaped to 16:9 a
moment later and the picture stayed drawn for the old square box.

The correction now follows its box: `fitMainstage` re-applies the transform of
a zoomed or corrected canvas after sizing the pane, `viewApplyAll`/`viewPrune`
and the window-resize handler cover corrected canvases as well as zoomed ones,
and the 1 Hz probe reshapes the pane before drawing for it.

Also in this hotfix: **adoption is limited to the page on the machine itself.**
0.9.8's "adopt what the server runs" ran on every page a KASTR serves, so a
phone or LAN viewer opening the operator's HTTPS page would have listed the
operator's cameras as its own shares and hidden their tiles (found in the rig,
where a second local page did exactly that). Same loopback rule as the server's
publish endpoint. And the shape probe now judges only full-size frames (a rail
tile decoding a 640×352 low rendition of a 1280×720 catalog differs by
coding-size rounding, not shape -- it was being nudged 2 %) with a 3 %
tolerance. Both platforms are rebuilt.

## v0.9.8 — camera publishers live and die with KASTR, and come back as yours

**Restart: your cameras are yours again.** A KASTR that was killed hard (Task
Manager, a crash, the old close script) left its `ffmpeg | moq` publisher pairs
running: the cameras stayed on the relay under your name while the next KASTR
saw them as a stranger's tiles -- no grid, no Share row, no Stop, and re-adding
a camera published to the same path twice. Three layers fix it:

- **Children die with the app.** On Windows every ffmpeg/moq child -- and the bundled
  moq-relay -- joins a Job Object that the OS tears down with the KASTR process,
  however it ends (an orphaned relay used to keep port 4443 and the next start
  failed with "address in use"). On both
  platforms every child is recorded in `rtsp-children-<pid>.json` in the state
  folder, and the next start reaps the recorded processes of a dead KASTR
  (matched by executable and start time, so a reused PID is never someone
  else's process). `--diagnose` lists the registry.
- **A fresh page adopts what the server runs.** After a reload or a closed
  window the bridge still publishes; the page now lists those feeds as its own
  (same feed, same broadcast name, same audio flag), seats them in the grid and
  shows them in the Share tab. The server keeps the running pair when the
  publish request matches (idempotent publish), so nothing drops. "Reconnected
  N camera feeds already running on this machine."
- **Keep after restart is the default.** The box is on for new feeds and
  remembers its last state; a feed's own "Keep after restart" menu item still
  turns it off. Feeds now legitimately come back after a restart -- through the
  page, in the grid, stoppable.
- `POST /api/quit` ends KASTR cleanly from a local tool; `close-kastr.ps1` asks
  that way first and only then kills and sweeps (`moq.exe` and the frozen
  build's `_MEI…\bin` helpers included -- the old sweep matched neither).

**Audio is controllable where the shares are listed.** Every RTSP row on the
Share tab has an **Audio** box (the pane menu's "Send audio" stays; the box at
the top of the panel is the default for new feeds). In Grid-only mode the box
is disabled with a hint -- that mode publishes the mosaic without audio. The box
reads "applying…" until the server confirms. Renaming a native feed republishes
it under the new name (it was a silent no-op).

**The spotlight shows the picture's true shape.** A camera with non-square
pixels (an anamorphic H.264 stream, SAR ≠ 1:1) is never passed through: the
catalog viewers size their picture from carries the coded frame, so a copied
anamorphic stream showed squeezed on every viewer. The probe reads the SAR,
such a camera is converted once, and every encode path now starts by
resampling to square pixels at the display width (`scale=iw*sar:ih,setsar=1`). Viewers also compare the decoded frame's own shape with
the bitmap the catalog sized and correct a mismatch on the fly (`state().
shapes` shows the numbers); a zoomed mosaic cell now shapes the stage to the
cell instead of the whole mosaic. Reproduced in the rig with a 960×1080 SAR 2:1
file: passed through by a pre-fix publisher it arrives as a 960×1080 bitmap
(the decoder reports the same, so a viewer alone cannot tell -- the fix has to
be on the publishing side); converted by 0.9.8 it arrives 1920×1080. (A plain
`setsar=1` was tried first and merely relabelled the squeeze -- the pixels have
to be resampled.) Until the
owning KASTR runs 0.9.8, its anamorphic cameras still look squeezed to everyone.

**Fill-first auto grid.** Rows may hold different cell counts when that draws
more picture: five cameras are two large over three smaller (17 % black instead
of 44 %), three are two over one, six are three over three, ten are 3+3+4. No
cell is smaller than half the biggest, nothing is cropped, partial rows and the
whole block are centred. Drag-swap decides which cameras take the big cells.
Both ends must run 0.9.8 for a viewer's cell click to land on the right camera.

**Housekeeping.** The repo moved out of OneDrive to `C:\Users\KentonJeffery\
Claude\KASTR` (no more clobbered binaries mid-build). `dist/archive` holds one
folder per version with one zip per platform (`v0.9.8/KASTR-windows-v0.9.8.zip`,
`KASTR-linux-v0.9.8.zip`); only the version just built is kept.

Files: `kastr_rtsp.py` (job object, child registry + sweep, idempotent
`Bridge.publish`, SAR probe + `setsar=1`), `kastr_serve.py` (`/api/quit`,
`make_bridge(state_dir, log)`), `kastr.py`, `kastr-serve.py`, `close-kastr.ps1`,
`moq-watch-lite.html` (autoRows, aspect correction, Audio box, adoption, keep
default), `build.py` (archive layout).

## v0.9.7

- **Grid cells stop dropping out.** With four real cameras on passthrough the
  published feeds were rock solid (no restarts), but the owner's preview
  players behind the grid cells were being reconnected about once a minute
  each, and while reconnecting the cell showed "reconnecting…" -- that was the
  "random drops across all my cameras". The preview is now a Media Source
  player the page drives itself: it jumps over timestamp gaps, stays at the
  live edge by seeking inside its own buffer instead of speeding up or
  reconnecting, trims old data, and only reconnects when the camera stream
  really stops delivering. A brief reconnect keeps the last frame in the cell
  instead of flashing a placeholder. The bridge now tells the player which
  codec it is sending, so H.265 passthrough previews open correctly; a preview
  that cannot play at all falls back to a cheap H.264 encode as before.
- **The name strip on grid cells is gone.** It covered the cameras' own
  on-screen information bar. Names remain in the feed menus and on viewers'
  cell labels.

## v0.9.6

- **Fewer encodes per camera -- the fix for feeds dropping out with three or
  more streams.** KASTR's server is threaded and ffmpeg uses every core it is
  given; what starved the small boxes was the *number* of encodes: every
  camera that was not plain H.264 cost two full re-encodes (one for the
  published feed, one for the owner's preview and the grid) plus the relay
  sender. Now:
  - *Pass cameras through untouched* (Share ▸ RTSP) applies to every codec
    viewers can decode -- H.264 and H.265 today, including 4K and full-range
    H.264 that used to be converted -- so a camera costs zero encodes. Cameras
    nobody can decode as-is (MJPEG, MPEG-4) are still converted to H.264, once.
    The old "H.265 only" setting carries over.
  - The preview/grid stream follows the same rule (copied when it can be), and
    when it must be encoded it is now small and fast: 15 frames a second, at
    most 1280 wide, fastest preset -- a fraction of the old cost. If a copied
    stream turns out not to play in the window (H.265 on a machine without
    hardware decode) the preview falls back to a cheap H.264 encode by itself.
  - Linux machines with an Intel or AMD GPU get hardware encoding (VA-API)
    when a conversion is still needed.
- **Adding a camera twice is caught.** Adding an address that is already
  shared asks whether to replace the existing feed; the default keeps things as
  they are. (Two copies of one camera meant two publishers and two previews.)

## v0.9.5

- **The grid is live again.** The mosaic is drawn from each feed's local monitor
  picture, and since native publishing (0.9.1) nothing watched over those
  monitors: one that stalled or fell behind froze or delayed the grid for every
  viewer while the cameras themselves (published by the server) stayed live --
  the "grid isn't updating, the camera I open from it shows something
  different" report. The monitors now keep playing, catch up when they fall
  behind live, and reconnect when they freeze; a reconnecting cell says so
  instead of showing a stale frame. On the viewing side a picture that stops
  moving while data still arrives is now treated as a stall and re-subscribed.
- **Clicking a camera in your own grid opens that camera.** On the stage, a
  cell click now brings up the feed itself, full resolution, in place of the
  grid (click it again, or the "Grid" button, to return); the mosaic drops to
  the rail meanwhile. Wheel and double-click still zoom the mosaic.
- **Per-feed audio.** Each RTSP feed's menu has "Send audio: on/off" (and says
  when the camera has no audio track); the Share panel's "Send the camera's
  audio" sets the default for a feed you add. Off publishes video only. The
  choice is remembered per camera address.
- **Muting a grid mutes its feeds.** On viewers, the grid tile's mute and volume
  now govern the full-quality feeds heard behind it, and the grid tile keeps its
  audio controls whenever its feeds carry audio (they were hidden because the
  mosaic itself is silent, which is why muting it did nothing).

## v0.9.4

- **A camera that drops no longer rearranges anyone's stage.** When an RTSP
  feed in a grid disconnected, every viewer briefly saw that feed pop out of
  the grid as its own tile, the layout reflow around it, sometimes the stage
  jump to it, and then everything snap back when it reconnected. Three causes,
  all fixed:
  - Viewers now *remember* which feeds belong to a grid. A reconnecting member,
    or a grid announce that flickers, no longer un-hides the feed's tile; the
    tile only shows on its own when the grid is really gone (Separate feeds, or
    the grid removed).
  - The grid's geometry announce is only re-sent when it actually changes, and
    it lists a reconnecting member's path just like a live one.
  - A dropped camera no longer restarts its publisher from the page. The local
    monitor picture reconnects on its own ladder (now also when the camera is
    unreachable, which used to leave the monitor dead), the server keeps
    publishing the feed with its own retries, and the grid cell says
    "reconnecting… (attempt N)" instead of freezing on the last frame.
- Smaller fixes on the way: a full-quality feed that leaves the stage hands it
  back to its grid at that cell instead of promoting a sibling feed; the grid
  announce follows a relay change; a browser encoder failure no longer restarts
  RTSP feeds (they never used it); the feed's status line shows the publisher's
  last error while it is down.

## v0.9.3

- **Linux: the window opens in KASTR's own browser again.** The 0.9.x release
  zip stored the bundled browser's executables without execute permission, so
  on Linux `browser/chrome` could not start; KASTR then handed the URL to the
  system default browser (Firefox, which cannot run it) and showed the "close
  this message to stop" dialog. The archive now marks those files executable,
  KASTR restores the permissions itself on every launch, and the hand-off to
  the default browser is gone. If the bundled browser still cannot start, KASTR
  retries without Chrome's sandbox (Ubuntu 23.10+ blocks it for unpackaged
  programs), then tries a system Chrome/Chromium/Edge, and only then shows a
  dialog that says *why* -- with the browser's own last line -- and the address
  to open by hand.
- **Smaller.** The bundled Chrome is pruned to what a KASTR window uses (all
  locales but en-US, the installer/updater helpers, Widevine, DirectX shader
  compiler, hyphenation data: about 90 MB per Windows install, 70 MB on Linux;
  existing installs prune themselves on the next launch). The YouTube/video-page
  resolver (yt-dlp, about 5 MB of the binary plus sqlite3) is gone -- RTSP
  cameras, direct media URLs and HLS/DASH manifests still work; a video page
  is refused with a clear message. The browser-side RTSP publish path
  (captureStream -> WebCodecs), the corner tile-resize grip, the hidden
  Relay/Audio/Order controls, the MKV codec sniffer and other dead code left
  the page (about 440 lines); the unused upstream demo pages, the old Vite
  bundles, the non-SIMD MediaPipe engine, and 35 `.bak` files left the tree.
- **RTSP grid "One big + strip" without the black bars.** The strip is now a
  column on the left with true 16:9 cells, the big feed fills the rest at
  16:9, and the mosaic canvas takes the shape that needs no letterboxing
  (three feeds: 1920x720; four: 1706x720). Two feeds fall back to side by side.

## v0.9.2

- **The "Chrome for Testing is only for automated testing" bar is gone.** The
  bundled browser is started the way Chromium's own test harness starts it,
  which suppresses that infobar (and the unsupported-flags warning).
- **The RTSP feeds mode is always reachable.** *Grid + full-quality feeds*,
  *Grid only*, *Separate feeds* and *Lock cells* now live in **View ▸ RTSP
  feeds** and in every feed's ▾ menu, not only on the mosaic's menu (which does
  not exist while feeds are separate -- that was the "I lost the grid"). A hint
  appears when two or more feeds are set to Separate.
- **Zoom on your own feeds and files.** The stage zoom (wheel about the cursor,
  drag to pan, double-click, − / % / +) works on your own RTSP feed and shared
  file panes when they hold the stage, not only on the mosaic and remote tiles.
- **Optional H.265 pass-through.** Share ▸ RTSP: "Pass H.265 cameras through
  untouched". Off by default. A camera that already emits H.265 is then
  published as-is (roughly 30-50% less bandwidth than H.264, zero encode cost);
  everything else is still converted to H.264. Viewers need hardware HEVC
  decode; a viewer that cannot decode a stream sees "H.265 -- this viewer
  cannot decode it" on that tile instead of a black picture, and still hears it.

## v0.9.1

- **RTSP feeds are published natively -- no second encode, no window
  required.** Until now every camera was decoded and re-encoded inside the
  KASTR window before it reached the relay. KASTR now bundles `moq-cli` (the
  relay project's own publisher) and each feed goes ffmpeg -> moq -> relay
  directly: an H.264 camera is copied untouched (full quality, zero encode
  cost), anything else is encoded once by ffmpeg (hardware when available),
  and camera audio is carried for the first time. The page only monitors the
  feed; a viewer's "frozen" report restarts the pair server-side; a feed that
  dies is retried on the usual ladder. Grid modes work as before: the mosaic
  is still composed in the window, and in *Grid + full-quality feeds* the
  members publish natively. Machines without `moq-cli` fall back to the old
  browser path automatically.
- Why not MediaMTX: it is a protocol router, not an encoder, and its MoQ is
  the IETF draft dialect -- not compatible with KASTR's relay and web library.

## v0.9.0

- **KASTR is self-contained: it ships its own browser.** The app window runs
  in a pinned Google *Chrome for Testing* build (153.0.8010.36) that lives in
  the `browser/` folder next to KASTR, with its own profile. KASTR no longer
  depends on whatever Chrome or Edge a machine has, on that browser
  auto-updating underneath it, or on a stray Chrome window holding the profile
  after a crash. The first launch carries your saved name, rooms and settings
  over from the old profile; the camera and microphone permission is asked
  once again (it belongs to the browser profile).
  On Windows the launcher grants the bundled browser the sandbox file
  permissions Chrome's installer would have set (a bare copy lacks them and
  Chrome then opens a window that never loads).
- **The browser follows the fleet.** Like the binary, the browser folder is
  matched to the relay host's KASTR at launch (`/api/update/browser`), so a
  re-pinned browser reaches every machine; a missing or damaged folder is
  fetched the same way. `kastr.ini`: `browser = bundled` (default), `system`,
  or a path.
- Linux: `install.sh` checks the bundled browser's shared libraries and prints
  the apt line when something is missing. Relay-only boxes never start it.
- Release archives grow by the browser (~150 MB compressed per platform); the
  fleet-feed zips stay out of the archive (`updates/browser/`).

## v0.8.13

- **KASTR no longer loads its media library from the internet.** Until now the
  page imported the MoQ library from esm.sh at every launch, unpinned. On 9 Sept
  a new upstream release appeared and esm.sh could not serve it, so every
  installed KASTR opened to an empty Join box with no rooms. The library
  (`@moq/watch` 0.5.3, `@moq/publish` 0.4.6 -- the versions KASTR was tested
  with) now ships inside the app, pinned. If a module ever fails to start, the
  gate says so and offers Retry instead of sitting there blank.
- **Shared media files: everyone sees the video.** The file player captured its
  canvas at "0 fps", which the encoder turned into a frame rate of 0; hardware
  encoders refused it, so the room heard the file and saw black while the
  sharer's own preview looked fine. The player now captures at 30 fps.
- **Media files start at once after converting.** The converted file used to be
  downloaded whole into the page before playback; it now streams from the local
  server (with seeking) and is freed when the source is removed or after 12 h.
- **Clicking another grid while your own grid is on stage** brings it to the
  stage; it used to zoom inside the rail tile.
- **The launcher explains itself.** A `launch.log` in the KASTR state folder
  records every startup decision (the app has no console); a launch whose window
  never appears now shows a dialog with the address instead of exiting silently;
  a double-click while KASTR is already running verifies that the existing
  window answered; a post-update relaunch no longer closes its own new window;
  a stalled update download gives up after 60 s and keeps the current version.
- **ffmpeg 9.0.1 on Linux** (Windows already shipped 9.0.1). `/api/instance`
  reports the bundled ffmpeg version.
- Fix: the keyframe interval field was applied x1000 (a 33-minute GOP when set).

## v0.8.12

- **RTSP feeds at full quality, with or without the grid.** The composite's
  menu (▾) has a new group, *Publish feeds as*: **Grid + full-quality feeds**
  (default -- the 720p mosaic AND every feed on its own path at its real
  resolution), **Grid only** (one stream, as before) or **Separate feeds**
  (no mosaic at all). Viewers never see the extra paths as tiles: clicking a
  cell of the grid on the main stage now opens that feed itself, full
  quality, downloaded only while it is on the stage; click again (or the
  pill) to return to all feeds.
- **Real zoom and pan on the stage.** Any share on the main stage -- a feed,
  a grid, a screen -- zooms with the **mouse wheel** about the cursor (the
  page itself no longer zooms), pans by dragging, and has − / 100% / +
  buttons in the corner; double-click toggles 2×. Recordings capture what
  the viewer sees.
- **Locked grid cells.** A feed that drops keeps its cell (dimmed,
  "reconnecting…") and comes back in the same place; the arrangement is
  remembered across restarts by feed URL. *Lock cells* in the composite
  menu turns this off (the grid compacts as before).
- **Your own grid in the rail behaves.** A click on it brings it front and
  centre -- a slightly wobbly click used to swap two cells instead and
  swallow the spotlight. Cell swapping and cell zoom only work on the stage.
- **You can see what you share.** A screen or window share shows itself as a
  small live thumbnail in the bottom-right corner (with its menu, and a ▾ to
  collapse it to a pill). Sharing KASTR's own window shows a note instead of
  a hall of mirrors.
- **The side rail pages visibly.** The pager is a proper bar ("‹ Page 1/3 ›
  · 16 more"); the mouse wheel over the rail and PageUp/PageDown flip pages.

## v0.8.11

- **A machine without a camera can share.** Joining without a camera made
  you a viewer, and anything you shared afterwards (RTSP feed, media file,
  screen) sat in "previewing" forever because nothing ever pressed Go live
  for you -- nobody saw it. Any source added while you are in a room now goes
  on air by itself (a name from the Profile is still required).
- **Viewers show up in People.** Members who publish nothing are listed as
  "Name -- watching" and counted in the room chip, so a camera-less machine
  is visible to everyone.
- The ASI swoosh is centred on the compass hub (the small circle), not the
  ring.

## v0.8.10

- **Shared media files: everyone sees the video, and everyone gets
  controls.** KASTR now plays a shared file in its own player and feeds the
  picture and sound to the encoder itself (the library's built-in file
  player rendered nothing to the room -- you heard it, you did not see it).
  Every tile of a shared file carries a bar: **play/pause**, **position
  slider**, **loop**, and your own **mute/volume**; play, pause, seek and
  loop act on the owner's playback for the whole room. The owner's own pane
  has the same bar plus the file's broadcast volume.
- **Files that need converting are detected properly.** Before sharing,
  KASTR asks its bundled ffmpeg what is inside (any MKV, MP4, MOV, AVI,
  TS...): video the browser cannot decode (HEVC, MPEG-4, ...) is re-encoded
  to H.264, audio it cannot decode (AC-3, DTS, ...) to AAC; web-safe files
  are used untouched. The previous "copy the video" path could hand the
  browser an undecodable stream.
- **Uploads show progress and always find a store.** The Files card opens
  with a progress row while a file uploads (and a Retry on failure). If the
  relay host has no file service (older KASTR or unreachable), the file is
  stored on your own machine and announced under your LAN address -- with a
  note when your KASTR is bound to loopback so others cannot reach it yet.
- **Microphone meter works.** The Audio settings meter now reads your live
  mic when it is open and otherwise opens a **test tap** on the selected
  microphone (works before joining and while muted); the talking ring
  re-taps when you unmute or switch microphones instead of giving up after
  15 seconds.
- **Fixes:** radio buttons sit to the left of their labels; the ASI swoosh
  is centred on the compass ring; the breathing animation no longer drifts
  it.

## v0.8.9

- **Use KASTR on a phone.** ⋯ → **Phone access…** shows a QR code and link
  for this machine over **https**, plus a one-time certificate step per phone
  (iPhone: install the profile, then General › About › Certificate Trust
  Settings; Android: Security › Install a certificate › CA certificate). After
  that the phone joins with camera and microphone like any KASTR. The page
  gets a phone layout: icon toolbar, bottom-sheet menus, one scrolling column
  in Gallery, main-stage-only in Speaker view (the bandwidth saver), and a
  "Tap to unmute" pill when the phone blocks audio until you touch it.
  Requires the web host to be reachable on the network (the Relay page's
  "Allow other KASTR machines…" switch or relay-only mode); KASTR then also
  listens on https port 8443 and the relay adds a secure listener on 4445.
  Desktop machines are unchanged (fingerprint-pinned WebTransport).
- **Voice isolation** is selectable and works: Audio settings › Noise
  suppression › *Voice isolation* adds KASTR's own processing to the
  browser's suppression (band-pass, an adaptive gate that trims the hiss
  between words, a leveller). It is conservative by design: a loud fan stays,
  room hiss goes. Falls back to the browser's suppression alone on browsers
  without AudioWorklet.
- **Cleaner settings cards.** Camera ▾ › "More video effects and settings"
  opens a **Video output** card with only the video encoder settings; Mic ▾ ›
  "More audio settings" opens an **Audio output** card with the Opus and
  microphone-processing settings. Both also live under ⋯ › Settings.
- **Relay-only mode applies now.** The Relay page's relay-only checkbox
  gains an **Apply & relaunch KASTR** button that restarts the app in the
  chosen mode immediately.
- **Fixes:** the RTSP **Add** button no longer stays dead when the first
  bridge check raced the server (it re-checks when Share opens) and failures
  now show a toast; the profile picture card stays open while you choose a
  file, so you can drag and zoom right away, and the saved picture is cut
  from the full-quality original (up to 1024 px); the ⓘ next to *Media file*
  is a tooltip, not a click into the file picker; the redundant "Sharing"
  label is gone (the red dot and Stop sharing remain); the Sources list no
  longer lists the camera (the toolbar owns it); the side rail defaults to
  two columns with your own preview spanning the full width, avatar circles
  stay round in small cells, the ASI swoosh is centred, and the name bar
  stays visible in every layout alongside the mute/pause icons; the master
  volume is remembered; **MKV files with AC-3/DTS audio** now play with
  sound — KASTR spots the codec and converts the audio track to AAC with its
  bundled ffmpeg before sharing (video is copied, not re-encoded).

## v0.8.8

- **Teams-style controls.** The top bar is now icon-over-label buttons in
  the Teams order: People · View · Files · More ⋯ | Camera ▾ · Mic ▾ ·
  Share | Leave. Camera and Mic are always there -- on a viewer join they
  add your camera when clicked -- and their chevrons open proper settings
  cards.
- **View menu:** Gallery / Speaker / **Focus on content** (only the main
  stage stays -- everything else stops downloading, the bandwidth saver) /
  Hide me / Full screen.
- **Camera settings card** (Camera ▾): live preview, camera choice,
  Backgrounds (None, Standard blur, ASI navy, Soft mist, or your own
  picture), Adjust brightness, Soft focus, and "More video effects and
  settings" for the encoder page (moved out of the ⋯ menu).
- **Audio settings card** (Mic ▾): speaker choice with the master volume,
  microphone choice with a live level meter, Noise suppression switch, and
  "More audio settings" (also moved out of ⋯).
- **More menu** like Teams: Record, Room info, Files…, Video effects and
  settings, Audio settings, Profile…, Settings ▸ (About & updates, Video
  output), Help. The "Publish only" switch is gone: shared files, screens
  and RTSP feeds are publish-only by nature and never count as people.
- **Share menu** like Teams: "Share content" with an **Include sound**
  switch, **Screen** and **Window** cards (each opens the browser's picker
  on that pane), then RTSP/HTTP feed, **Media file** (with an ⓘ listing the
  supported formats) and **Upload File** (moved here from the room menu).
  Camera and microphone are no longer offered as "sources" -- you cannot
  hide your presence from the room by sharing without a camera.
- **Profile.** ⋯ → Profile…: first name, last name and a picture you can
  zoom and drag inside the circle (or clear). The first launch asks for it
  once; after that KASTR **joins your last room automatically** -- the room
  picker only appears when there is no remembered room or after Leave. The
  profile picture setting moved here from the ⋯ menu.
- **Expand one feed of someone's RTSP grid.** With their grid on the main
  stage, click a cell to fill the stage with that feed; click again for the
  whole grid. A **Gallery** pill takes you back to the gallery.
- **RTSP feeds that survive a restart.** Tick "Keep sharing this feed after
  KASTR restarts" when adding a feed (or "Keep after restart" in the pane
  menu). After the automatic join, the feeds are re-added and go live.
- **Room up-time.** Rooms other than main show how long they have been up
  in the room chip ("Room: ops · 3 · 1h 12m") and in the ☰ rooms list.
- **Updates that really restart.** A runtime update (Check for updates or a
  relay switch, now also from the Relay page's "Point KASTR at this relay")
  closes the app window first -- politely, then by force if the window
  belongs to a browser we did not start -- and relaunches detached from the
  dying process. Leftover `KASTR.old-*` files are swept again 10 s and 60 s
  after the relaunch.
- **Gallery** centres a short last row. Initials are white; the ASI swoosh
  fills more of the circle and the person's colour is the ring. The
  equalizer shows only on audio-only shared content, never on a camera.
- **Files** button in the top bar (badge = files shared) with download
  links, including files shared before you joined.

## v0.8.7

- **Relay history with live status.** The relay popover (top right) now
  lists the last **5** relays you connected to, each with a green
  *Available* / red *Not available* light (re-checked every 10 s while the
  popover is open). Click an entry to put it in the relay field, then
  **Connect**.
- **Updates can no longer strand you on `KASTR.old-...exe`.** If the new
  binary cannot be placed (antivirus / OneDrive holding the file), the swap
  retries and then puts the original back, so `KASTR.exe` always exists.
  Leftover `KASTR.old-*` files from earlier updates are removed at every
  launch.
- **Frozen camera, fixed by the people who see it.** When a viewer's tile
  stops receiving picture for 5 s, their KASTR tells yours; your side
  nudges the encoder (pause/unpause) and, if the viewer still reports it,
  rebuilds that source -- exactly what leaving and rejoining did, per
  source, without you doing anything. You see a small note ("A viewer
  reported your camera frozen -- rebuilt it"). The viewer also re-subscribes
  on its own after 12 s in case the fault is on its side.
- **Recording: name it, choose where it goes.** Stop now opens a small
  dialog: edit the file name, **Save as...** (a real file picker that
  remembers your recordings folder), **Download** (Downloads folder as
  before) or **Discard**.
- **Side rail never squishes.** Your own preview is pinned to the bottom
  of the rail on every page; everyone else pages above it (‹ 1/3 ›).
- **RTSP grid layouts + drag-and-drop.** The composite pane has a layout
  menu (▾): Auto, 2 × 2, One big + strip, Side by side, Stacked --
  remembered. Drag a feed onto another cell to swap them; everyone sees the
  new arrangement.
- **Rename while live.** Changing your name now re-publishes every live
  share under the new name (viewers see the old one go and the new one
  arrive within a few seconds). Previously a shared screen kept the old
  name until it was removed and re-added.
- **Softer join/leave sounds.** A gentle three-note chime up (join) and
  down (leave), quieter and without the abrupt cut.
- **Profile pictures.** ⋯ Options → **Profile picture...** picks a photo
  (downscaled locally). It fills the circle wherever your initials showed
  -- on your own pane and on everyone else's view of you. Without a photo,
  initials sit in an ASI-colored circle over a faint swoosh, each person
  in their own ASI color.
- **Share a file with the room.** ☰ room menu → **Share a file...**
  (up to 500 MB). It is stored on the relay host's KASTR and listed in a
  new **Files** section of the People page for everyone, with a download
  link; it is deleted when you leave the room (or with ✕).
- **Publish only.** ⋯ Options → **Publish only -- don't watch the room**
  for machines that only share (RTSP box, screen source): nothing is
  downloaded or heard. People counts now count **cameras** -- a box that
  only shares RTSP or a screen is a share, not a person.
- **Which relay is someone on?** People groups say "· via <relay name>"
  (the name given to that relay on its Relay page).
- **Grid view name bar.** In the grid, the name stays visible in the same
  bar as the mute/pause chips; only the spotlight side rail keeps the
  hover reveal.
- Relay page attribution ("via" per stream) now actually works -- it was
  feature-detecting a method that this library version keeps elsewhere.

## v0.8.6

- **Record the meeting.** A **Record** button in the top bar captures the
  stage exactly as you see it -- every visible tile at its on-screen size,
  plus everyone's audio and your own -- and saves a `.webm` to your
  Downloads when you press Stop (`KASTR-<room>-<date_time>.webm`). Everyone
  in the room gets a 5-second "Recording started by ..." notice and a red
  REC indicator for as long as anyone records.
- **Updates follow the relay you're on.** Switching relays now checks that
  relay host's KASTR version immediately and updates if it differs (KASTR
  restarts itself). There's also a **Check for updates** button in the
  version popover and in About.
- **Room passcodes stick.** When a room's creator left and came back while
  someone else was still inside, the passcode requirement silently
  vanished. Every member now holds the room's lock record, so it persists
  for as long as anyone is in the room.
- **Shared content fits the stage.** In spotlight view the shared window
  is sized to its own aspect ratio inside the available space: no black
  side bars, no gap at the bottom, and everything shared stays visible.
- **Less bandwidth when it doesn't matter.** Tiles you can't see -- when
  KASTR is minimized or hidden, or another tile is full screen -- stop
  downloading video (audio unaffected). RTSP/HTTP feeds and the grid
  composite now also publish a second, small rendition so a viewer with a
  thumbnail-sized tile pulls ~400 kbps instead of the full stream.
- **Camera freezes.** Two fixes: when your camera stops delivering frames
  (locked screen, another app grabbed it) KASTR now pauses your video for
  viewers instead of leaving them a frozen frame, and resumes with a fresh
  keyframe when frames return. And if the encoder wedges *while someone is
  watching* (frames stop although the camera is live), KASTR nudges it the
  way you did by hand -- pause/unpause -- and rebuilds the source if that
  doesn't take. This never fires on an idle source with no viewers.
- **Background blur** now keeps only *you* sharp: other people in the
  background are blurred with the background. Blur also no longer drops
  off when you switch relays.
- **Audio-only files** show an equalizer that moves with the sound.
- **People page** simplified: Stats and Diagnostics panels are gone, and
  so is the per-stream "hear this stream" selector -- everyone is always
  heard; per-stream mute and volume remain.
- **Relay page**: a new **"Allow other KASTR machines to update from this
  one"** checkbox makes any KASTR an update source without relay-only
  mode (binds the network at next launch + firewall rules now). The relay
  popover shows what KASTR version the relay host runs.
- **"Encoder settings" is now "Video output."**
- **Release zips now include the `updates/` folder**, so one archive is a
  complete deployment that can also serve updates to the other platform.
- Note on connecting without running a relay: it always needs *a* relay.
  When two machines connect "ad hoc", they are both on the same relay
  (yours was pointed at a shared one) -- the Relay page's "Currently used"
  line shows which.

## v0.8.5

- **Grid view tiles your own sources immediately.** Adding or removing one
  of your own sources left the grid laid out for the OLD count for 5-10
  seconds (until the relay happened to echo the stream back), so new tiles
  sat stacked full-width top-over-bottom before snapping into place. The
  page now watches its own-source panes directly and re-lays the grid the
  moment one appears or leaves.

## v0.8.4

- **Grid view no longer stacks your own sources full-width.** When
  multiple RTSP/HTTP feeds merge into the grid composite, the individual
  member tiles are now hidden entirely (the composite IS the view)
  instead of lingering as invisible cells that padded the grid and, on a
  tall window, collapsed it to one full-width column. Grid view now shows
  exactly the one composite tile; removing a feed brings the layout back
  cleanly.
- **Relay-only mode is now truly turnkey — just tick it and relaunch.**
  A relay-only machine (Relay page → "Relay-only machine", or
  `mode = relay` / `--relay-only`) now binds all network interfaces,
  autostarts the relay on the LAN, and adds the firewall rules on first
  run (one Windows admin prompt; Linux uses the desktop's authorization
  or prints a `sudo` line on a headless box). That's everything the
  fleet needs to update from it — the reachability gaps that silently
  blocked updates before are handled automatically now. Every KASTR
  build also ships carrying both platforms' update binaries, so one
  relay machine updates the whole mixed fleet (Windows + Linux) with
  nothing to copy.
- **Your own preview shows the blue talking border now.** The own-tile
  talking ring only ever armed for shared files/screens; a camera's mic
  is managed differently inside the library, so your camera preview
  never lit up. It now taps the camera's mic the same way, so your own
  tile rings blue when you talk, like everyone else's.

## v0.8.3

- **Multiple RTSP/HTTP feeds publish as ONE stream.** Two or more
  RTSP/HTTP sources automatically merge into a single "RTSP Grid"
  share: an auto-adjusting mosaic (grid sizes itself to the feed
  count, each cell labeled) published as one 720p/15fps broadcast —
  one path on the relay instead of N. Drop to a single feed and it
  automatically returns to a normal standalone stream, live, without
  a restart. The grid gets the same relay-truth badge and self-heal
  as everything else.
- **Signal first, quality second.** With encoder settings on Auto,
  KASTR now caps itself at 1080p and 1200 kbps (was: match the
  source, uncapped — a 4K camera would silently try to push a 4K
  encode). Any explicit setting still overrides. The "Negotiated"
  line now also says **· hardware** or **· software** so you can see
  at a glance whether hardware encoding engaged.
- **Hardware acceleration on Linux.** Chromium ships VA-API video
  acceleration off on Linux; KASTR now launches with it enabled, so
  Linux boxes stop silently software-encoding. (Windows already has
  hardware video on by default.)
- **Spotlight stops jumping around.** The stage auto-moves only TO
  shared content (screens/files/RTSP), never to a camera — and once a
  share holds the stage, a second share arriving does NOT steal it.
  When the spotlit share ends, the stage moves to a remaining share
  (or back to the grid if none).
- **Why your tester's 0.8.1 didn't update — and how you'll know next
  time.** The updater failed in total silence (its probe timeout was
  a bare return, and the app has no console). Every launch now
  records the check's outcome, and the Relay page shows it — in red
  when the version authority was unreachable. **Ops note**: the fleet
  updates FROM the machine named in `relay =`; that box must have
  KASTR running, `host = 0.0.0.0` in its kastr.ini, and all four
  firewall rules — the 0.8.2 firewall check will tell you if the
  "KASTR web" rule (the update port) is missing, and the button adds
  it. That missing web-port rule is almost certainly what blocked the
  tester's update.
- **Relay-only mode is a checkbox now** (Relay page → "Relay-only
  machine"): it writes `mode = relay` into kastr.ini for you; the
  next launch boots straight to the Relay page. `--relay-only` still
  works too.
- **Relay address history + sticky relay.** The masthead relay field
  remembers every address you've connected to (dropdown suggestions),
  and the app now REOPENS on the last relay you used — the choice
  survives relaunch instead of reverting to kastr.ini.
- **Join/leave chimes are louder** (nearly 3× the level, longer tail)
  after "difficult to hear".
- **Tile borders are consistent**: no tile wears a standing blue
  border anymore (remote tiles had one, yours didn't). The only
  border highlight is **talking**, and it's now blue instead of
  green.
- **Encoder settings show immediately** — the popover no longer hides
  everything behind a second collapsed "Encoder settings" section;
  the video fields are open on arrival.
- **Sharing your own KASTR tabs is allowed now** (the red border
  marks it). Note on tab sharing: a browser can only list its own
  tabs — that's Chromium, not KASTR. To share a page that's open in
  Chrome/Edge/another app, pick that **window** in the share picker's
  Window pane (the Share panel says this too).

## v0.8.2

- **Mute means silence, everywhere.** Muting a tile now drives its
  volume to exactly zero (the library's documented teardown edge)
  instead of trusting a near-zero floor, the muted tile wears the
  mic-slash chip, and the tile's chevron gains **"Mute (name)
  everywhere"** — one click silences every stream that person publishes
  (the old behavior kept their other streams audible).
- **RTSP/HTTP shares get relay truth and self-healing.** RTSP slots
  were the one publish path with no relay echo: they could badge
  ON AIR while nothing reached other machines (the Linux "RTSP stays
  local" report). They now use the same 8-second discovery-echo test
  (badge flips to NO RELAY within seconds of the relay losing them)
  and the publish self-heal rebuilds a wedged RTSP connection around
  the same ffmpeg feed — verified: relay killed and restarted mid-
  stream, badge NO RELAY → ON AIR, no restart needed.
- **Side rail pages like Teams.** In spotlight view the rail no longer
  shrinks forever: tiles keep a readable size and extras page behind a
  **‹ 1/2 ›** pager at the rail's bottom. Paged-out tiles stop
  downloading video (audio unaffected). The rail is also **resizable**
  — drag its inner edge; past ~300px it becomes **two columns**, and
  the width is remembered.
- **Paused tiles match Teams**: a camera-off chip joins the mic-off
  chip in a bottom-left row (always visible), the "audio only" caption
  is gone (the face is initials + art), and chips never sit under the
  name. Hovering a camera tile shows just the person's name ("Kenton");
  shares keep "Kenton — File" so two shares stay tellable apart.
- **Your tiles lead the grid** (first cell, not last) and stay at the
  bottom of the spotlight rail.
- **Join/leave chimes**: a soft two-note rise when a person joins the
  room, a fall when their last stream leaves. Per person, debounced
  against flaps, silent for the first seconds after connecting and
  under master mute.
- **Background blur** (beta): the camera menu (top-bar chevron) gains
  "Blur background" — person segmentation runs on-device (bundled
  MediaPipe, no internet needed) and publishes the composited video.
  Costs real CPU; off by default, per session.
- **You appear in People**: a "(you)" group tops the list with your own
  streams, and the count includes you ("2 people · 3 streams"). Stats
  and Diagnostics stay hidden until a stream is selected — each row's
  new chevron selects it and opens its stats in one click.
- **Relay-box ergonomics**: the firewall button only appears when rules
  are actually missing (a green "rules are in place" line otherwise —
  and the check covers the web port rule the button adds); a new
  **"Start KASTR when this machine boots"** checkbox (per-user, no
  admin; Windows Run key / Linux autostart entry; installed app only);
  **relay-only mode** (`mode = relay` in kastr.ini or `--relay-only`)
  boots straight to the Relay page with autostart forced and no app
  nav — same binary, so the fleet updater still applies; "Connect to
  it" lists the **LAN address first** (127.0.0.1 never travels).
- **Hub/spoke visibility**: the Federation panel gains a **relay name**
  (it becomes the stats node, so the stats page and stream attribution
  say "garage", not a host slug), the federation URL field stays in
  sync with the server, and on a hub the streams panel labels each
  stream **"· via (spoke)"** when several relays federate.
- **The Go Live tab's disconnect plug is gone** (app shell): the tab
  button only opens/fronts the page; leaving a room lives in the page
  itself, so a mis-click can't hang up a meeting.
- Relay reconnect now also rebuilds a connection stuck in "connecting"
  for 20s (not just one that reports "disconnected"), so field
  machines never sit amber indefinitely.

## v0.8.1

- **The fleet updates itself from the relay host.** At launch, every
  KASTR asks the KASTR instance on its relay's machine what version it
  runs; if different, it downloads that binary, verifies the checksum,
  swaps itself, and relaunches — upgrades AND downgrades ("match client
  to server"). Ops setup, once, on the relay host: set
  `host = 0.0.0.0` in its kastr.ini so clients can reach its web port
  (the firewall button now opens that port too), and build with
  `--publish` (or copy `dist/updates/` next to its binary) so it can
  serve the OTHER platform's binary as well as its own. Opt out per
  machine with `update = off` in kastr.ini or `--no-update`.
- **Relay federation, one field.** The Relay page's new Federation
  panel: paste a hub relay's URL, Save — this relay clusters to it, and
  rooms/streams flow across every federated relay with no client
  changes. The hub machine needs nothing. (LAN certs are trusted
  without verification — the trusted-LAN tradeoff, since KASTR relays
  use throwaway self-signed certs.)
- **The relay stats page finally works** — one missing line: the relay
  never named its stats node, publishing at a path the stats page is
  built to ignore. It now shows a node card with live counters. (The
  stats badge hides on windows narrower than 900px by design.)
- **Teams-parity stage**: names, chevrons and your own labels appear on
  MOUSEOVER only (a NO RELAY warning still forces itself visible);
  Full screen moved into each tile's chevron; a dark mic-slash chip
  bottom-left shows ONLY when that stream is muted; your own preview
  tiles sit at the BOTTOM of the grid; your own paused tile now matches
  the remote standby face exactly (and no longer covers your name —
  that was the "lost overlay" report); the spotlight side rail resizes
  so every tile stays in view.
- **No self-preview of your own screen share** — you're looking at the
  screen already. Instead, starting a screen share pops a small
  always-on-top **mini control window** (mute mic / stop sharing / back
  to KASTR) so you can control the meeting from any app.
- **People is a popover now** — drops down from the People button,
  closes on any outside click — and it counts PEOPLE: one entry per
  name, with that person's streams grouped beneath ("Kenton — 2
  streams").
- **Stuck green rings fixed**: a muted stream's tile could keep its
  talking border forever (muting tears down the audio meter, which
  froze the ring's last state). Rings now clear the moment the meter
  goes away.
- **Room list count**: the current room now counts from live tiles
  (right even on room-code relays); other rooms keep the scan count.
- **Firewall button actually works**: the elevated command was dying in
  PowerShell quoting — it now runs a script file instead (and also
  opens the KASTR web port).
- **Noise suppression toggle** in the top-bar mic menu.
- Cold start: device pickers repaint when the browser announces
  devices, and every launch busts the browser cache ("stale app" fix).
  Relay reconnect after a long outage verified end-to-end (35 s outage
  → green + reconnected without touching anything). The masthead relay
  popover's Apply button is now "Connect".

## v0.8.0

- **Stream from the web.** The RTSP button is now **RTSP/HTTP**: paste a
  direct video URL (mp4/webm/HLS) or a YouTube link — page links resolve
  through a bundled yt-dlp. Caveat: YouTube changes their side now and
  then; if YouTube links stop resolving, a KASTR rebuild with a newer
  resolver fixes it (direct media URLs are unaffected).
- **Relay autostart**: the Relay page gains "Start the relay when KASTR
  launches" — it remembers port/LAN/room-code choices and brings the
  relay up on its own at every launch. (Hand-edit fallback:
  `relay_autostart = true` in kastr.ini.)
- **One-click firewall rules**: an "Add firewall rules" button next to
  the printed commands. Windows shows the admin (UAC) prompt and runs
  the three rules; Linux desktops use pkexec; headless boxes still get
  the commands to run. Only accepted from the machine itself.
- **Rooms live on for 5 minutes after everyone leaves** — the leaver's
  page quietly holds the room's listing, so walking to another machine
  doesn't lose the room. (Closing the app entirely releases it early.)
- **Create new room from the ☰ menu** while already in a room — name +
  optional code, no trip back to the join gate.
- **Audio activity is the border, not a bar**: the VU bars on tiles,
  rows and faces are gone; the green ring is the one signal — and your
  OWN tiles now get the ring too when their audio is live.
- **Hear your own file**: playing a shared file is now audible to you
  locally (it always was to everyone else); its Mute audio also mutes
  your local playback.
- **Paused looks the same everywhere**: your own paused tile shows the
  initials + swoosh standby face, exactly like remote paused tiles, and
  resuming re-keys the encoder so viewers stop seeing a frozen pre-pause
  frame.
- **Every stream window's chevron has "Mute here"** — a local mute for
  that one stream, on remote tiles and your own alike.
- **Names that stick, everywhere**: the install now remembers "Your
  name" server-side, so it survives even browsers that silently lose
  their storage (the Linux report). Any device that lost it gets it
  prefilled from the install.
- **Linux launches the real app now**: the shipped Linux config pointed
  at the plain index page instead of the tabbed shell — which is why the
  Go Live / Relay Server buttons had no connection lights there. Both
  platform configs are regenerated (and now identical).
- **Spotlight side-tiles stop jumping**: the automatic speaker
  enlargement (the 1–3 second zoom every few seconds) is gone; tiles
  hold their size and the ring marks the speaker.
- **RTSP/HTTP shares can hide their preview** ("Hide preview" in the
  chevron — the stream keeps broadcasting; decoding must continue by
  browser design, so this saves screen, not much CPU).
- Empty device pickers now say "No camera detected" / "No microphone
  detected" / "No output devices detected" instead of sitting blank.
  Options menu wording: "Audio Output…". Shared-file labels always read
  "Name — Filename" (a camera-less join used to drop the name from
  every share, for every viewer — fixed).

## v0.7.8

- **Your own streams are now real tiles.** Camera, screen, RTSP and file
  each get their own cell in the grid — same size, same look, same
  bottom "Kenton — Camera" label as everyone else's streams. No more
  one card cramming your streams together (the "stacked full-width /
  stacked full-height" layout bug lived exactly there). Rows now have a
  fixed height too, so nothing can stretch the grid out of shape again.
- **Click yourself to spotlight yourself** — your tiles click exactly
  like remote tiles: click to spotlight, click again for the grid.
- **View button**: "View: Grid" / "View: Spotlight" in the top bar
  switches layouts manually whenever you want.
- **"They can't see me" — fixed at the root.** The watch side always
  healed itself after a relay blip (you kept seeing everyone), but your
  outgoing streams had no heal at all and could stay silently dead
  (they stopped seeing you). Streams now self-heal: live for 20 s with
  a healthy relay and no echo of your stream from it = rebuild,
  automatically. Verified: relay restarted mid-broadcast, streams back
  on air within ~40 s with truthful badges throughout.
- **RTSP streams don't open a window until they're actually
  delivering** — a dead camera no longer opens a black pane — and a
  failure now pops up a notice with the reason (ffmpeg's own words)
  instead of hiding in a badge.
- **The relay light works on every page now.** Pages without their own
  relay connection (the Relay Server page, the shell) probe the in-use
  relay over HTTP: green while it answers, red within ~15 s of it going
  away.
- **"Streams on this relay" unstuck**: the panel now probes the relay
  KASTR is actually pointed at (the shared/external one included), not
  only a locally hosted relay, and names it — "2 streams in 1 room on
  10.10.105.190:4443".
- **Cleaner self view**: the row strip under your streams is gone; each
  share's chevron menu now carries Mute/Unmute audio, Pause/Resume
  video, Stop sharing (and Spotlight for everyone when several shares
  are live). The camera's controls stay in the top bar.

## v0.7.7

- **Chevrons toggle**: clicking the chevron that opened a menu now closes
  it — everywhere (top bar, share overlays, tile overlays, rows).
- **Top-bar mic/camera icons centered** in their buttons.
- **The join gate is dismissible**: a ✕ (and Esc) closes it without
  joining — for machines that only host the relay and never join a
  stream. The masthead relay control is reachable again once the gate is
  closed (this is the "can't click the relay server" report — the gate
  covered the in-page relay badge; the shell's Relay Server tab was never
  blocked). Way back in: the room chip (now "Join a room…") or the ☰
  rooms button reopens the gate. Leave hides while you're not in a room.
- **Camera no longer comes up empty on app start**: the silent rejoin
  could fire before Windows finished enumerating devices, quietly joining
  you as a viewer — a refresh "fixed" it. Joining now waits out that race
  (up to ~3 s) before deciding you have no camera.
- **Room occupancy badges**: the join gate's room list shows how many
  people are already in each room ("main — 2 here", refreshed every 5 s,
  and your in-progress selection survives the refresh); the room chip
  shows a live count while joined ("Room: main · 3"); the ☰ room menu
  shows counts too. Counts publishers (everyone who joined with a
  camera/share); on room-code relays the pre-join counts aren't visible
  to an anonymous scan, so the gate badge is omitted there.
- **The Relay Server page lists the streams flowing through it** —
  refreshed every 5 s, from any machine pointed at that relay. A stream
  badged ON AIR anywhere MUST appear in this list; if it doesn't, that
  device is on a different relay. On room-code relays the anonymous
  probe can only see rooms, and the panel says so.
- **The layout recomputes when the window does.** 0.7.5's fixed-size
  tile cards were computed once and could go stale after a resize —
  tiles frozen at the wrong width stacked full-screen, one on top of the
  other, until the next state change. The stage now relayouts on every
  window/stage resize. Also: when you share while your camera is up,
  your self-view card shows the camera and the share **side by side**
  instead of stacked.
- **Speaker icons replace the ♪ note glyph** everywhere it marked audio
  state (no-audio markers on tiles and rows, the "audio only" face).

**Multiple relays CAN be joined into one federation** (research result,
config-only, nothing to build): the bundled moq-relay 0.14.12 supports
symmetric clustering — a broadcast published to any clustered relay is
visible through every other, with unchanged paths, so rooms and
discovery just work across machines. Minimal LAN recipe: pick one hub
machine (a relay-only box is ideal; start its relay with Allow LAN); on
each OTHER machine add to its relay config:

```toml
[cluster]
connect = ["https://<hub-ip>:4443/"]

[client.tls]
disable_verify = true   # trusted LAN; the relays use throwaway self-signed certs
```

Every relay also needs a unique `[stats] node` name once clustered. The
hub going down pauses federation (local streams keep working) and heals
automatically when it returns. KASTR doesn't yet write these keys into
its generated config — say the word and a "Join relay federation" box on
the Relay page can do it. Note: with "Require room codes", clustering
additionally needs the same auth key on every machine plus a
relay-to-relay token — worth doing as a KASTR feature rather than by
hand.

## v0.7.6

- **The main camera's mic/video buttons live in the top bar**, by the
  Leave button, Teams-style — with their device-pick chevrons. The
  self-view card no longer shows a row for your own camera (its preview
  stays); shared sources keep their rows.
- **Shares wear their menu on the window itself**: screen, RTSP and file
  shares get a chevron overlaid on the video (top-right), with Stop
  sharing — and, when more than one share is live, Spotlight for
  everyone. Other people's shared-content tiles get the same overlay
  chevron with Spotlight for me / Spotlight for everyone.
- **Stop sharing (all) button** next to Share: one click ends every
  screen/RTSP/file share at once. Only visible while sharing.
- **Spotlight for everyone**: choosing it puts that share on every
  connected user's stage (a lightweight room-wide signal; the newest
  choice wins, and it releases when the chooser leaves or stops). A
  single share still spotlights automatically for everyone, as before.
- **Fixed: going live on a room-code relay silently killed every
  publish.** The go-live step rewrote the publish connection's URL
  without its auth token; the relay refused the stream while the badge
  still said "ON AIR". Devices on a secured relay each saw only
  themselves.
- **The ON AIR badge now tells the truth**: it turns "NO RELAY" when the
  relay hasn't actually accepted the stream within ~8 seconds — whatever
  the cause (auth, wrong relay, network). Previously it was impossible
  to tell a dead publish from a live one.
- **See which relay each device is on**: hover the "Room:" chip — its
  tooltip now reads "Room main via http://…". The People panel's stats
  already listed the relay.
- **Cloned machines no longer collide**: broadcast paths embed the
  machine name, and two boxes imaged from the same install (same
  hostname) produced byte-identical paths — colliding on the relay and
  suppressing each other's tiles as "their own", so each device saw only
  itself. The path's host segment now carries a stable per-machine
  suffix (from the network adapter), invisible in the UI.

**If devices in the same room can't see each other after updating:**
on each device, hover the "Room:" chip and confirm every device names
the SAME relay — if one says `127.0.0.1` or an old address, point it at
the right relay via the masthead badge (top right). A pane badging
"NO RELAY" means that device's stream is not reaching the relay it
names. And note "Point KASTR at this relay" hands out `127.0.0.1`
unless "Allow LAN" was checked when the relay started — other devices
need the LAN address.

## v0.7.5

- **Teams-style tile cards.** The grid view now lays everyone out as
  uniform 16:9 cards — video cropped to fill the card, the block of
  cards centered in the stage, and the card size recomputed as
  participants and shared streams come and go. In the focused view the
  side tiles crop the same way; the main picture keeps its full frame,
  so shared screens never lose edges.
- **Your room survives page reloads and tab switches.** Joining a room
  now saves a rejoin ticket for the life of the app window: any reload
  of the Go Live page (including the disconnect plug re-opening it)
  silently rejoins the same room with your saved name, mic/video
  toggles, and room code — re-minting on secured relays. The ticket is
  cleared only by Leave, a deliberate disconnect, or closing the app.
  Switching rooms updates the ticket, and a stale code falls back to
  the normal join gate with “Wrong room code.”
- **The disconnect plug asks before dropping a room.** The plug shares
  the Go Live tab button, so a mis-click could cost the room. Joined =
  “Leave the room and disconnect?” first; OK leaves properly (camera
  released, ticket cleared), Cancel just fronts the tab.
- **Linux: your name (and everything else) finally sticks.** Ubuntu's
  default Chromium is a snap, and snap confinement silently denies the
  browser access to KASTR's profile under `~/.local/share` — so the
  browser ran on a throwaway profile and “Your name”, rooms, and sizes
  vanished every launch. With a snap-confined browser the profile now
  lives at `~/snap/chromium/common/kastr-profile` (a place the snap may
  touch); non-snap browsers are preferred when installed, and both the
  launch log and `--diagnose` name the profile in use.
- **The Relay tab's running-light actually runs.** The red on-air dot
  read status from the Relay tab's page, so it went dark whenever that
  tab was closed — and a throttled background tab could leave it stuck
  on. The shell now asks the server directly: the light follows the
  relay process itself, on every platform, within a couple of seconds.

## v0.7.4

- **The Relay page's firewall hint speaks the server's language**: on a
  Linux-hosted KASTR it now shows the ufw commands instead of PowerShell
  (the page asks /api/instance which OS is serving — the firewall being
  configured is the host's, not the browser's). Both platforms' commands
  now include the room-code port (TCP port+1) alongside the relay port.
- **The self-view's camera/mic menus open upward when needed**: the
  controls moved to the bottom of the preview card in 0.7.0, and the
  menus kept opening downward — off the bottom of the window, looking
  like the chevron did nothing.

## v0.7.3

- **Linux: a browser that cannot open a window no longer takes the
  server with it.** $DISPLAY can be set yet unusable — root inside a
  desktop session hits the X server's “Authorization required, but no
  authorization protocol specified” (plus D-Bus refusals), Wayland-only
  sessions and snap confinement fail the same way — and KASTR waited a
  silent minute, then quietly shut down under the very URL the errors
  said to open. Now: the crash is detected within a second, KASTR says
  it is still serving (with a root-specific hint), and stays up — open
  the printed URL in any browser and the normal window lifecycle takes
  over from its heartbeat. Windows behaviour is unchanged.

## v0.7.2

- **Linux: headless machines serve without a window.** With no $DISPLAY
  or $WAYLAND_DISPLAY (servers, SSH sessions, root shells outside the
  desktop's environment) Chromium exited with “Missing X server” and
  took the server down with it. KASTR now detects the headless case,
  keeps serving, and prints the URLs — including the reminder that
  reaching the UI from another computer needs `--host 0.0.0.0` (or
  host in kastr.ini).
- **Linux: launch from the GUI.** `sh install.sh` (in the linux folder)
  registers KASTR in the applications menu with its icon — GNOME's file
  manager refuses to run raw binaries by design, so the launcher is the
  double-click answer. The CLI works as always.
- **Release archives keep a keepsake per line**: the newest archive of
  each x.y series (0.6.x, 0.7.x, …) now survives pruning alongside the
  usual last five.

## v0.7.1

- **Linux: runs as root.** Chromium refuses to start its sandbox as root
  (crbug.com/638180) and quit before the window appeared — seen on an
  Ubuntu machine driven as root, which is normal on robot/industrial
  boxes. KASTR now detects root on Linux and passes --no-sandbox itself;
  the window only ever loads the app's own local pages. The Linux README
  says so too.

## v0.7.0

Room codes become REAL, and the meeting chrome takes its 0.7 shape.

- **Secured relays.** Hosting a relay gains “Require room codes”: the
  relay then verifies signed tokens on every connection, and a token
  service on relay-port+1 mints them — the room code is the only
  credential (no accounts, no user list). Locked rooms register with
  the minter; a wrong code is refused by the SERVER, not the page, and
  on secured relays the room announce carries only a locked marker —
  no crackable material is published. Open relays are untouched, and
  pages work against both without a setting. Honest limits: open rooms
  are open to anyone who can reach the relay, codes travel over plain
  HTTP on the LAN, and room names/lock status stay listable.
  (Found and fixed on the way: the relay's key loader mangles absolute
  Windows paths, so the key rides a relative path + working directory.)
- **My preview joined the stage**: the top-left cell of the collage, or
  the top of the ladder in the spotlight, with the name and mic/video
  controls attached to its bottom — the top bar carries controls only.
- **Share panel, distilled**: three square buttons (Screen / RTSP /
  File) and the Sources list — Devices, Broadcast and Status left the
  panel (their machinery drives the join flow untouched).
- **An ⋯ Options menu** carries Audio &amp; output, Encoder settings,
  About KASTR (the old home page's identity, now that the ASI logo is
  just a logo) and Help at the bottom. Rooms moved to a ☰ menu beside
  the “Room:” chip. Popovers collapse on any outside click.
- **Room code, not password**: the inputs are masked text fields the
  browser's password manager ignores — no more save-password prompts.
- **Disconnecting Go Live returns to its start page** (the join gate),
  never some other tab.
- **The stuck-red relay light is fixed for joined pages too**: a
  connection dead for 10 s is rebuilt (discovery AND the room's
  registry announce), with a fresh token when secured.
- **Shared streams carry a chevron** with the one action they need —
  stop sharing.

## v0.6.10

Teams-style stage layouts.

- **Collage**: everyone in the room in a uniform best-fit grid that
  recomputes as people join and leave — the stage fills, never scrolls.
  (The 0.6.3 manual tile sizes and corner grips are dormant, not
  deleted.) Drag still reorders.
- **Spotlight**: click a tile — or share anything that is not a camera
  (screen, RTSP, file), which takes it automatically — and that stream
  fills the big left stage while everyone else ladders down the right,
  with the person currently speaking highlighted and enlarged at the
  top of the ladder. Click a ladder tile to swap it into the stage;
  click the stage to go back to the collage. When the shared content
  ends, the collage returns.
- **A green ring means audio is arriving** on that stream, in both
  layouts — fed by the same per-tile meters, so it is decode-truth,
  not a guess. The speaker pick is the loudest recently-active stream,
  held ~1.5 s so the ladder does not flap.

## v0.6.9

The last polish pass before v0.7 access control — and the legacy
publish page is gone for good.

- **Switch rooms from the room chip.** The “Room: …” chip in the bar
  opens a menu of every live room (padlock on the locked ones; the
  password is asked right there). Switching while publishing
  republishes your sources under the new room — devices never blink,
  and viewers in the old room lose you, which is what leaving means.
- **The self-view mute now actually turns red** when muted — a CSS
  specificity bug had been eating the state the video button showed
  fine — and the device chevrons sit flush at the same height as
  their buttons.
- **Quieter chrome**: no red ring on your live pane and no red fill on
  the Share button (being on the page IS being live); the Share dot
  now lights only when you share something beyond your camera (screen,
  RTSP, file). The “Go Live” heading, the Grid-era audio-mode and
  warm-audio buttons, and the People panel’s watch/park controls all
  left the UI (the machinery stays; audio is “all”, warm on, streams
  auto-watch). The People panel section is titled People.
- **Popovers collapse when you click anywhere** — including clicks that
  land in another frame (the page area under a masthead popover, the
  masthead over a page popover): focus loss now closes them all.
- **The People button** renders icon and label on one line, inside its
  border.
- **publish-camera.html is removed** — from the site and from the
  bundle. The Share panel on Go Live has been the whole publish surface
  since 0.6.6; the fallback earned its retirement. (Old builds in
  dist/archive still carry it if ever needed.)

## v0.6.8

A polish pass over the meeting, from a day of using it.

- **The join card acts like Teams now**: a live camera self-preview with
  round mic and camera toggles (both OFF by default — they map straight
  to how you join), a free-form name (the first-name + last-initial
  format is no longer forced), and one Join button. A machine without a
  usable camera joins as a viewer automatically — the separate
  “screen instead” / “without a device” buttons are gone (screen
  sharing lives in the Share panel, any time after joining).
- **Channels are called rooms** everywhere you can see. A room’s
  password is asked for only when the room actually has one, the room
  name field appears only when creating a new room, and an empty room
  is deleted — gone from the picker until someone creates it again.
- **Muted and paused are loud red** on your self-view controls, and the
  device chevrons fused onto their mute/pause buttons — one control.
- **Names, not model numbers**: your preview pane wears just your name
  (no path, no status line); streams label as person + device type
  (“Kenton — Camera”), and the stream rows’ mute uses the same mic
  glyph as the self-view. A paused stream shows the person’s initials
  over the ASI swoosh instead of a “video paused” string.
- **Click a tile to focus it; click again for the grid.** The Grid
  button and the sort dropdown are retired (drag still reorders).
- **Sources preview the moment they are added** — no separate Start
  click (Start remains as the retry for a failed source).
- **The relay moved into the top-right badge**: its popover now changes
  the relay (server-wide, plus every open page follows live) as well as
  showing stats. The toolbar Relay button is gone.
- **Pick your speakers**: the Audio panel gains an output-device
  selector (remembered on this machine), and every microphone picker
  names what “System default” currently is.

## v0.6.7

Meetings. The page is now **Go Live**, and it behaves like one: you join
a channel, you are present in it, you leave it.

- **Join before you watch.** A Teams-style gate collects your name,
  camera and microphone, and the channel; nothing connects until you
  join. Joining with a camera puts you on air **muted, with video
  paused** — deliberate states you flip from the bar's self-view
  controls, so nobody joins hot. “Share a screen instead” and “join
  without a device” are the honest escape hatches (a no-device joiner
  is invisible to others — the roster is the streams).
- **Channels.** Broadcasts live under a channel (room) on the relay;
  discovery only sees the channel you joined. The picker lists live
  channels (plus any you created) and “main” always exists. A channel
  you create can take a password — **advisory in this release**: it
  gates the join screen (salted hash on the relay), not the relay
  itself; real enforcement arrives with v0.7's tokens. Channel changes
  are leave-and-rejoin, never a silent re-aim of a live broadcast.
  The old publish page (and any pre-0.6.7 build) publishes without a
  channel and is therefore invisible to Go Live pages — accepted for
  the legacy fallback's last release.
- **A meeting layout.** Top bar (your streams with live previews, mic/
  camera controls, channel chip, red **Leave**), full-height stage, and
  a **People** panel on the right holding the stream list, stats and
  diagnostics. Leave stops publishing outright — camera released,
  light off — and returns you to the gate.
- **Streams in your channel start watched** (park still remembered per
  stream — an explicit park survives reconnects and reloads), and
  **audio defaults to all streams**: a meeting is heard.
- **The relay badge tells the truth**: green connected, yellow
  connecting, red once the relay has been unreachable for 15 s — and
  it recovers by itself (a stuck connection is rebuilt on observed
  death, never on idleness). The app shell's Go Live tab shows the
  same truth in its dot, and its ✕ became a plug: disconnect when
  open, connect when closed.

## v0.6.6

The Live Streams merge: the Watch page absorbs the publish machinery and
becomes the app's one page.

- **One page for everything.** The publish core — devices, sources,
  encoder settings, RTSP/file/screen, the operator gate, Go live — now
  runs natively inside the (renamed) Live Streams page. The Share panel
  hosts the real controls instead of an embedded copy of the publish
  page. Deliberately a second module script: a failure in the ported
  core degrades the page to watch-only rather than killing it.
- **Full-framerate self-view.** “My streams” shows your local sources as
  live preview panes — the slot’s own canvas, same document, no relay,
  no webp — replacing the publish page’s preview stage outright.
  Previews are simply always on now (the self-view IS the preview); the
  leased thumbnail path remains for other windows on this profile.
- **Live Streams is the default page** the app opens on, and the
  masthead / home page rename with it. The relay field in the Relay
  popover is now the one relay truth for watching AND publishing.
- **The old Publish page stays for one release** as a fallback —
  reachable from the Share panel header and the home page (opens in its
  own window), fully interoperable over the sources channel, byte-frozen
  except for one link label. It goes away once the merge has proven
  itself in the field.
- **Enable devices can no longer look dead.** Field report: the button
  did nothing until an app restart (a wedged permission prompt). It now
  shows “Requesting…” while the prompt is pending and logs a hint if
  the browser hasn’t answered after 10 s.

## v0.6.5

The big Teams-style pass: real icons, a cleaner Watch page, your own
streams in their own pane with live previews and device menus.

- **Real icons, at last.** The first pictograms in KASTR: microphone,
  camera and speaker glyphs with slashed off-states — red for a muted
  mic, amber for paused video (deliberate, not a fault). The mic icon
  carries a Teams-style level fill; today it shows state (a live level
  for your own mic needs a publish-side meter, planned).
- **The Watch toolbar folds away.** The intro text became a Help (?)
  popover with the full key and gesture list; Relay URL + Connect became
  one Relay button (with a note that connecting rebuilds every tile);
  the volume/mute/mode/warm cluster became one Audio button that turns
  red when everything is muted. Opening any panel closes the others.
- **Your own streams leave the grid.** Watching yourself through the
  relay paid twice for a picture you already have. Own broadcasts now
  live only in “My streams” — with small LIVE previews painted by the
  publishing view itself and passed across locally (never through the
  relay), leased only while the pane is visible so idle cost is zero.
  Two honest notes: your own machine no longer reports starvation on
  your own streams (another machine's watcher still does), and a
  same-named broadcast from another machine would be hidden too —
  name collisions were already unsupported.
- **Switch devices from Watch.** Camera rows in My streams grow menus:
  pick which camera feeds that stream (the broadcast keeps its original
  name — renaming live would drop viewers) and which microphone the
  machine uses (persists exactly like the Publish picker).
- **A proper standby face.** Paused or audio-only tiles show the ASI
  swoosh breathing on a navy pool instead of a black rectangle — and it
  respects reduced-motion settings.
- **Publish reorganised around devices.** The camera picker (and Add all
  cameras) moved into Devices above the microphone; the mic now follows
  the cameras — adding a camera while nothing carries the mic attaches
  it, removing the carrier moves it to the next camera with a note.
  Previews are on by default (reversed from 0.5.2 at the requester's
  direction; the Share panel forces them off — its stage is hidden).
  The encoder settings panel folds shut; Auto remains the recommendation.

## v0.6.4

The header tells the truth about the relay, and Watch gets a Teams-style
self-view.

- **The relay badge follows a repoint.** The number in the top right was a
  snapshot taken when the window opened — the server substitutes the relay
  into pages as it serves them, the app shell's own document is served
  once per launch, and “Point KASTR at this relay” changed a value nobody
  was ever told about. Now `/api/instance` carries the live value, the
  badge polls it and updates within ~5 seconds, the stats popover
  re-targets the new relay, and the Relay page's “Currently used” field
  reads the server instead of scraping the badge (it used to show “—”
  forever inside the app). Deliberately unchanged: each page's own Relay
  URL field and any running connections keep their relay until reload,
  and a restart returns to the launch configuration.
- **“My streams” on Watch.** A pane above the stream list shows everything
  this machine's views are publishing — fed by their announcements, so
  even streams you have parked appear — with a live/preview dot and
  per-source mute-mic and pause-video buttons that act on the owning
  view, addressed the same way the existing remote “stop” is. Muting is
  now durable for the session: the effective mute used to be recomputed
  from the mic-target selector on every start and on every retarget, so
  a mute set anywhere else silently reverted. State changes announce
  immediately (the 4-second liveness tick alone was too slow for a
  control surface). RTSP rows show name and state only — that path is
  video-only by design.

## v0.6.3

Audio without video, tiles you can size by hand, and tiles you can grab
anywhere.

- **Pause video, keep the audio.** Every camera, screen and file source row
  now has a `video: on / paused` toggle. It drives the library's own
  “invisible” control: the video encoder stops for every source kind, a
  paused camera is released outright (light off), and the mic — or the
  file's / tab's own audio — keeps publishing. The broadcast stays
  announced and viewers keep the sound without a reconnect; audio
  continues only if the source carries audio (a paused camera that isn't
  the mic target announces an empty catalog). The state survives
  Stop/Start within the session. RTSP rows have no toggle — that path is
  video-only by design.
- **Audio-only streams look deliberate on Watch.** They used to render as a
  black rectangle with a permanent amber “picture: no / recovering” in
  Stats — and posted a false “viewers report receiving nothing” warning to
  the publisher every 30 seconds, because the starvation check counted
  video bytes that legitimately never come. Now: a big level meter with
  “♪ audio only” (or “video paused” when there is no audio either),
  Stats say `video: none (audio only)`, the video pipeline is not enabled
  at all, and the starvation report only fires for broadcasts that
  advertise video. (A broadcast whose catalog never arrives at all — the
  relay fault the report exists for — is still reported.)
- **Size Watch tiles by hand.** Drag the corner grip of any tile: the grid
  is now fine cells and the other tiles flow around whatever size you
  choose (the default tile matches the old size). Sizes are remembered on
  this device; narrowing the window clamps a too-wide tile and widening
  restores it. Exact manual order is approximate around oversized tiles —
  the packing fills gaps by design. Resizing (and now plain window
  resizes, which never did) re-picks the video rendition for the new
  size, and the picker no longer wipes the library's own size and
  bandwidth hints when it pins a rendition by name.
- **Drag tiles from anywhere.** The whole tile is the reorder handle, not
  just the name bar — buttons and the resize grip excepted. Plain clicks
  still select (the drag threshold went from 5 to 6 px, since a big
  surface invites wobblier clicks).

## v0.6.2

RTSP feeds that heal themselves, a Watch page that only downloads what you
ask for, and a mic picker that tells the truth.

- **RTSP feeds no longer freeze after running a while.** The bridge's endless
  stream was never steered toward the live edge: every hiccup left the
  picture a little further behind real time, and once the browser's demuxer
  filled up it stopped reading the connection entirely — wedging ffmpeg in a
  write forever, with every counter still reading “healthy” (`frames=` counts
  encoder output, which keeps climbing while the backlog plays out; nothing
  after a slot wires could ever report a fault). Fixes, all driven by
  observed facts — no silence timers came back (the 0.5.28 rule):
  the picture is held near live by chasing at 2× when it falls more than
  ~3 s behind (measured as wall-clock vs media-clock drift — the stream is
  unseekable, so seeking is never attempted); a feed more than 20 s behind
  reconnects instead (≈2 s back to live); a playhead frozen for 10 s while
  playing restarts the feed; a media error after wiring — previously
  invisible — restarts it; keyframes stopping while frames flow (a
  timestamp fault that blanks new viewers) restarts it; and the bridge now
  times out a reader that stops consuming (15 s), so an abandoned
  connection can no longer wedge ffmpeg — the feed list stops claiming a
  dead feed is running. Stale ffmpeg errors no longer bleed into the next
  attempt's report.
- **Watch subscribes per stream.** Every announced stream is listed, but
  nothing connects until you switch it on — each tile costs its own QUIC
  connection plus catalog even when hidden, so parked streams now cost
  exactly nothing. Click a row (or its ○ toggle) to start one; ● parks it
  again; watch all / park all in the list header. Your choices are
  remembered on this device, a stream that goes away and comes back returns
  subscribed, and arrows / number keys never subscribe on their own.
  (A parked tile keeps its place in the list but can't be drag-reordered
  until it's watching again — its pane isn't on the stage to drag.)
- **The mic picker names the real default.** Chrome's device list carries
  “Default — X” and “Communications — X” pseudo-entries that duplicate real
  microphones — and picking “Default” was a silent no-op (the library strips
  that id from the list it honours). The picker now shows
  “System default — your actual default mic” plus the real devices only,
  auto-selects the default until you choose, remembers what you choose,
  follows plug/unplug live, and says — once — when your saved mic is
  missing and it has fallen back to the default.

## v0.6.1

Audio you can actually control, names on every stream, and a grid you can
arrange.

- **Mute finally mutes -- and stays muted.** Two earlier attempts were built
  on the belief that the library had no volume control. It does: `volume`
  drives a real gain with a smooth ramp, and values just above zero silence
  the sound *without* dropping the stream. Worse, our old workaround -- a
  gain spliced into the audio graph -- ended up wired **in parallel** with
  the library's own path whenever the volume was written, so the sound
  played on at full loudness no matter what the controls said. The splice is
  deleted; every level and mute is now a plain volume write, re-asserted
  once a second so nothing can drift back. Master mute, per-stream mute,
  per-stream levels and the master slider all do exactly what they say.
- **Live level meters.** Every stream row and tile shows a thin meter that
  moves with the sound actually being decoded -- green when you can hear it,
  grey when it is silenced. Streams that carry no audio at all (RTSP
  cameras, by design) show a crossed-out note instead of controls that
  could never do anything. The meters pause while the window is hidden, so
  they cost nothing in the background.
- **Pick your microphone.** The Devices panel now has a microphone selector.
  The choice is remembered on this machine (never travels with the exe),
  applies to every source that carries a mic, and falls back to the system
  default if the remembered mic is unplugged. Switching while live re-opens
  the mic -- a brief blip on that stream's audio.
- **Streams now say who is publishing them.** Going live requires your name
  -- first name and last initial, like "Kenton J" -- asked once and
  remembered. It becomes part of the broadcast name
  (`machine/kenton-j/camera.hang`), and the Watch page shows it as
  "Kenton J -- camera" on every row and tile. Streams from older builds
  keep their old labels. The Share panel asks for (and shares) the same
  name.
- **Arrange the Watch grid your way.** Drag any tile by its name bar to
  reorder -- the list, the row numbers, the digit keys and the arrow keys
  all follow, and the arrangement is remembered on this machine. An Order
  control offers name, person and newest-first sorts; dragging switches
  back to manual with whatever you were looking at as the starting point.
  Reordering never interrupts playback.

## v0.6.0

RTSP cameras now stream at their real frame rate. This closes out the work of
making RTSP ingest genuinely usable, which is why it gets a minor version.

- **Full frame rate for RTSP sources.** The published stream sat at one frame a
  second while the camera delivered 15-30. Bisected with everything else held
  constant -- same page, same encoder, same resolution, hidden and visible, fixed
  and variable timing -- and the culprit was the *audio track* in the bridge's
  output: with the camera's audio muxed in, the browser captures the video at
  ~1 fps; strip the audio and the identical stream captures at the full rate.
  Resampling it did not help, so the track itself is what throttles capture.
  The bridge now delivers video only, and the camera went from 1 to a measured
  **30 fps end to end**, ~4 Mbit/s at 1080p.
- Nothing is lost by dropping that audio: the RTSP publish path has only ever
  built a video broadcast -- the audio track was decoded and then discarded, so
  its only observable effect was breaking the video. Publishing camera audio
  would be a new feature (a separate audio pipeline), not a regression fix.
- The disappearing video-file broadcast reported against v0.5.27 does not
  reproduce on v0.5.28 -- verified running a looping file beside the camera for
  a minute with a live viewer. Consistent with the cause being the restart and
  rename machinery removed in v0.5.28.

## v0.5.28

- **The watchdogs that guessed are gone.** With the software-encoder fallback
  in place the video works, and what was left misbehaving was this machinery
  itself:
  the "broadcast stopped producing" watchdog restarted a healthy stream every
  time its viewers left (encoding is on demand, so frames stopping when nobody
  watches is correct, not death); the relay-name checking renamed sources to
  `-2` on every relaunch, because the previous session's own announcement
  lingers on the relay for a while and cannot be told apart from a rival; and
  the fifteen-second "went quiet" timer was a guess with false alarms.
  All of it is removed. A stream now restarts only on unambiguous signals: the
  camera feed actually ending, or the capture track actually dying. Names are
  only de-duplicated against this app's own sources, never against the relay,
  and nothing renames automatically.
- Verified: a live broadcast left without viewers for over half a minute keeps
  its name and stays on air, and a returning viewer gets the picture back.

## v0.5.27

- **When the hardware video encoder fails, KASTR now switches itself to
  software encoding.** The failure your console has been showing all along --
  `publish error: track=video error=Encoding error` -- is the browser's hardware
  encoder accepting a configuration and then dying on the first real frame. It
  is browser-specific: the same machine encodes fine in one browser and fails in
  another, which is why it never reproduced outside the app. When it happens,
  every viewer gets a reset stream and a black picture while the publisher
  merely looks idle. On the first such failure the app now steers the encoder
  choice to software, restarts the affected sources, says so plainly, and
  remembers the choice for this machine.
- **The name-rotation from v0.5.26 is gone.** It was built on the theory that a
  relay path had gone bad; renamed broadcasts failing identically disproved
  that, and the rotation just produced a parade of dead streams. A viewer
  receiving nothing now produces a status message, not a rename.
- The diagnostics snapshot now includes the encoder configuration actually in
  use (codec, hardware or software), recent library errors, and whether the
  software fallback is active.

## v0.5.26

- **A broadcast whose path has gone dead on the relay now moves itself to a
  fresh name.** A relay can reach a state where one path silently absorbs every
  subscription: watchers get a reset stream and a black picture, and the
  publisher just looks like nobody is watching -- which is also what "nobody is
  watching" looks like, so the publisher alone can never tell. Verified live
  with two independent watchers subscribed to one such path and the publisher's
  encoder never asked for a single frame. And because the stale claim does not
  announce itself, the name-clash guard cannot see it either.
  The one party that can tell is a watcher: subscribed, catalog in hand, and
  nothing arriving. So the Watch page now reports a stream that has delivered
  zero bytes for 25 seconds, and a publisher in the same app that owns the name
  and whose encoder is genuinely idle re-announces under the next suffix --
  the same mechanics as editing the name by hand, so nothing is torn down.
  Renames are throttled, capped at five, and end in a plain message telling you
  to restart the relay if even fresh names deliver nothing.
- This only heals publishers running in this app. A viewer cannot fix a
  publisher on another machine; restarting the relay clears such paths for
  everyone.

## v0.5.25

- **Home page reordered to match the top bar** -- Publish, Watch, Relay server --
  and the "recommended" tags removed.
- **Stops forcing an encoder configuration the browser cannot honour.** v0.5.12
  started pinning RTSP sources to H.264 at 1080p. From that the library computes
  an encode size of 1904x1072, while the frames a camera actually delivers are
  1920x1088 -- and the encoder then fails with "Encoding error", closes itself,
  and every viewer receives a reset stream and a black picture. Left alone, the
  library picks a size that matches the source exactly and it works. Both
  encoder settings are back to Auto; choosing them by hand still works, and is
  now clearly the exception rather than the default.
  Note this is only safe because the bridge now scales oversized cameras down
  before the browser sees them (v0.5.12's other half): Auto was previously
  choosing VP9 at full 4K, which no browser can encode in real time.

## v0.5.24

- **Converts full-range camera video, which the browser's encoder refuses.** The
  app's console gave this away at last:

      publish error: track=video error=Encoding error.
      subscribe error: remote error: 0  (WebTransportError: Received RESET_STREAM)

  The browser rejects the frames, the library rebuilds the encoder, one keyframe
  comes out, and it fails again -- which is why the publisher looked like it was
  managing exactly one frame a second with half of them keyframes, a figure that
  made no sense as a performance measurement. Viewers get a reset stream and a
  black picture, and nothing anywhere reports a fault.
  The cause is colour range. This camera sends FULL-range video (`yuvj420p(pc)`),
  where the built-in test pattern that has always worked is limited-range
  (`yuv420p(tv)`). That is the only property separating the source that works
  from the one that does not. Note that `format=yuv420p`, which the bridge was
  already applying, does NOT convert the range -- it only renames the format,
  which is why an earlier attempt at normalising this achieved nothing. The
  conversion is now explicit, and a full-range source is never passed through
  untouched however convenient copying it would be.

## v0.5.23

- **Fixes a source renaming itself over and over.** A name that clashed was
  renamed by appending `-2`, but the check then ran again on the new name and
  appended another, producing broadcasts called
  `camera-2-2-2-2-2-2-2-2-2-2-2.hang`. Seen live while testing something else.
  The suffix is now replaced rather than stacked, and the check runs once after
  a burst of relay announcements instead of once per announcement.

## v0.5.22

- **Fixes a publisher that keeps capturing but sends nothing.** A camera is
  published by capturing one track from the video element, and the encoder is
  built around that one track. If it ends -- which happens without the video
  element reporting anything -- the encoder is starved: it stays live, keeps
  announcing, and every viewer sees the stream listed and black. The reconnect
  added in v0.5.18 could not see it, because it watches the video element and the
  element was fine. KASTR now watches the track the encoder is actually using,
  and rebuilds when it dies.
- The Publish diagnostics were hiding this. They reported the capture rate by
  asking the video element for a *new* stream each time, which always answers
  30fps -- so a starved encoder looked perfectly healthy. They now report the
  state of the encoder's own track, plus whether its relay connection is
  established.

## v0.5.21

- **Fixes the black picture for good, and it was a name clash all along.** When
  two publishers claim one broadcast name, the newer one wins and the older is
  starved in silence: the relay sends it no subscriptions, so it encodes nothing,
  and every viewer sees the stream listed with a black picture. Nothing reports an
  error at any layer. Worse, being displaced is permanent -- the loser never
  recovers, even after the other publisher goes away.
  The guard added in v0.5.17 asked the relay which names were taken, but that
  answer can take fifteen seconds to arrive, so a source added just after launch
  was named against an empty list and the guard never fired. Now: a source named
  before the relay has answered is re-checked and renamed once it does, and a
  broadcast that is live, capturing happily, has encoded nothing at all, and whose
  name the relay says belongs to someone else, renames itself and republishes
  rather than staying invisible.
- The go-live check no longer counts your own broadcast as a conflict, which
  would have refused to put a stream back on air after stopping it.

## v0.5.20

- **Fixes the window opening small again.** v0.5.18 removed the fixed window
  size on the assumption the browser would restore an app window's position and
  size by itself. It does not, so every launch came up at some default -- worse
  than the fixed size it replaced. KASTR now records where the window is and
  hands it back on the next launch, maximized state included, falling back to
  maximized on a first run or if the saved position no longer fits any monitor.
- **The app can now report what it is doing.** Each page posts a snapshot of its
  own state -- what is publishing, what a viewer is receiving, what the encoder
  has produced -- to its own server, which keeps the latest one. Entirely local:
  the same loopback server that serves the page, nothing written to disk and
  nothing leaving the machine. It exists because several rounds of chasing a
  black picture were spent inferring what a page was doing from the outside,
  when the page already knew.

## v0.5.19

- **A broadcast that dies while its camera is fine now rebuilds itself.** Seen
  side by side on one relay: a broadcast that had been up ten minutes delivered
  nothing to anybody -- black in every viewer, zero bytes -- while a freshly
  published broadcast of the same camera through the same relay played normally.
  The camera was healthy throughout, so the reconnect added in v0.5.18 never
  fired: that watches the camera, and the camera was not what broke. KASTR now
  also watches what the encoder produces, and rebuilds the broadcast if it goes
  quiet for twenty seconds while the camera is still delivering.

## v0.5.18

- **A camera that drops its connection now reconnects.** UniFi cameras
  invalidate their RTSPS session after a while -- ffmpeg reports "the specified
  session has been invalidated" and exits. The video feed then ended *cleanly*,
  and only a hard error was being watched for, so nothing recovered: the source
  still looked present and every viewer went black. The feed ending, or simply
  going quiet for fifteen seconds, now rebuilds the connection, backing off if
  the camera is genuinely gone, and says what it is doing rather than leaving a
  silent gap.
- Reconnecting no longer re-interrogates the camera about its codec, which was
  three seconds of extra dead air each time.
- **The window opens maximized the first time and remembers where you put it
  after that.** Every launch had been pinned to the same size, which overrode
  the position and size the app had remembered, so moving or resizing it never
  stuck.
- **Publishing keeps running while the window is behind something.** Browsers
  throttle a window that is not in front to roughly one frame a second, and
  publishing a camera or file depends on the page being drawn -- measured 30 fps
  in front against 0.24 fps behind. For a tool meant to keep streaming while you
  work in another window, that was the wrong default.

## v0.5.17

- **Fixes the real cause of a stream that lists but plays black.** Two
  publishers can end up on the same broadcast name -- names are built from the
  machine name and the source, so two copies of the app, two people publishing
  the same camera, or one forgotten instance all land on the same one. Nothing
  reports an error: the relay keeps announcing the catalog while delivering no
  media, so a viewer lists the stream, subscribes, and gets a black picture and
  zero bytes. Observed exactly that, then watched it start playing the instant
  the duplicate was renamed away.
  Names were only ever checked against this browser -- its own sources, and the
  Publish page and Share panel comparing notes -- which cannot see a publisher
  in another process or on another machine. KASTR now watches what the relay has
  already announced and treats those names as taken, so adding a source that
  somebody else is already publishing quietly becomes `-2` instead of breaking
  both. If a name is claimed in the gap between adding a source and going live,
  it now says so instead of publishing into a silent conflict.

## v0.5.16

- The Publish page's diagnostics now report the encoder's own output -- frames,
  keyframes, bytes, whether it is running at all, and the rate frames are being
  captured at. Until now a slow or absent stream could only be inferred from
  what a viewer received, which cannot tell "nothing was encoded" apart from
  "nothing arrived". Worth knowing: the encoder deliberately does nothing until
  somebody is watching, because Media over QUIC only produces what is asked for.

## v0.5.15

- **Publishing no longer freezes when you switch tabs.** An RTSP or file source
  is published by capturing a video element, and a browser only produces frames
  from one while it is actually being drawn -- measured on a 1080p camera, 30 fps
  with the page in front and 0.24 fps behind. Switching to Watch to look at what
  you were publishing therefore froze it, which is the one thing anybody would
  do. Inactive tabs are now kept drawn but parked behind the active one instead
  of being taken off screen. Camera and screen sources were never affected: their
  frames come from the capture device, not from anything being drawn.
- **The Watch stats no longer claim frames are decoding when they might not be.**
  The counter labelled "frames decoded" is incremented as each chunk comes off
  the network, before the decoder ever sees it, so it climbs happily while
  nothing decodes -- and the panel then concluded "a blank picture must be a
  rendering problem", which is the opposite of the truth. It now reports "chunks
  received" for what that number is, adds a "picture" row that says whether the
  decoder is actually holding a frame, and says so plainly when chunks arrive
  but no picture does.

## v0.5.14

- **Launching KASTR now runs the copy you launched.** If something was already
  serving on its port, the app assumed it was another copy of itself and simply
  showed that window -- it decided this from a bare heartbeat reply, which any
  version answers identically. So a copy running from a source checkout could
  capture the launch of the real program, and the app reported a `-dev` version
  even though a released build had been started. The check now asks which build
  is there: the same one still gets the window (a second server on one browser
  profile could never open one anyway), and anything else is left alone while
  this build starts on a free port.
- Checking for a running copy no longer counts as a sign of life from it. The
  old check posted to the page heartbeat, so merely looking kept a windowless
  instance alive.

## v0.5.13

- **Fixes a stream showing as present but playing black.** The bandwidth saving
  added in v0.5.2 stops a stream downloading while its tile is scrolled out of
  view -- and it was applying that to the stream you had actually selected. On
  the Watch page the video sits below the fold in a short window, so arriving
  there gave a listed stream, a black pane, and a subscription that was never
  switched on at all. The selected stream is now always downloaded, wherever it
  is on the page. Other tiles in grid view still load lazily, but with a much
  larger margin so scrolling reaches a picture instead of a black square.
- RTSP history keeps the last 15 urls, and the field is labelled "Recently
  used" rather than counting what is in it.

## v0.5.12

- **An RTSP camera now actually plays on the Watch page.** It previewed on
  Publish and arrived as nothing on Watch: the catalog was there, a track and
  config were chosen, no error, and zero bytes. The cause was that an RTSP source
  built its encoder and never applied the encoder settings to it -- so it always
  ran on the library's defaults, which for a 4K camera means VP9 at 3840x2160,
  something no browser can encode in real time. Settings are now applied when the
  encoder is created, and the defaults are H.264 at 1080p rather than "let the
  library decide".
- **Oversized cameras are scaled down before the browser sees them.** A 4K frame
  copied straight through reached the browser fine but left it scaling 8.3
  megapixels per frame, which measured 1.0 fps against 18.3 fps for a 720p
  source. The bridge now does that scaling instead, on the GPU where there is
  one -- measured 25 fps at 1080p from the same 4K camera. Sources already within
  1920 wide are still passed through untouched, at no quality cost.
- **RTSP URLs are remembered.** Recently used ones appear in a list next to the
  field and as type-ahead suggestions, so a long camera URL only has to be
  entered once. There is a Forget button, because these often contain passwords.
- Those URLs are stored **only on the machine that used them**, in this app's own
  browser profile. They are not part of the program: copying KASTR to another
  computer does not carry them across, and nothing is written next to the
  executable.

## v0.5.11

- **RTSPS cameras work.** A `rtsps://` URL sat at "ready" and never went to air.
  ffmpeg's actual complaint was `Peer certificate failed verification` -- cameras
  like UniFi Protect present a self-signed certificate on their RTSPS port, and
  nothing could validate an IP address on a local network anyway. Verification is
  now off for RTSPS: the stream is still encrypted in transit, the camera just
  is not authenticated.
- **Camera video is no longer re-encoded when it does not need to be.** The
  bridge always re-encoded, which on a 4K camera ran at **0.30x real time** -- it
  could never keep up with a live feed at any resolution. Cameras already send
  H.264, so it is now repackaged instead: **1.15x real time** and a seventh of the
  data. A short probe on first connect checks the camera's codec, so anything
  that is not H.264 is still re-encoded as before.
- Cameras with several audio tracks, or none at all, no longer break the bridge.
- **The ON AIR badge no longer blinks to "off" every few seconds.** Rebuilding the
  source list reset each badge to a placeholder that only a later refresh filled
  in, and sharing between views triggered a rebuild every four seconds. The list
  is now only rebuilt when something actually changed, and never left showing a
  placeholder.
- **Sources shared from another view now appear in the right-hand pane**, not just
  in the source list. The tile cannot show the picture -- the video is being
  encoded in the other view and a stream cannot be decoded twice -- so it says
  where it is running instead.
- **"Audio: follows selection" is now a three-way switch**: follows selection,
  all streams, then manual. Hearing everything at once no longer means clicking
  the speaker on every row, and per-stream mute and levels still apply.

## v0.5.10

- **Mute and the volume sliders actually work now.** They have not since v0.5.4,
  and that was my doing. The streaming library turns out to have no volume
  control at all -- its audio pipeline takes a single on/off flag, and what looks
  like a volume setting only feeds that flag: zero means off, any other value
  means on at full loudness, with nothing in between. v0.5.4 stopped writing zero
  (to avoid tearing the audio connection down on every switch), which meant
  nothing was ever quiet again. KASTR now does its own mixing, so levels are real
  levels and a mute is silent while the stream stays connected -- so switching
  still does not drop sound. Where the audio pipeline cannot be reached, mute
  falls back to switching the stream off outright: being genuinely silent matters
  more than staying warm.
- The stats panel now reports which of those two it is using, and can finally
  read the audio state it used to say it "could not read".
- **The Autonomous Solutions logo is the way home**, and the Home button has been
  removed from the top bar since it did the same thing.

## v0.5.9

- **Anything shared from Watch now shows up on the Publish page too**, and the
  other way round. The Share dropdown and the Publish page are two live views of
  the same page, and each only knew about its own sources, so a camera started
  from Watch was invisible on Publish. Each view now announces what it is
  publishing and lists the others' sources alongside its own, marked with where
  they came from. The view that started a source still owns it -- stopping one
  from the other side asks its owner to do it, because only the view that opened
  a capture can close it cleanly.
- **Two views can no longer pick the same broadcast name.** Names were only
  deduplicated within a view, so Watch and Publish could both publish as
  `<machine>/camera.hang` and fight over it on the relay.
- **The Autonomous Solutions logo no longer leaves the app.** It was an ordinary
  link to the home page, so clicking it dropped out of the app shell and loaded
  the home page bare -- no tabs, and everything that was running torn down,
  which read as a different, older app. It now just brings the Home tab forward.
- **Home-page cards switch tabs instead of loading inside the Home tab**, which
  used to nest a second navigation bar inside the app and run the page twice.
- **The home page is no longer served from a stale cache.** A request for `/`
  skipped the no-caching header that every other page gets, so the browser held
  on to an old copy of it -- including across an upgrade. Tab pages are also
  stamped with the build now, so a new version never shows the old one's pages.

## v0.5.8

- **Fixes the version shown in the app being one behind.** v0.5.7 reported
  itself as v0.5.6 in the header and in these notes. When `VERSION` changed to
  mean "the build that shipped", the build kept bundling that file as-is -- and
  it is not updated until after the build succeeds, so each app was stamped with
  the previous number. The version is now generated from the build itself, so it
  cannot drift again.

## v0.5.7

- **Fixes v0.5.6 failing to start.** The new watchdog that stops a half of the
  app outliving the other half used `os.kill(pid, 0)` to ask "is the other half
  still alive?". That is the standard way to ask on Mac and Linux, but on
  Windows it does not ask anything -- it terminates the process. So the
  watchdog killed the very thing it was watching, a second after launch. It now
  waits on a proper process handle instead.

## v0.5.6

- **Fixes a crash on exit in v0.5.5.** Closing the app showed "Unhandled
  exception in script ... AttributeError: 'NoneType' object has no attribute
  'flush'". The Windows app is built as a windowed program and so has no
  console at all -- `sys.stdout` and `sys.stderr` are nothing, not files -- and
  the new shutdown path tried to flush them. Worse, it did that between the
  cleanup and the exit, so the error skipped the exit entirely: the one
  function whose job is to always end the process was the one thing that could
  stop it happening. Shutdown now ends the process from a `finally`, so nothing
  going wrong inside it can prevent the exit, and every write to a console that
  may not exist is guarded.

## v0.5.5

- **Relay stats is no longer a card on the home page.** The relay badge in the
  top right opens the same view from any page, and did it better -- the card
  opened a detached browser tab instead.
- **Closing the window now ends KASTR completely.** It used to be able to keep
  serving in the background, holding its port and its ffmpeg and relay
  processes -- which twice blocked a rebuild of its own .exe. Three causes: the
  "could not open its window" notice was a modal dialog that blocked forever
  behind other windows; shutdown ran on only one of the five ways out of the
  launcher, so quitting any other way left every child running; and nothing
  handled Ctrl+C or a shutdown request. There is now a single teardown that
  every exit goes through -- ffmpeg first, then the relay, then the server --
  each step time-limited, with a watchdog so shutdown itself cannot hang.
  Measured: window closed to fully exited in about a second.
- Shutdown also notices the browser's own profile lock disappearing, so a
  window opened by a second copy of Chrome no longer waits out a 2.5 minute
  timer before the server stops.
- **`VERSION` now names the build that shipped, not the next one.** It reads
  the same number as `BUILT_VERSION` and as the app itself, instead of sitting
  one ahead and looking like a mismatch. Building the second platform of a
  release takes `--keep-version`, which now does what its name suggests.
- **The release archive is written last.** It used to be zipped before code
  signing and before the macOS bundle got its camera and microphone usage
  strings, so the zip -- the copy that actually gets handed to people -- held
  an unsigned executable and a bundle that would have failed to capture,
  while the copy left in `dist/` was fine.
- **The archive only packs what it can vouch for.** A platform folder joins a
  release only if its `BUILT_VERSION` matches and its binary is actually
  there; anything else is named and skipped rather than shipped under a
  version it was not built for. The build prints what went in, per platform.
- **A release archive can grow but not silently shrink.** Rebuilding one
  platform can no longer replace a two-platform release with a one-platform
  one; that now stops the build and says what would have been lost
  (`--allow-shrink` if you mean it).
- Executable bits in the zip no longer depend on which machine zipped it, a
  failed archive no longer leaves a part-written file behind, and a build can
  no longer report success while quietly failing to record its own version.

## v0.5.4

- **Audio controls work again.** The master mute and the per-stream volume
  sliders were both being silently overridden. `@moq/watch` treats a volume of
  exactly 0 as a mute: it forces the element muted and tears down the audio
  subscription, and it then discards the next volume set and substitutes 0.5 of
  its own. Every value is now floored at -80 dB instead of 0 -- inaudible, but
  low enough that nothing is reinterpreted, so a mute stays a mute, a level
  stays where you put it, and the subscription stays warm so switching does not
  drop sound.
- **A mute button on every stream**, next to its level, so one noisy feed can be
  silenced without giving up its place or touching anything else. Sliding a
  muted stream back up unmutes it.
- **Publish is back on the top bar.**
- **Studio is gone.** It was Publish and Watch side by side, which is what the
  Watch page's Share panel now does in one window.
- **Share closes when you click away from it**, rather than only on the X.
  Whatever you put on air keeps running either way.
- **All publish settings** switches to the Publish tab instead of opening a
  second window, so nothing else you have running is disturbed.
- **Linux carries ffmpeg again.** RTSP ingest works on a Linux machine with
  nothing installed on it, the same as Windows. v0.5.3 shipped without it and
  fell back to whatever `ffmpeg` was on PATH.
- The bundled Linux ffmpeg is a static x86_64 GPL build from BtbN, the Linux
  provider ffmpeg.org links to; the GPL variant is required because RTSP ingest
  encodes with libx264. `fetch-helpers.py` pins one dated build and checks its
  SHA-256 before unpacking, so every machine that builds KASTR gets a
  byte-identical binary.
- Builds now archive themselves: one zip per release in `dist/archive/`,
  holding the Windows and Linux folders together, written after the build
  rather than by the next one. A KASTR left running no longer fails the build.

## v0.5.3

- **Share is now its own trimmed view.** The Share dropdown on Watch no longer
  embeds the whole Publish page. Encoder settings, the relay field, the preview
  tiles and the verbose status panel are gone; what is left is pick a source,
  name it, go live. "All publish settings" in the dropdown header still opens
  the full page.
- **Publish removed from the top bar.** It is reachable from the Home page and
  from the Share dropdown.
- Release notes added, viewable from the version in the masthead.

## v0.5.2

- **Watch: per-stream volume.** Every row has its own level, multiplied by the
  master slider, so several streams can be heard at different volumes.
- **Watch: Share dropdown** — publish without leaving the page. It is lazy, and
  closing it does not stop anything already on air.
- **Watch: prefix and latency target removed** from the toolbar; they are fixed
  at "everything" and 500 ms.
- **Bandwidth follows the window.** Grid tiles scrolled out of view stop
  downloading instead of decoding everything at once. When a catalog offers
  several renditions, the one matching the pane size is requested — no effect on
  KASTR's own streams, which publish a single rendition.
- **Publish: previews off by default**, which is what a publishing box wants.
- Version number added, shown in the masthead. Each build archives the previous
  one to `dist/archive/` and Windows builds moved to `dist/windows/`.

## v0.5.1

- **Watch: full screen per stream** — a button on each stream, or `F`. Fixed two
  bugs found while testing: the click's user activation was being discarded, so
  switching straight between full-screened streams was always refused, and the
  failure message was written where a once-a-second refresh immediately erased it.
- **Watch: expandable stats** — codec, resolution, frame rate, frames decoded,
  throughput, audio context state and the raw catalog, matching what the old
  upstream Watch page showed.
- Nav reordered to Publish / Watch / Studio; relay stats moved into the relay
  badge at top right; the app opens on Home.

## v0.5

First numbered build. Everything before this was unversioned.

- **Watch** (was Switcher): grid view by default, multi-source audio, keyboard
  switching, warm-audio gating so switching streams never drops sound.
- **Publish**: any mix of cameras, screen/window/tab, RTSP feeds and local files,
  each its own broadcast named after the machine. Sources can be added and
  removed while on air.
- **Relay**: hosts a MoQ relay on this machine with the bundled `moq-relay`.
- **RTSP ingest** through a bundled ffmpeg, with a built-in test pattern.
- **Studio**: Publish and Watch side by side.
- Tabbed shell so switching pages does not stop what is running.
- Windows and Linux builds, both self-contained.
