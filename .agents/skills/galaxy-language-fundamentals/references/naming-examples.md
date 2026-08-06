# Naming Convention Examples from SC2-IngameDevTools

Reference detail split out of the `galaxy-language-fundamentals` skill. Real examples
illustrating the handler-module naming convention.

```galaxy
// BehaviorHandler.galaxy — complete module pattern
include "Script/debug_h"
include "Script/ItemList"

static const string CONTAINERDLG_PATH = "UIContainer/ConsoleUIContainer/CatalogManager/BehaviorManager";

ItemListContainerStruct BehaviorContainer;   // global module state (PascalCase)
static string ItemList;                       // file-private
static ListBoxFilterStruct ListBoxFilter;     // file-private

// Trigger handler — bool(bool,bool) signature, registered by string name
bool BehaviorListBoxFilterQuery(bool a, bool b) {
    int player = EventPlayer();               // locals are plain camelCase
    playergroup pg = PlayerGroupSingle(player);
    string val = DialogControlGetPropertyAsString(
        ListBoxFilter.editbox, c_triggerControlPropertyEditText, player);
    ItemList_FilterListRebuild(ItemList, ListBoxFilter, val, pg);
    return true;
}

bool BehaviorContainerSendHandler(bool a, bool b) {
    bool trigRan = true;
    string val = DialogControlGetPropertyAsString(
        BehaviorContainer.messageBox, c_triggerControlPropertyEditText, EventPlayer());
    // ...
    return trigRan;
}

void BehaviorHandler_Init() {                 // the ONE public entry point
    playergroup pg = PlayerGroupAll();
    ItemList = "BehaviorList";
    ItemListContainer_InitStandard(BehaviorContainer, CONTAINERDLG_PATH,
        "BehaviorContainerSendHandler");
    ItemListInitFromCatalog(ItemList, c_gameCatalogBehavior, ItemListCatalogFilter);
    ItemList_FilterListInitStandard(ListBoxFilter, "BehaviorListBox",
        BehaviorListBoxSetActive, ItemListItemTextValue, CONTAINERDLG_PATH+"/NavList");
    ItemList_FilterListRebuild(ItemList, ListBoxFilter, "", pg);
}
```

```galaxy
// Struct declaration — FeatureNameStruct pattern
struct EffectContainerStruct {
    int panel;
    int messageBox;
    int addButton;
    int removeButton;
    int sourceButton;
    int targetButton;
    int sourceUnitFrame;
    int targetUnitFrame;
    unit source;
    unit target;
};
// Typedef for passing by reference:
typedef structref<EffectContainerStruct> EffectContainerStructRef;
```

```galaxy
// Funcref typedef pattern for callbacks
void ItemListSetActiveCallbackDef(ItemListStructRef itemList, int index, playergroup pg);
typedef funcref<ItemListSetActiveCallbackDef> ItemListSetActiveCallback;

int ItemListForEachCallBack(string element, int currentIndex, ItemListStructRef itemList);
typedef funcref<ItemListForEachCallBack> ItemListForEachCallBackRef;
```

```galaxy
// Library utility functions: libPrefix_lowercaseName
void libGalExe_debug(int player, string msg) { ... }
string libGalExe_strip(string message) { ... }
actor libGalExe_actor(int player, string param) { ... }
```

```galaxy
// debug.galaxy — ultra-short global debug helpers
void print(string s)   { TriggerDebugOutput(1, StringToText(s), true); }
void console(string s) { TriggerDebugOutput(1, StringToText(s), false); }
void err(string s)     { TriggerDebugOutput(1, StringToText(s), true); }

// Module-private console wrapper:
static void CatalogValueHandler_console(string s) {
    TriggerDebugOutput(DEBUG_TYPE_INFO, StringToText(s), false);
}
```
