// Scratch-only (never shipped): fills the save blocks with a mid/late game for the
// screen rig and warps into the map, from where the rig saves it with the start
// menu. Built in when build_gba.sh runs with RIG_FILL=1; started by writing
// CB2_RigFillSave to gMain.callback2 (at the title screen). gRigFillVariant picks
// the place: 0 Mauville's Pokémon Center 1F, 1 Mauville City by the Game Corner,
// 2 Slateport's Name Rater, 3 Lilycove's Contest Lobby (the receptionist).
#include "global.h"
#include "main.h"
#include "coins.h"
#include "event_data.h"
#include "item.h"
#include "mail.h"
#include "mauville_old_man.h"
#include "money.h"
#include "new_game.h"
#include "overworld.h"
#include "play_time.h"
#include "pokeblock.h"
#include "pokedex.h"
#include "pokemon.h"
#include "script.h"
#include "sound.h"
#include "string_util.h"
#include "constants/battle.h"
#include "constants/characters.h"
#include "constants/easy_chat.h"
#include "constants/maps.h"
#include "constants/flags.h"
#include "constants/game_stat.h"
#include "constants/heal_locations.h"
#include "constants/items.h"
#include "constants/map_groups.h"
#include "constants/moves.h"
#include "constants/region_map_sections.h"
#include "constants/species.h"
#include "constants/vars.h"

u32 gRigFillVariant;

struct RigMon
{
    u16 species;
    u8 level;
    const u8 *nickname;
    u16 item;
    u16 moves[MAX_MON_MOVES];
    u8 condition[6]; // cool, beauty, cute, smart, tough, sheen
    u32 personality;
};

static const u8 sNick0[] = _("ラグ");
static const u8 sNick1[] = _("サーナ");
static const u8 sNick2[] = _("チルル");
static const u8 sNick4[] = _("ザンギ");
static const u8 sNick5[] = _("ミロ");
static const u8 sPlayerName[] = _("ユウキ");

static const struct RigMon sParty[PARTY_SIZE] =
{
    {SPECIES_SWAMPERT, 45, sNick0, ITEM_MYSTIC_WATER, {MOVE_SURF, MOVE_EARTHQUAKE, MOVE_ROCK_SLIDE, MOVE_PROTECT}, {120, 80, 30, 60, 200, 100}, 0x00000011},
    {SPECIES_GARDEVOIR, 42, sNick1, ITEM_TWISTED_SPOON, {MOVE_PSYCHIC, MOVE_CALM_MIND, MOVE_THUNDERBOLT, MOVE_DOUBLE_TEAM}, {10, 150, 180, 220, 5, 60}, 0x12345678},
    {SPECIES_ALTARIA, 40, sNick2, ITEM_NONE, {MOVE_DRAGON_DANCE, MOVE_FLY, MOVE_EARTHQUAKE, MOVE_DRAGON_CLAW}, {50, 255, 90, 40, 70, 20}, 0x0000BEEF},
    {SPECIES_PIKACHU, 30, NULL, ITEM_LIGHT_BALL, {MOVE_THUNDERBOLT, MOVE_QUICK_ATTACK, MOVE_THUNDER_WAVE, MOVE_IRON_TAIL}, {0, 0, 255, 0, 0, 0}, 0xF0000001},
    {SPECIES_ZANGOOSE, 38, sNick4, ITEM_QUICK_CLAW, {MOVE_CRUSH_CLAW, MOVE_SWORDS_DANCE, MOVE_SHADOW_BALL, MOVE_BRICK_BREAK}, {200, 0, 0, 0, 120, 200}, 0x00C0FFEE},
    {SPECIES_MILOTIC, 35, sNick5, ITEM_LEFTOVERS, {MOVE_SURF, MOVE_RECOVER, MOVE_ICE_BEAM, MOVE_ATTRACT}, {30, 255, 120, 90, 10, 255}, 0x0BADF00D},
};

static const u16 sItems[][2] =
{
    {ITEM_POTION, 12}, {ITEM_SUPER_POTION, 6}, {ITEM_HYPER_POTION, 3}, {ITEM_FULL_RESTORE, 2},
    {ITEM_REVIVE, 4}, {ITEM_ANTIDOTE, 3}, {ITEM_PARALYZE_HEAL, 2}, {ITEM_AWAKENING, 1},
    {ITEM_BURN_HEAL, 2}, {ITEM_ICE_HEAL, 1}, {ITEM_FULL_HEAL, 3}, {ITEM_ESCAPE_ROPE, 2},
    {ITEM_REPEL, 5}, {ITEM_SUPER_REPEL, 3}, {ITEM_MAX_REPEL, 1}, {ITEM_RARE_CANDY, 3},
    {ITEM_PP_UP, 1}, {ITEM_HP_UP, 2}, {ITEM_X_ATTACK, 1}, {ITEM_FIRE_STONE, 1},
    {ITEM_THUNDER_STONE, 1}, {ITEM_HEART_SCALE, 4}, {ITEM_NUGGET, 1}, {ITEM_STARDUST, 2},
    {ITEM_SHOAL_SALT, 3}, {ITEM_RED_SHARD, 1}, {ITEM_ORANGE_MAIL, 2}, {ITEM_HARBOR_MAIL, 1},
    {ITEM_POKE_BALL, 20}, {ITEM_GREAT_BALL, 10}, {ITEM_ULTRA_BALL, 5}, {ITEM_NET_BALL, 3},
    {ITEM_DIVE_BALL, 2}, {ITEM_NEST_BALL, 2}, {ITEM_REPEAT_BALL, 1}, {ITEM_TIMER_BALL, 4},
    {ITEM_LUXURY_BALL, 1}, {ITEM_PREMIER_BALL, 1}, {ITEM_MASTER_BALL, 1},
    {ITEM_MACH_BIKE, 1}, {ITEM_ACRO_BIKE, 1}, {ITEM_COIN_CASE, 1}, {ITEM_POKEBLOCK_CASE, 1},
    {ITEM_WAILMER_PAIL, 1}, {ITEM_ITEMFINDER, 1}, {ITEM_OLD_ROD, 1}, {ITEM_GOOD_ROD, 1},
    {ITEM_SOOT_SACK, 1}, {ITEM_CONTEST_PASS, 1}, {ITEM_GO_GOGGLES, 1}, {ITEM_DEVON_SCOPE, 1},
    {ITEM_METEORITE, 1},
};

static const struct Pokeblock sPokeblocks[] =
{
    {PBLOCK_CLR_RED, 20, 0, 0, 0, 0, 15},
    {PBLOCK_CLR_BLUE, 0, 22, 0, 0, 0, 20},
    {PBLOCK_CLR_PINK, 0, 0, 30, 0, 0, 25},
    {PBLOCK_CLR_GREEN, 0, 0, 0, 18, 0, 18},
    {PBLOCK_CLR_YELLOW, 0, 0, 0, 0, 25, 22},
    {PBLOCK_CLR_PURPLE, 15, 10, 0, 0, 0, 30},
    {PBLOCK_CLR_INDIGO, 0, 12, 14, 0, 0, 28},
    {PBLOCK_CLR_GOLD, 40, 0, 40, 0, 0, 10},
    {PBLOCK_CLR_BLACK, 2, 2, 2, 2, 0, 50},
    {PBLOCK_CLR_GRAY, 0, 0, 0, 0, 0, 40},
};

static const u16 sMatchCallFlags[] =
{
    FLAG_ENABLE_MOM_MATCH_CALL, FLAG_ENABLE_PROF_BIRCH_MATCH_CALL, FLAG_ENABLE_RIVAL_MATCH_CALL,
    FLAG_REGISTERED_STEVEN_POKENAV, FLAG_ENABLE_NORMAN_MATCH_CALL, FLAG_ENABLE_MR_STONE_POKENAV,
    FLAG_REGISTERED_ROXANNE, FLAG_REGISTERED_BRAWLY, FLAG_REGISTERED_WATTSON,
    FLAG_REGISTERED_ROSE, FLAG_REGISTERED_ANDRES, FLAG_REGISTERED_DUSTY, FLAG_REGISTERED_LOLA,
    FLAG_REGISTERED_RICKY, FLAG_REGISTERED_CINDY, FLAG_REGISTERED_THALIA, FLAG_REGISTERED_TONY,
    FLAG_REGISTERED_JEFFREY, FLAG_REGISTERED_DALTON, FLAG_REGISTERED_ISABEL,
};

static void GiveRigMon(const struct RigMon *m)
{
    struct Pokemon mon;
    u8 name[POKEMON_NAME_LENGTH + 1];
    u32 i, hp;

    CreateMon(&mon, m->species, m->level, 20, TRUE, m->personality, OT_ID_PLAYER_ID, 0);
    for (i = 0; i < MAX_MON_MOVES; i++)
        SetMonMoveSlot(&mon, m->moves[i], i);
    if (m->nickname != NULL)
    {
        memset(name, EOS, sizeof(name));
        StringCopy(name, m->nickname);
        SetMonData(&mon, MON_DATA_NICKNAME, name);
    }
    SetMonData(&mon, MON_DATA_HELD_ITEM, &m->item);
    // Met somewhere along the way, not in the truck where the new game starts.
    i = MAPSEC_ROUTE_101 + (m->personality % 20);
    SetMonData(&mon, MON_DATA_MET_LOCATION, &i);
    SetMonData(&mon, MON_DATA_COOL, &m->condition[0]);
    SetMonData(&mon, MON_DATA_BEAUTY, &m->condition[1]);
    SetMonData(&mon, MON_DATA_CUTE, &m->condition[2]);
    SetMonData(&mon, MON_DATA_SMART, &m->condition[3]);
    SetMonData(&mon, MON_DATA_TOUGH, &m->condition[4]);
    SetMonData(&mon, MON_DATA_SHEEN, &m->condition[5]);
    CalculateMonStats(&mon);
    hp = GetMonData(&mon, MON_DATA_MAX_HP);
    hp = hp * 3 / 4;
    if (m->species == SPECIES_PIKACHU)
        SetMonData(&mon, MON_DATA_HP, &hp);
    GiveMonToPlayer(&mon);
    GetSetPokedexFlag(SpeciesToNationalPokedexNum(m->species), FLAG_SET_SEEN);
    GetSetPokedexFlag(SpeciesToNationalPokedexNum(m->species), FLAG_SET_CAUGHT);
}

static void FillParty(void)
{
    u32 i, val, status;
    u16 mailId;

    gPlayerPartyCount = 0;
    ZeroPlayerPartyMons();
    for (i = 0; i < PARTY_SIZE; i++)
        GiveRigMon(&sParty[i]);

    // Ribbons on the first: contest ranks, the Champion and Effort ribbons.
    val = 4; SetMonData(&gPlayerParty[0], MON_DATA_COOL_RIBBON, &val);
    val = 2; SetMonData(&gPlayerParty[0], MON_DATA_TOUGH_RIBBON, &val);
    val = 1; SetMonData(&gPlayerParty[0], MON_DATA_BEAUTY_RIBBON, &val);
    val = TRUE;
    SetMonData(&gPlayerParty[0], MON_DATA_CHAMPION_RIBBON, &val);
    SetMonData(&gPlayerParty[0], MON_DATA_EFFORT_RIBBON, &val);
    SetMonData(&gPlayerParty[0], MON_DATA_WINNING_RIBBON, &val);
    // And a few on Milotic.
    val = 3; SetMonData(&gPlayerParty[5], MON_DATA_BEAUTY_RIBBON, &val);
    val = 1; SetMonData(&gPlayerParty[5], MON_DATA_CUTE_RIBBON, &val);
    FlagSet(FLAG_SYS_RIBBON_GET);

    // Zangoose is poisoned.
    status = STATUS1_POISON;
    SetMonData(&gPlayerParty[4], MON_DATA_STATUS, &status);

    // Altaria holds a mail with words in it.
    mailId = GiveMailToMonByItemId(&gPlayerParty[2], ITEM_ORANGE_MAIL);
    if (mailId != MAIL_NONE)
    {
        struct Mail *mail = &gSaveBlock1Ptr->mail[mailId];
        mail->words[0] = EC_WORD_HELLO;
        mail->words[1] = EC_POKEMON(ALTARIA);
        mail->words[2] = EC_WORD_GOOD;
        mail->words[3] = EC_WORD_THANKS;
        mail->words[4] = EC_POKEMON(SWAMPERT);
    }
}

static void FillPokedex(void)
{
    u32 i;

    for (i = 1; i <= 180; i++)
        GetSetPokedexFlag(HoennToNationalOrder(i), FLAG_SET_SEEN);
    for (i = 1; i <= 150; i += (i < 60) ? 1 : 2)
        GetSetPokedexFlag(HoennToNationalOrder(i), FLAG_SET_CAUGHT);
    // A few outside Hoenn's dex for the national one.
    for (i = 1; i <= 151; i += 5)
    {
        GetSetPokedexFlag(i, FLAG_SET_SEEN);
        if (i % 2)
            GetSetPokedexFlag(i, FLAG_SET_CAUGHT);
    }
    EnableNationalPokedex();
    gSaveBlock2Ptr->pokedex.mode = DEX_MODE_HOENN;
}

static void FillBag(void)
{
    u32 i;

    ClearBag();
    for (i = 0; i < ARRAY_COUNT(sItems); i++)
        AddBagItem(sItems[i][0], sItems[i][1]);
    for (i = ITEM_TM01; i <= ITEM_TM50; i += 3)
        AddBagItem(i, 1 + i % 3);
    for (i = ITEM_HM01; i <= ITEM_HM08; i++)
        AddBagItem(i, 1);
    for (i = FIRST_BERRY_INDEX; i < FIRST_BERRY_INDEX + 30; i++)
        AddBagItem(i, 1 + (i * 7) % 20);
    gSaveBlock1Ptr->registeredItem = ITEM_MACH_BIKE;

    ClearPokeblocks();
    for (i = 0; i < ARRAY_COUNT(sPokeblocks); i++)
        AddPokeblock(&sPokeblocks[i]);
}

static void FillFlags(void)
{
    u32 i;

    FlagSet(FLAG_SYS_POKEMON_GET);
    FlagSet(FLAG_SYS_POKEDEX_GET);
    FlagSet(FLAG_RECEIVED_POKEDEX_FROM_BIRCH);
    FlagSet(FLAG_SYS_POKENAV_GET);
    FlagSet(FLAG_RECEIVED_POKENAV);
    FlagSet(FLAG_ADDED_MATCH_CALL_TO_POKENAV);
    FlagSet(FLAG_SYS_B_DASH);
    FlagSet(FLAG_RECEIVED_RUNNING_SHOES);
    FlagSet(FLAG_RECEIVED_COIN_CASE);
    FlagSet(FLAG_SYS_CLOCK_SET);
    for (i = FLAG_BADGE01_GET; i <= FLAG_BADGE05_GET; i++)
        FlagSet(i);
    for (i = 0; i < ARRAY_COUNT(sMatchCallFlags); i++)
        FlagSet(sMatchCallFlags[i]);
    // Mauville after Wally's battle by the gym.
    FlagSet(FLAG_DEFEATED_WALLY_MAUVILLE);
    FlagSet(FLAG_HIDE_MAUVILLE_CITY_WALLY);
    FlagSet(FLAG_HIDE_MAUVILLE_CITY_WALLYS_UNCLE);
    FlagSet(FLAG_HIDE_MAUVILLE_CITY_SCOTT);
}

static void FillPlayer(void)
{
    u32 id = 0x5A1EC81E; // public 51230: the last digit makes Mauville's old man the bard

    memset(gSaveBlock2Ptr->playerName, EOS, sizeof(gSaveBlock2Ptr->playerName));
    StringCopy(gSaveBlock2Ptr->playerName, sPlayerName);
    gSaveBlock2Ptr->playerGender = MALE;
    gSaveBlock2Ptr->playerTrainerId[0] = id;
    gSaveBlock2Ptr->playerTrainerId[1] = id >> 8;
    gSaveBlock2Ptr->playerTrainerId[2] = id >> 16;
    gSaveBlock2Ptr->playerTrainerId[3] = id >> 24;
    gSaveBlock2Ptr->optionsTextSpeed = OPTIONS_TEXT_SPEED_FAST;
    SetMauvilleOldMan();
    SetMoney(&gSaveBlock1Ptr->money, 123456);
    SetCoins(777);
    gSaveBlock2Ptr->playTimeHours = 52;
    gSaveBlock2Ptr->playTimeMinutes = 34;
    gSaveBlock2Ptr->playTimeSeconds = 10;
    SetLastHealLocationWarp(HEAL_LOCATION_MAUVILLE_CITY);
    // The trainer card's back lists only what is not zero.
    SetGameStat(GAME_STAT_LINK_BATTLE_WINS, 12);
    SetGameStat(GAME_STAT_LINK_BATTLE_LOSSES, 5);
    SetGameStat(GAME_STAT_POKEMON_TRADES, 7);
    SetGameStat(GAME_STAT_WON_LINK_CONTEST, 2);
    SetGameStat(GAME_STAT_POKEBLOCKS_WITH_FRIENDS, 9);
}

void CB2_RigFillSave(void)
{
    StopMapMusic();
    NewGameInitData();
    FillPlayer();
    FillFlags();
    FillParty();
    FillPokedex();
    FillBag();
    switch (gRigFillVariant)
    {
    case 1:
        SetWarpDestination(MAP_GROUP(MAP_MAUVILLE_CITY), MAP_NUM(MAP_MAUVILLE_CITY), WARP_ID_NONE, 8, 14);
        break;
    case 2:
        SetWarpDestination(MAP_GROUP(MAP_SLATEPORT_CITY_NAME_RATERS_HOUSE), MAP_NUM(MAP_SLATEPORT_CITY_NAME_RATERS_HOUSE), WARP_ID_NONE, 7, 6);
        break;
    case 3:
        SetWarpDestination(MAP_GROUP(MAP_LILYCOVE_CITY_CONTEST_LOBBY), MAP_NUM(MAP_LILYCOVE_CITY_CONTEST_LOBBY), WARP_ID_NONE, 14, 4);
        break;
    default:
        SetWarpDestination(MAP_GROUP(MAP_MAUVILLE_CITY_POKEMON_CENTER_1F), MAP_NUM(MAP_MAUVILLE_CITY_POKEMON_CENTER_1F), WARP_ID_NONE, 7, 4);
        break;
    }
    WarpIntoMap();
    ResetInitialPlayerAvatarState();
    PlayTimeCounter_Start();
    gFieldCallback = NULL;
    gFieldCallback2 = NULL;
    SetMainCallback2(CB2_LoadMap);
}
