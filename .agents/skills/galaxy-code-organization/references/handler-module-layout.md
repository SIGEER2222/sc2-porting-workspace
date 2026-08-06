# SC2-IngameDevTools Handler-Module Layout (Full Walkthrough)

Reference detail split out of the `galaxy-code-organization` skill. The SC2-IngameDevTools
project (https://github.com/abrahamYG/SC2-IngameDevTools/tree/main/DevToolsIngame.SC2Mod/Script)
organises each feature as a self-contained **handler file** in `Script/`. There is one main
coordinator, a shared utilities folder, and a `_h.galaxy` header for forward declarations.

## Folder & file structure
```
Script/
├── DevToolsMain.galaxy          ← coordinator: includes all handlers, calls all _Init()
├── debug.galaxy                 ← global debug helpers: print(), console(), err()
├── debug_h.galaxy               ← forward declarations only (header pattern)
├── split_string.galaxy          ← utility (string split)
├── ItemList.galaxy              ← shared data structure (aggregator)
├── ItemListListBoxFormat.galaxy ← formatting helpers for ItemList
├── AbilityHandler.galaxy        ← feature handler (one per module)
├── AbilityOrderHandler.galaxy
├── ActorMessageHandler.galaxy
├── BehaviorHandler.galaxy
├── CameraHandler.galaxy
├── CameraShakeHandler.galaxy
├── CatalogLinkHandler.galaxy
├── CatalogValueHandler.galaxy
├── CheatHandler.galaxy
├── DataEditorHandler.galaxy
├── DataTableHandler.galaxy
├── DoodadHandler.galaxy
├── EffectHandler.galaxy
├── FogHandler.galaxy
├── LightingHandler.galaxy
├── PlayerHandler.galaxy
├── PortraitHandler.galaxy
├── RaceHandler.galaxy
├── SkinHandler.galaxy
├── SoundtrackHandler.galaxy
├── UnitHandler.galaxy
├── UpgradeHandler.galaxy
├── UserDataHandler.galaxy
├── WeaponHandler.galaxy
├── FreeCamHandler.galaxy
├── ItemList/
│   ├── index.galaxy             ← the actual ItemList implementation
│   └── Listbox.galaxy           ← listbox sub-feature
└── DevTools/
    ├── helpers.galaxy           ← shared helper functions (spawn point, movement tracker)
    ├── helpers_h.galaxy         ← forward declarations for helpers
    ├── ChatCommand.galaxy       ← chat command subsystem
    └── ChatCommand/
        └── Commands.galaxy        ← registered chat commands
```

## Main coordinator (`DevToolsMain.galaxy`)
```galaxy
include "Script/debug"
include "Script/DevTools/helpers"
include "Script/ActorMessageHandler"
include "Script/BehaviorHandler"
include "Script/EffectHandler"
include "Script/UnitHandler"
include "Script/UpgradeHandler"
include "Script/WeaponHandler"
include "Script/AbilityHandler"
include "Script/CatalogValueHandler"
include "Script/CatalogLinkHandler"
include "Script/LightingHandler"
include "Script/DataTableHandler"
include "Script/DataEditorHandler"
include "Script/CameraHandler"
include "Script/FogHandler"
include "Script/DevTools/ChatCommand"
include "Script/DevTools/ChatCommand/Commands"

void DevToolsMain_Init() {
    DevTools_ChatCommand_Init();
    helpersInit();
    ActorMessageHandler_Init();
    CatalogValueHandler_Init();
    UnitHandler_Init();
    BehaviorHandler_Init();
    EffectHandler_Init();
    LightingHandler_Init();
    // ... every handler's _Init() called here
    DevTools_ChatCommand_Commands_Init();
}
```

## Entry point wiring (`Lib7C0075CB.galaxy` — editor-generated lib file)
```galaxy
include "TriggerLibs/natives"
include "Lib7C0075CB_h"
include "TriggerLibs/NativeLib"
include "Script/DevToolsMain"

void TestMap_main() {
    DevToolsMain_Init();
}
void lib7C0075CB_InitCustomScript() {
    TestMap_main();
}
bool lib7C0075CB_InitLib_completed = false;
void lib7C0075CB_InitLib() {
    if (lib7C0075CB_InitLib_completed) { return; }
    lib7C0075CB_InitLib_completed = true;
    lib7C0075CB_InitCustomScript();
}
```

## Header file pattern (`debug_h.galaxy`)
```galaxy
// ONLY forward declarations — no implementations
void print(string s);
void printT(text t);
void console(string s);
void err(string s);
```

## Single handler module anatomy (`BehaviorHandler.galaxy`)
```galaxy
// 1. Include shared utilities
include "Script/debug_h"
include "Script/ItemList"

// 2. Path constants with UPPER_SNAKE_CASE
static const string CONTAINERDLG_PATH =
    "UIContainer/ConsoleUIContainer/CatalogManager/BehaviorManager";

// 3. Module struct + global instance
ItemListContainerStruct BehaviorContainer;

// 4. File-private state
static string ItemList;
static ListBoxFilterStruct ListBoxFilter;

// 5. Trigger event functions (bool a, bool b signature)
bool BehaviorListBoxFilterQuery(bool a, bool b) { ... }
bool BehaviorListBoxSelectionChanged(bool a, bool b) { ... }
bool BehaviorContainerSendHandler(bool a, bool b) { ... }

// 6. One public Init function
void BehaviorHandler_Init() {
    playergroup pg = PlayerGroupAll();
    ItemList = "BehaviorList";
    ItemListContainer_InitStandard(BehaviorContainer, CONTAINERDLG_PATH,
        "BehaviorContainerSendHandler");         // trigger registered by STRING name
    ItemListInitFromCatalog(ItemList, c_gameCatalogBehavior, ItemListCatalogFilter);
    ItemList_FilterListInitStandard(ListBoxFilter, "BehaviorListBox",
        BehaviorListBoxSetActive, ItemListItemTextValue,
        CONTAINERDLG_PATH+"/NavList");
    ItemList_FilterListRebuild(ItemList, ListBoxFilter, "", pg);
}
```
