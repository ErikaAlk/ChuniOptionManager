# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-window **WinUI 3 / Windows App SDK** desktop app (.NET 8, x64-only, unpackaged) for browsing and editing a CHUNITHM arcade `option` folder — the mod/add-on packages (`A001`, `A300`, `AXVX`, `AZUR`, …) that hold songs, charts, and characters. The app scans the option root, renders songs and characters as game-styled cards, and writes edits back into the original `Music.xml` / `Chara.xml` / `DDSImage.xml` files. All user-facing strings are Chinese.

The app itself lives *inside* a real option tree (`C:\Chuni\CHUNITHM\bin\option\ChuniOptionManager`), so at runtime it auto-detects the surrounding option root.

## Build & run

```powershell
dotnet build -c Release -p:Platform=x64    # the user runs the Release build
```

- **The user runs the RELEASE build** (`bin\x64\Release\net8.0-windows10.0.19041.0\ChuniOptionManager.exe`). Building only `-c Debug` leaves Release stale and the user sees no change. Default to `-c Release`; build both configs if unsure which will be launched.
- **Use `-p:Platform=x64`, NOT `-r win-x64`.** Both compile, but they land in *different* output folders:
  - `-p:Platform=x64` → `bin\x64\{Debug,Release}\net8.0-windows10.0.19041.0\` — **the path Visual Studio uses and the user actually runs.**
  - `-r win-x64` → `bin\{Debug,Release}\net8.0-windows10.0.19041.0\win-x64\` — a *different* folder; a build here looks successful but the user sees no change because they run the VS-built exe elsewhere.
  - A bare `dotnet build` (no platform, no RID) fails with `WindowsAppSDKSelfContained requires a supported Windows architecture` — `Platform=x64` supplies the architecture.
- Before assuming the user will see a change, **confirm the timestamp of the exe they run** (`bin\x64\Release\...\ChuniOptionManager.exe`) actually updated — or have them F5 in **Visual Studio**, which always builds current source to the run location. The app must be closed during build or the exe/dll is locked.
- This machine has the **.NET 10 SDK** (`C:\Program Files\dotnet\sdk`) installed via Visual Studio; the target framework is still `net8.0-windows10.0.19041.0` and it builds clean.
- Builds are **x64 only** (`<Platforms>x64</Platforms>`, self-contained Windows App SDK).
- **No test project and no linter** are configured — there is nothing to run for tests.
- `bin/` and `obj/` are gitignored build output; ignore them when searching. `chuni-option-manager-*.png` are README screenshots.

## Architecture

Three layers, no MVVM framework — UI is **code-behind driven**.

- **`Models/`** — plain data classes (`MusicItem`, `ChartModel`, `CharacterItem`, `IssueItem`, `OptionCatalog`). They carry presentation helpers too: image properties lazy-load on first access (`JacketSource`, `BigImageSource`, …), `Matches(query)` powers search, and `DifficultyPalette` (in `ChartModel.cs`) is the single source of truth for difficulty colors, foreground, and rank ordering.
- **`Services/`** — all filesystem and XML work. Pure static classes, no DI.
- **`MainWindow.xaml` + `MainWindow.xaml.cs`** — the entire UI: one `NavigationView` with three pages (Music / Characters / Issues, toggled by `Visibility` in `RootNav_SelectionChanged`) plus two full-screen editor **overlays** (`SongEditorOverlay`, `CharacterEditorOverlay`). The 1400-line code-behind builds the "add character" dialog and the crop window imperatively (no XAML for them).

### Data flow

`OptionRootLocator.FindDefaultRoot()` → `OptionRepository.Scan(root)` (on a background `Task.Run`) → `OptionCatalog` → `ApplyFilters()` populates the `ObservableCollection`s (`FilteredSongs`, `FilteredCharacters`, `Issues`). Search/filter/sort all funnel through `ApplyFilters()`, which re-queries the in-memory catalog (results capped at `.Take(2000)`). After any save/delete the app re-scans the whole root and re-selects the edited item by `XmlPath`.

### `OptionRepository` — the core service

Central to almost everything. Static methods:
- **`Scan`** — recursively finds every `Music.xml` and `Chara.xml`, parses each into a model. Parsing is **failure-tolerant by design**: a malformed XML returns `null` and is skipped so one bad custom package can't stop the catalog from opening. Builds a `DDSImage.xml` index keyed by image name to link characters to their `.dds` files (preferring same-package matches).
- **`BuildIssues`** — the Issues page: enabled-but-missing `.c2s` files (High, one row per song merging all missing difficulties), same-ID duplicates with inconsistent difficulties (Medium), missing character image index (Low). (WORLD'S END splits are normal and intentionally NOT flagged.)
- **`SaveChartEnableStates`** — writes `<enable>` toggles back, preserving original whitespace (`LoadOptions.PreserveWhitespace` + `SaveOptions.DisableFormatting`).
- **`SaveCharacterSettings`** — writes character metadata fields back to `Chara.xml`.
- **`AddCharacter`** — see below.
- **`DeleteMusic` / `DeleteCharacter`** — soft delete (see below).
- **`ListWorks` / `ListWorksPackages` / `AddWorks` / `UpdateWorks` / `DeleteWorks`** — the works (作品) library: scan/create/edit/soft-delete `charaWorks{id:D6}\CharaWorks.xml` and maintain `WorksSort.xml` ordering (`AddWorksToSortFirst` creates the file/dir if missing; `RemoveWorksFromSort`). `AddWorks` takes a target **package** (any top-level option folder, not just AZUR). `DeleteWorks` **cascades**: it also soft-deletes every character whose `works id` matches (their Chara + DDSImage dirs go to `_deleted` alongside the works).

### Difficulty mapping

`Music.xml` stores difficulty as `ID_00`..`ID_05`; `NormalizeDifficulty` maps these to `BASIC / ADVANCED / EXPERT / MASTER / ULTIMA / WORLD'S END` (also `ULTRA`→`ULTIMA`, `WorldsEnd`→`WORLD'S END`). Use these normalized strings everywhere downstream; `DifficultyPalette.Rank` gives their sort order.

### Adding characters → the AZUR package

`AddCharacter` clones templates from the **`AZUR`** package (`chara114514` / `ddsImage114514`), allocates the next free `chara{id}` (≥114514), and writes `Chara.xml` + `DDSImage.xml`. New character `priority = 999`. The works the character belongs to comes from `AddCharacterRequest.WorksId/WorksName` (chosen in the dialog from the works library; `0` = Invalid) and is written into `Chara.xml`'s `works` id/str — it's no longer hardcoded to `11451`. If the chosen works is defined in the AZUR library, `EnsureWorksPriority` + `AddWorksToSortFirst` bump its visibility. If a source image is supplied (via the quick-crop window) it's converted to DDS; otherwise **no `.dds` is written** (no template fallback) — the character is created imageless. The three texture status boxes in the dialog stay hidden until a quick-crop generation fills them.

The "新建/管理库" works dialogs and the "单图快速生成" crop are separate **`Window`s**, not `ContentDialog`s — WinUI allows only one `ContentDialog` open per `XamlRoot`, and they're launched from inside the open "新增角色" `ContentDialog`. For the same reason the works-manager's delete uses a two-click inline confirm instead of a nested confirm dialog.

### DDS pipeline (the tricky part)

WinUI's `BitmapImage` cannot load `.dds`, so there are two hand-written codecs:
- **`DdsImageGenerator`** — encodes PNG/JPG → **DXT5 (BC3) DDS** with full mipmap chain, at sizes 1080 / 512 / 128 (`big.dds` / `small.dds` / `thumb.dds`). Includes a from-scratch BC3 block encoder (`WriteAlphaBlock` / `WriteColorBlock`) and square crop/zoom logic (`RenderSquare`).
- **`DdsPreviewCache`** — decodes DDS (DXT1/3/5) → PNG for on-screen preview, cached in `%TEMP%\ChuniOptionManager\dds-preview\` keyed by path+size+mtime. Models call this lazily when their image source is requested.

Image work uses **`System.Drawing.Common`** (GDI+), which is Windows-only — fine here, but don't assume cross-platform.

## Conventions & gotchas

- **Backups & soft delete**: the first save of any file copies it to `<file>.bak` (only once). Deletes never remove data — they move directories into `option\_deleted\<timestamp>_<type>_<id>_<name>\`, which `Scan` excludes (`IsDeletedPath`). `_deleted` is the recycle area; `*.bak` is gitignored.
- **Path safety**: `MoveToDeleted` calls `EnsureInsideOptionRoot` to refuse moving anything outside the option root or the root itself.
- **Two different XML writers, intentionally**: chart enable-state saves preserve byte-for-byte formatting; character/template saves go through `SaveXml` which re-indents as UTF-8 (no BOM) with CRLF. Match the existing writer for whatever file you're touching.
- **App icon**: source is `Assets\AppIcon.png` → multi-size `Assets\AppIcon.ico` (regenerate with System.Drawing if the source changes). README screenshots live in `docs\`. Wired two ways: `<ApplicationIcon>` in the csproj (the exe's file icon) and `appWindow.SetIcon(...)` inside `ApplyDarkTitleBar` (title-bar/taskbar icon for *every* window — main, crop, add/manage-works — since they all call it). The `.ico` is a `Content` item copied to output so `SetIcon` finds it at `AppContext.BaseDirectory\Assets\`.
- **Crash logging**: `App.LogCrash(scope, ex)` appends to `startup.log` next to the exe. Global handlers (`UnhandledException`, `AppDomain`, `TaskScheduler`) are wired in the `App` constructor; UI methods wrap risky work and surface errors via `ShowStatus(...)` (the top `InfoBar`).
- **`_isUiReady` guard**: `ApplyFilters` and selection-changed handlers no-op until the window finishes initializing — keep that guard when adding new handlers that touch named controls.
- **Option-root detection**: a folder "looks like" an option root if it contains ≥2 of `A001`/`A300`/`AXVX` *and* has at least one `Music.xml` somewhere beneath it (`OptionRootLocator.LooksLikeOptionRoot`). The folder picker enforces this.
