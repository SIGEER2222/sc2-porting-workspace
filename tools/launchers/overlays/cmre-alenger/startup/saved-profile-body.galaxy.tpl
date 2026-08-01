    // CMRE_ON_DEMAND_SAVED_PROFILE_STARTUP
    if ((CMUIX_CoreReady == false)) { CMUIX_CoreInit(); }
    CMUIX_StartupLoadPersistentProfiles();
    CMUIX_HistoryPrunePendingRecordsAll();
    CMUIX_LaunchProfileOpenBank(1);
    if (BankLastCreated() != null) {
        BankValueSetFromInt(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "CreatedAt", DateTimeToInt(CurrentDateTimeGet()));
        BankValueSetFromString(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "TargetMission", CMUIX_MapSelectionCurrentMapInstance());
        BankValueSetFromString(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "TargetMap", CMUIX_MapSelectionCurrentMapInstance());
        BankSave(BankLastCreated());
        if (CMUIX_LaunchProfileValidForStartup(BankLastCreated()) == true) {
            CMUIX_LaunchProfileApply(BankLastCreated());
        }
    }
{{P1_COMMANDER_SETUP}}
{{P2_COMMANDER_SETUP}}
{{MODE_TAIL}}
