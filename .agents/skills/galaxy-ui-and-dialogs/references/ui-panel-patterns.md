# SSF Hooked-Frame Panel Patterns (Hero Selection & Scoreboard)

Reference detail split out of the `galaxy-ui-and-dialogs` skill. SSF uses hooked XML frames for
feature panels; each panel is a separate file under `scripts/UI/`.

## Hero Selection Dialog Pattern

The `HeroSelection.galaxy` file drives the logic while `UI-HeroPanel.galaxy` owns the dialog
controls:

```galaxy
// UI-HeroPanel.galaxy
static dialogcontrol HeroPanel_MainFrame;
static dialogcontrol[gv_MaxAmountHeroes + 1] HeroPanel_HeroButtons;

void HeroPanel_Init() {
    HeroPanel_MainFrame = DialogControlHookup(gv_UI_MasterFrame, c_triggerControlTypePanel, "HeroPanel");
    int i = 1;
    for (; i <= gv_MaxAmountHeroes; i += 1) {
        HeroPanel_HeroButtons[i] = DialogControlHookup(HeroPanel_MainFrame, c_triggerControlTypeButton, "Hero" + IntToString(i));
    }
    TriggerAddEventDialogControl(TriggerCreate("HeroPanel_Click"), c_playerAny, c_invalidDialogControlId, c_triggerControlEventTypeClick);
}

void HeroPanel_UpdatePlayer(int playerID) {
    // Show/hide based on unlock state
    int i = 1;
    for (; i <= gv_MaxAmountHeroes; i += 1) {
        bool unlocked = ((gv_PlayerStats[playerID].heroUnlocked & (1 << i)) != 0);
        DialogControlSetEnabled(HeroPanel_HeroButtons[i], PlayerGroupSingle(playerID), unlocked);
    }
}
```

### Level-up upgrade panel

```galaxy
bool HeroLevelUp_Handler(bool testCond, bool runActions) {
    unit hero = EventUnit();
    int level = UnitXPGetCurrentLevel(hero);
    int player = UnitGetOwner(hero);
    // Show appropriate upgrade panel for this level
    if (level == 2) {
        DialogControlSetVisible(gv_UpgradeFrame_Level2, PlayerGroupSingle(player), true);
    }
    return true;
}
```

## Scoreboard / Stats Panel Pattern

The player board is a hooked XML frame, updated by calling `PlayerBoard_UpdatePlayer(playerID)`:

```galaxy
// UI-PlayerBoard.galaxy
static dialogcontrol PlayerBoard_MainFrame;
static dialogcontrol[gv_MaxAmountPlayers + 1] PlayerBoard_KillsLabel;
static dialogcontrol[gv_MaxAmountPlayers + 1] PlayerBoard_ScoreLabel;

void PlayerBoard_Init() {
    PlayerBoard_MainFrame = DialogControlHookup(gv_UI_MasterFrame, c_triggerControlTypePanel, "PlayerBoard");
    int i = 1;
    for (; i <= gv_MaxAmountPlayers; i += 1) {
        PlayerBoard_KillsLabel[i] = DialogControlHookup(PlayerBoard_MainFrame, c_triggerControlTypeLabel, "Player" + IntToString(i) + "/Kills");
    }
}

void PlayerBoard_UpdatePlayer(int playerID) {
    libNtve_gf_SetDialogItemText(
        PlayerBoard_KillsLabel[playerID],
        IntToText(gv_PlayerStats[playerID].kills),
        PlayerGroupAll()
    );
}
```
