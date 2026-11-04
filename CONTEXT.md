# Desktop Pet Experience

The user-facing desktop-pet experience of the Windows-only modular fork: one
pet, one overlay window, settings, menus, and the SurfCore client seam.

## Language

**Focus Session**:
The process-wide Pomodoro runtime of the single pet. It owns the current
focus/break phase, deadline, pause state and completed rounds; a finished phase
automatically starts the next full phase, with one sound at each boundary.
Pause/resume stays silent; explicit stop plays an end sound, while application
shutdown and quiet mode stay silent. Persistent work background and timing
preferences belong to the global Settings System. Explicit stop also presents
one persona farewell using actual elapsed focus time (excluding pauses/breaks)
and up to six short observations from this run. A cached template from the
existing observation request avoids an extra network call; local history keeps
only ten finished runs as bounded text, never screenshots. The island and context
menu invoke commands on this one runtime. Focus pauses autonomous walking and
replaces casual self-talk with persona-aware encouragement or a foreground-window
observation. Pausing, resting or exiting cancels pending focus speech; existing
quiet mode remains an independent user choice.
_Avoid_: Duplicate focus timers, permanently changing no-move, AI attention score

**Module**:
A feature package under `pet/modules/<id>/`, registered by one line in
`pet/modules/__init__.py::MODULES`. Its cheap `__init__.py` declares a
`ModuleManifest`; runtime, menu, settings page and config schema are reached
through string entry points (`"pkg.mod:attr"`) resolved with
`pet.modules.base.load_entry`. Deleting a module means deleting its directory
and its `MODULES` line, and its defaults, config keys, menu actions and settings
page disappear with it. Core never imports a concrete module.
_Avoid_: Plugin bundle, core feature, second module list

**ModuleHost**:
The only surface a module may use: `pet/module_host.py::AppModuleHost` over the
generic service table and queued event bus. It offers config, bubbles,
notifications, dialogs, island contributions and `provide`/`get` services;
modules never import `pet.app`, `pet.overlay_shell` or another module.
_Avoid_: Direct shell access, cross-module import

**Companion Line**:
The dialogue route for quick bubbles, island chat, proactive talk and
self-talk. It goes through SurfCore's pet-api so persona, memory, daily quota
and the shared proactive allowance stay in one place; when SurfCore is offline
the companion line disables itself with a reason (self-talk falls back to local
presets) and never silently switches to a second direct-API path.
_Avoid_: Direct-API quick chat, separate companion quota

**Assistant Line**:
The dialogue route of the full AI chat window and screen-looking requests. It
calls the user's API provider directly but always takes its persona from the
SurfCore persona card (last cached card when offline), and reports usage /
checks budget through `pet/surfcore_link.py` when SurfCore is available.
_Avoid_: SurfCore chat session, separate persona source

**SurfCore Client**:
The pet side of SurfCore: `pet/modules/surfcore/` discovers
`~/.dsh/surfcore/pet/host.json`, talks only to loopback with the pet token,
long-polls events and exposes the `surfcore` service; `pet/surfcore_link.py` is
the core seam for persona cache, budget gate, usage labels and proactive claim.
It reads the service and never imports the SurfCore module. `surfcore/` itself
is the Node/DSH plugin and is not Python.
_Avoid_: In-process SurfCore runtime, direct HTTP in the GUI thread

**Shared UX Contract**:
The Windows-only agreement for information architecture, state semantics,
interaction meaning, spacing roles, and brand roles. Native presentation may
vary within Windows without changing this contract.
_Avoid_: Pixel parity, identical native chrome

**Settings System**:
The single product surface that owns every persistent user preference. Legacy
settings may temporarily redirect into it but do not define a second contract.
_Avoid_: Modern settings, legacy settings

**Menu Action Model**:
The shared set of menu commands, canonical labels/icons, callbacks, capability
availability, and runtime enablement semantics, independent of the widget that
presents them.
_Avoid_: Modern menu behavior, legacy menu behavior

**Menu Layout Tree**:
A versioned tree of stable action IDs and one-level submenus. It owns order and
user visibility, explicit separators, and optional alias/icon presentation
overrides, while the Menu Action Model owns canonical presentation, callbacks,
runtime state, and build capability. Missing actions from newer versioned
defaults are inserted beside their nearest template sibling; explicit hidden
nodes and user ordering remain authoritative.
_Avoid_: Serialized QAction, presentation-specific menu order

**Menu Presentation Override**:
An optional Menu Layout Tree decoration. Aliases replace canonical labels only
at runtime while the editor retains the canonical label for orientation. Icon
overrides may select a semantic icon, suppress the icon, or reference a
validated local image with contain/cover rendering; an unreadable local image
falls back to the Menu Action Model icon.
_Avoid_: Renamed command, embedded image bytes

**Animation Menu Dismissal**:
The interaction rule of the animation submenus: triggering a play-once action
plays it and dismisses the whole menu chain, because the next thing the user
wants to see is the pet. It governs the play-once animation leaves only —
toggles, value pickers, and submenu navigation keep their own rules — and the
`anim_menu_stay_open` preference (default off) restores the stay-open behavior
for users who chain several actions. The random-action list is grouped by the
prefix families already present in the animation names, so no level of that
menu needs scrolling across a whole screen.
_Avoid_: Sticky menu, per-item dismissal flag

**Capability Unavailable**:
An action cannot exist in this Windows build (missing optional runtime,
dependency, or hardware capability). The Menu Layout Tree retains its position,
while the current runtime may omit it and the editor explains the capability
reason.
_Avoid_: Disabled feature, hidden action

**Runtime Disabled**:
An action exists in this build but its owning feature is currently off or has no
configured content. It keeps its Menu Layout Tree position and is rendered with
a disabled style and explanation; changing the feature toggle never rewrites or
filters the tree.
_Avoid_: Capability unavailable, user-hidden

**Settings Popup Surface**:
The shared settings-menu presentation used by selectors and command buttons.
It owns popup anchoring, minimum trigger width, row geometry, disabled state,
submenu arrows, and trailing selection checks; callers only provide actions.
_Avoid_: Copied menu stylesheet, native button menu indicator

**Image Directory Preview**:
An on-demand right-side drawer for image-directory settings. It uses three
shortest-height columns, preserves each thumbnail's useful aspect ratio, labels
every card with an elided filename and full-name tooltip, and defers directory
scanning and image decoding until the user presses Preview.
_Avoid_: Inline settings grid, eager gallery

**Settings Capability Domain**:
A stable sidebar destination organized by user intent. Every persistent setting
has one owning domain; capability changes availability, not ownership.
_Avoid_: Module page, Windows settings page

**Settings Reset**:
The whole-settings recovery command in the Settings System sidebar. It restores
every persistent preference to its factory default in one atomic write and keeps
only the AI provider credentials — every provider's key fields plus, for
providers outside the default set, a credential-only entry that holds the name
and the key (`base_url`/`model` return to the default template). It then closes
the settings window, syncs the system login item to the reset value, and asks
the running pet to align its runtime position to the new default so the exit-time
position save cannot write the pre-reset position back. Character and asset
settings take effect on restart. There is no per-page reset.
_Avoid_: Per-page reset, credential reset

**Report Gate**:
The single control for how much of one aggregated event class the pet reports.
It is a pass probability in `0.00–1.00` (`0.00` silences the class, `1.00`
reports every occurrence) and there is no boolean switch: the settings slider is
the only fine-grained control, while the pet menu offers only the two endpoints.
A gate governs the bubble step alone — detectors and the raw-record chain are
never sampled — and it never covers the whole feature.
_Avoid_: Notification toggle, report percentage, global mute

**Gate Group**:
The collapsible settings block that collects every report gate with the
bubble-phrase rows of its own event class, so a gate sits next to what it
controls. It is expanded by default and auto-expands when a search matches a row
inside it.
_Avoid_: Hidden advanced panel, per-feature switch list

**Quiet Mode**:
A process-wide, non-persistent do-not-disturb window covering the pet window and
sprite. It suppresses ordinary reminders and bubbles — the pet
bubble and the system notification of that same reminder — while self-talk
(including click responses), link-state bubbles, and every stateful or
interactive event (approval, question, error, lifecycle, balance) keep
presenting, because those are answers the user must act on. Suppressed
reminders are queued with a fixed bound (oldest dropped first) and reported in
one bubble when quiet ends. A fullscreen application counts as quiet only while
the persistent `quiet_also_on_fullscreen` preference is on, and it is the same
fullscreen signal the auto-hide avoidance already uses.
_Avoid_: Notification mute, global sound mute, separate pet mute

**Session-End Spawn Freeze**:
The process-wide latch armed when the operating system announces that the
session is ending (`WM_QUERYENDSESSION`/`WM_ENDSESSION`, or Qt's session
signals as a fallback). While armed, no child ffmpeg process may be spawned and
existing readers are stopped, because a process created inside a tearing-down
Windows session fails DLL initialization (0xc0000142) and blocks shutdown.
The freeze is one-way: a process that survives a cancelled shutdown stays
frozen rather than resuming animation.
_Avoid_: Shutdown option, ffmpeg kill switch
