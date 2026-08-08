    // CMRE_ON_DEMAND_PRESELECTED_COMMANDER_STARTUP
{{P1_COMMANDER_SETUP}}
{{P2_COMMANDER_SETUP}}
    GameSetMissionTimePaused(false);
    AITimePause(false);
    UnitPauseAll(false);
    libCOOC_gf_ShowHideWorldCover(false, 0.0, 1);
    if ((PlayerType(14) == c_playerTypeUser)) {
        libCOOC_gf_ShowHideWorldCover(false, 0.0, 14);
    }
    libNtve_gf_HideGameUI(true, PlayerGroupAll());
    BankLoad("CMRERebornDebug", 1);
    if (BankLastCreated() != null) {
        BankValueSetFromInt(BankLastCreated(), "debug", "preselected_commander_startup", 1);
        BankSave(BankLastCreated());
    }
    libCOOC_gf_CC_DevStartupFinish();
    return ;
