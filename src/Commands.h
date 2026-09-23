/* Copyright 2022 the SumatraPDF project authors (see AUTHORS file).
   License: Simplified BSD (see COPYING.BSD) */

// @gen-start cmd-enum
// clang-format off
enum {
    // commands are integers sent with WM_COMMAND so start them
    // at some number higher than 0
    CmdFirst = 200,
    CmdSeparator = CmdFirst,

    CmdOpenFile = 201,
    CmdClose = 202,
    CmdCloseCurrentDocument = 203,
    CmdCloseOtherTabs = 204,
    CmdCloseTabsToTheRight = 205,
    CmdCloseTabsToTheLeft = 206,
    CmdCloseAllTabs = 207,
    CmdSaveAs = 208,
    CmdPrint = 209,
    CmdShowInFolder = 210,
    CmdRenameFile = 211,
    CmdDeleteFile = 212,
    CmdExit = 213,
    CmdReloadDocument = 214,
    CmdCreateShortcutToFile = 215,
    CmdSendByEmail = 216,
    CmdProperties = 217,
    CmdSinglePageView = 218,
    CmdFacingView = 219,
    CmdBookView = 220,
    CmdToggleContinuousView = 221,
    CmdToggleMangaMode = 222,
    CmdRotateLeft = 223,
    CmdRotateRight = 224,
    CmdToggleBookmarks = 225,
    CmdToggleTableOfContents = 226,
    CmdToggleFullscreen = 227,
    CmdPresentationWhiteBackground = 228,
    CmdPresentationBlackBackground = 229,
    CmdTogglePresentationMode = 230,
    CmdToggleToolbar = 231,
    CmdChangeScrollbar = 232,
    CmdToggleMenuBar = 233,
    CmdCopySelection = 234,
    CmdSearchSelectionWithGoogle = 235,
    CmdSearchSelectionWithBing = 236,
    CmdSearchSelectionWithWikipedia = 237,
    CmdSearchSelectionWithGoogleScholar = 238,
    CmdSelectAll = 239,
    CmdNewWindow = 240,
    CmdDuplicateInNewWindow = 241,
    CmdDuplicateInNewTab = 242,
    CmdCopyImage = 243,
    CmdCopyLinkTarget = 244,
    CmdCopyComment = 245,
    CmdCopyFilePath = 246,
    CmdScrollUp = 247,
    CmdScrollDown = 248,
    CmdScrollLeft = 249,
    CmdScrollRight = 250,
    CmdScrollLeftPage = 251,
    CmdScrollRightPage = 252,
    CmdScrollUpPage = 253,
    CmdScrollDownPage = 254,
    CmdScrollDownHalfPage = 255,
    CmdScrollUpHalfPage = 256,
    CmdGoToNextPage = 257,
    CmdGoToPrevPage = 258,
    CmdGoToFirstPage = 259,
    CmdGoToLastPage = 260,
    CmdGoToPage = 261,
    CmdFindFirst = 262,
    CmdFindNext = 263,
    CmdFindPrev = 264,
    CmdFindNextSel = 265,
    CmdFindPrevSel = 266,
    CmdFindToggleMatchCase = 267,
    CmdSaveAnnotations = 268,
    CmdSaveAnnotationsNewFile = 269,
    CmdDiscardChanges = 270,
    CmdDeleteAnnotation = 271,
    CmdZoomFitPage = 272,
    CmdZoomActualSize = 273,
    CmdZoomFitWidth = 274,
    CmdZoomFitByOrientation = 275,
    CmdZoom6400 = 276,
    CmdZoom3200 = 277,
    CmdZoom1600 = 278,
    CmdZoom800 = 279,
    CmdZoom400 = 280,
    CmdZoom200 = 281,
    CmdZoom150 = 282,
    CmdZoom125 = 283,
    CmdZoom100 = 284,
    CmdZoom50 = 285,
    CmdZoom25 = 286,
    CmdZoom12_5 = 287,
    CmdZoom8_33 = 288,
    CmdZoomFitContent = 289,
    CmdZoomShrinkToFit = 290,
    CmdZoomCustom = 291,
    CmdZoomIn = 292,
    CmdZoomOut = 293,
    CmdZoomFitWidthAndContinuous = 294,
    CmdZoomFitPageAndSinglePage = 295,
    CmdContributeTranslation = 296,
    CmdOpenWithKnownExternalViewerFirst = 297,
    CmdOpenWithExplorer = 298,
    CmdOpenWithDirectoryOpus = 299,
    CmdOpenWithTotalCommander = 300,
    CmdOpenWithDoubleCommander = 301,
    CmdOpenWithAcrobat = 302,
    CmdOpenWithFoxIt = 303,
    CmdOpenWithFoxItPhantom = 304,
    CmdOpenWithPdfXchange = 305,
    CmdOpenWithXpsViewer = 306,
    CmdOpenWithHtmlHelp = 307,
    CmdOpenWithPdfDjvuBookmarker = 308,
    CmdOpenWithKnownExternalViewerLast = 309,
    CmdOpenSelectedDocument = 310,
    CmdPinSelectedDocument = 311,
    CmdForgetSelectedDocument = 312,
    CmdExpandAll = 313,
    CmdCollapseAll = 314,
    CmdSaveEmbeddedFile = 315,
    CmdOpenEmbeddedPDF = 316,
    CmdSaveAttachment = 317,
    CmdOpenAttachment = 318,
    CmdOptions = 319,
    CmdAdvancedOptions = 320,
    CmdAdvancedSettings = 321,
    CmdChangeLanguage = 322,
    CmdCheckUpdate = 323,
    CmdInstallPrereleaseUpdate = 324,
    CmdTogglePdfPreviewLogging = 325,
    CmdHelpOpenManual = 326,
    CmdHelpOpenManualOnWebsite = 327,
    CmdHelpOpenKeyboardShortcuts = 328,
    CmdToggleKeyboardHelp = 329,
    CmdHelpVisitWebsite = 330,
    CmdHelpAbout = 331,
    CmdMoveFrameFocus = 332,
    CmdFavoriteAdd = 333,
    CmdFavoriteDel = 334,
    CmdFavoriteToggle = 335,
    CmdToggleLinks = 336,
    CmdToggleShowAnnotations = 337,
    CmdShowAnnotations = 338,
    CmdHideAnnotations = 339,
    CmdCreateAnnotText = 340,
    CmdCreateAnnotLink = 341,
    CmdCreateAnnotFreeText = 342,
    CmdCreateAnnotLine = 343,
    CmdCreateAnnotSquare = 344,
    CmdCreateAnnotCircle = 345,
    CmdCreateAnnotPolygon = 346,
    CmdCreateAnnotPolyLine = 347,
    CmdCreateAnnotHighlight = 348,
    CmdCreateAnnotUnderline = 349,
    CmdCreateAnnotSquiggly = 350,
    CmdCreateAnnotStrikeOut = 351,
    CmdCreateAnnotRedact = 352,
    CmdCreateAnnotStamp = 353,
    CmdCreateAnnotCaret = 354,
    CmdCreateAnnotInk = 355,
    CmdCreateAnnotPopup = 356,
    CmdCreateAnnotFileAttachment = 357,
    CmdInvertColors = 358,
    CmdTogglePageInfo = 359,
    CmdToggleZoom = 360,
    CmdNavigateBack = 361,
    CmdNavigateForward = 362,
    CmdToggleCursorPosition = 363,
    CmdOpenNextFileInFolder = 364,
    CmdOpenPrevFileInFolder = 365,
    CmdCommandPalette = 366,
    CmdShowLog = 367,
    CmdShowErrors = 368,
    CmdClearHistory = 369,
    CmdReopenLastClosedFile = 370,
    CmdNextTab = 371,
    CmdPrevTab = 372,
    CmdNextTabSmart = 373,
    CmdPrevTabSmart = 374,
    CmdMoveTabLeft = 375,
    CmdMoveTabRight = 376,
    CmdInvokeInverseSearch = 377,
    CmdExec = 378,
    CmdViewWithExternalViewer = 379,
    CmdSelectionHandler = 380,
    CmdSetTheme = 381,
    CmdToggleInverseSearch = 382,
    CmdDebugCorruptMemory = 383,
    CmdDebugCrashMe = 384,
    CmdDebugDownloadSymbols = 385,
    CmdDebugTestApp = 386,
    CmdDebugShowNotif = 387,
    CmdDebugStartStressTest = 388,
    CmdDebugTogglePredictiveRender = 389,
    CmdDebugToggleRtl = 390,
    CmdListPrinters = 391,
    CmdToggleWindowsPreviewer = 392,
    CmdToggleWindowsSearchFilter = 393,
    CmdScreenshot = 394,
    CmdCropImage = 395,
    CmdResizeImage = 396,
    CmdSaveImage = 397,
    CmdPasteClipboardImage = 398,
    CmdTabGroupSave = 399,
    CmdTabGroupRestore = 400,
    CmdChangeBackgroundColor = 401,
    CmdChangeEbookSettings = 402,
    CmdSetTabColor = 403,
    CmdPdfCompress = 404,
    CmdPdfDecompress = 405,
    CmdPdfDeletePages = 406,
    CmdPdfExtractPages = 407,
    CmdPdfEncrypt = 408,
    CmdPdfDecrypt = 409,
    CmdPdfBake = 410,
    CmdPdShowInfo = 411,
    CmdDocumentExtractText = 412,
    CmdDocumentShowOutline = 413,
    CmdSetScreenshotHotkey = 414,
    CmdReadAloud = 415,
    CmdPauseReadAloud = 416,
    CmdContinueReadAloud = 417,
    CmdStopReadAloud = 418,
    CmdReadAloudFromTopPage = 419,
    CmdReadAloudSelection = 420,
    CmdToggleToolbarShowReadAloud = 421,
    CmdRemoveDeletedFilesFromHistory = 422,
    CmdCommandPaletteTOC = 423,
    CmdDebugToggleRenderInfo = 424,
    CmdConvertImageToPdf = 425,
    CmdExpandToCurrentPage = 426,
    CmdStartAutoScroll = 427,
    CmdAIChatWithClaudeCode = 428,
    CmdAIChatWithGrokBuild = 429,
    CmdAIChatWithOpenAICodex = 430,
    CmdFindToggleMatchWholeWord = 431,
    CmdGoToNextFavorite = 432,
    CmdGoToPrevFavorite = 433,
    CmdCreateAnnotImageFromClipboard = 434,
    CmdSetInverseSearch = 435,
    CmdCommandPaletteFavorites = 436,
    CmdNavigateFilesInFolder = 437,
    CmdDebugToggleCacheInfo = 438,
    CmdToggleEngineeringDrawingEnhance = 439,
    CmdSetDocumentColorsFollowTheme = 440,
    CmdTogglePreservePdfImages = 441,
    CmdToggleLightDarkTheme = 442,
    CmdChangeTheme = 443,
    CmdTranslateSelection = 444,
    CmdFavoriteShowInTab = 445,
    CmdTocExpandToLevel1 = 446,
    CmdTocExpandToLevel2 = 447,
    CmdTocExpandToLevel3 = 448,
    CmdTocCollapseSameLevel = 449,
    CmdToggleFavoritesSort = 450,
    CmdZoomFitHeight = 451,
    CmdDeleteFileAndOpenNext = 452,
    CmdShowGeneratedHTML = 453,
    CmdDeleteCachedFiles = 454,
    CmdToggleKeyboardLinkFollowing = 455,
    CmdDebugToggleDpiOverride = 456,
    CmdToggleImages = 457,
    CmdSelectTextViaKeyboard = 458,
    CmdOpenFileWithOSFilePicker = 459,
    CmdToggleFilePicker = 460,
    CmdToggleBoolSetting = 461,
    CmdFixDefaultApp = 462,
    CmdAIChatWithAntiGravity = 463,
    CmdConvertToPDF = 464,
    CmdDebugShowFitContentArea = 465,
    CmdExtendSelectionCharLeft = 466,
    CmdExtendSelectionCharRight = 467,
    CmdExtendSelectionWordLeft = 468,
    CmdExtendSelectionWordRight = 469,
    CmdToggleLaserPointer = 470,
    CmdZoomToSelection = 471,
    CmdToggleHoverPreview = 472,
    CmdToggleDisableLinks = 473,
    CmdSignDocument = 474,
    CmdInsertImage = 475,
    CmdToggleHighlightFormFields = 476,
    CmdTogglePageBoxes = 477,
    CmdConvertPdfToImages = 478,
    CmdToggleUniformPageWidth = 479,
    CmdToggleTransparencyGrid = 480,
    CmdTogglePageGrid = 481,
    CmdConfigurePageGrid = 482,
    CmdToggleEditPDF = 483,
    CmdApplyRedactions = 484,
    CmdUndo = 485,
    CmdRedo = 486,
    CmdCutAnnotation = 487,
    CmdCopyAnnotation = 488,
    CmdPasteAnnotation = 489,
    CmdSearchGoogleLens = 490,
    CmdNavigateThumbnail = 491,
    CmdShowAnnotationText = 492,
    CmdAnnotationHighlightBrush = 493,
    CmdFindAnnotation = 494,
    CmdOpenFileNoHistory = 495,
    CmdTranslateSelectionQuick = 496,
    CmdConfigureTranslation = 497,
    CmdNone = 498,

    /* range for file history */
    CmdFileHistoryFirst,
    CmdFileHistoryLast = CmdFileHistoryFirst + 32,

    /* range for favorites */
    CmdFavoriteFirst,
    CmdFavoriteLast = CmdFavoriteFirst + 256,

    CmdLast = CmdFavoriteLast,
    CmdFirstCustom = CmdLast + 100,

    // aliases, at the end to not mess ordering
    CmdViewLayoutFirst = CmdSinglePageView,
    CmdViewLayoutLast = CmdToggleMangaMode,

    CmdZoomFirst = CmdZoomFitPage,
    CmdZoomLast = CmdZoomCustom,

    CmdCreateAnnotFirst = CmdCreateAnnotText,
    CmdCreateAnnotLast = CmdCreateAnnotFileAttachment,
};
// clang-format on
// @gen-end cmd-enum

// order of CreateAnnot* must be the same as enum AnnotationType
/*
TOOD: maybe add commands for those annotations
Sound,
Movie,
Widget,
Screen,
PrinterMark,
TrapNet,
Watermark,
ThreeD,
*/

struct CommandArg {
    enum class Type : u16 {
        None,
        Bool,
        Int,
        Float,
        String,
        Color,
    };

    // arguments are a linked list for simplicity
    struct CommandArg* next = nullptr;

    Type type = Type::None;

    // TODO: we have a fixed number of argument names
    // we could use SeqStrings and use u16 for arg name id
    Str name;

    // TODO: could be a union
    Str strVal;
    bool boolVal = false;
    int intVal = 0;
    float floatVal = 0.0;
    ParsedColor colorVal;
};

CommandArg* AllocCommandArg(Str name, Str strVal);
void FreeCommandArgs(CommandArg* first);

struct CustomCommand {
    // all commands are stored as linked list
    struct CustomCommand* next = nullptr;

    // the command id like CmdOpenFile
    int origId = 0;

    // for debugging, the full definition of the command
    // as given by the user
    Str definition;

    // optional name, if given this shows up in command palette
    Str name;

    // optional keyboard shortcut
    Str key;

    // a unique command id generated by us, starting with CmdFirstCustom
    // it identifies a command with their fixed set of arguments
    int id = 0;

    CommandArg* firstArg = nullptr;
};

CustomCommand* AllocCustomCommand(Str definition, Str name, Str key);
void FreeCustomCommand(CustomCommand* cmd);

extern CustomCommand* gFirstCustomCommand;
extern SeqStrings gCommandDescriptions;

int GetCommandIdByName(Str);
int GetCommandIdByDesc(Str);
Str GetCommandDescription(int commandId);

CustomCommand* CreateCustomCommand(Str definition, int origCmdId, CommandArg* args, Str name = {}, Str key = {});
CustomCommand* CloneCustomCommand(CustomCommand* cmd, Str name = {}, Str key = {});
CustomCommand* FindCustomCommand(int cmdId);
void FreeCustomCommands();
CommandArg* NewStringArg(Str name, Str val);
CommandArg* NewFloatArg(Str name, float val);
void InsertArg(CommandArg** firstPtr, CommandArg* arg);

CustomCommand* CreateCommandFromDefinition(Str definition);
CommandArg* GetCommandArg(CustomCommand*, Str argName);
int GetCommandIntArg(CustomCommand* cmd, Str name, int defValue);
bool GetCommandBoolArg(CustomCommand* cmd, Str name, bool defValue);
Str GetCommandStringArg(CustomCommand* cmd, Str name, Str defValue);
void GetCommandsWithOrigId(Vec<CustomCommand*>& commands, int origId);

#define kCmdArgColor StrL("color")
#define kCmdArgBgColor StrL("bgcolor")
#define kCmdArgOpacity StrL("opacity")
#define kCmdArgOpenEdit StrL("openedit")
#define kCmdArgTextSize StrL("textsize")
#define kCmdArgBorderWidth StrL("borderwidth")
#define kCmdArgAlignment StrL("alignment")
#define kCmdArgInteriorColor StrL("interiorcolor")

#define kCmdArgCopyToClipboard StrL("copytoclipboard")
#define kCmdArgSetContent StrL("setcontent")
#define kCmdArgExe StrL("exe")
#define kCmdArgURL StrL("url")
// SelectionHandlers: how and what to send (see Customize-search-translation-services.md)
#define kCmdArgMethod StrL("method")
#define kCmdArgBody StrL("body")
#define kCmdArgContentType StrL("contenttype")
#define kCmdArgHeaders StrL("headers")
#define kCmdArgLevel StrL("level")
#define kCmdArgFilter StrL("filter")
#define kCmdArgN StrL("n")
#define kCmdArgMode StrL("mode")
#define kCmdArgTheme StrL("theme")
#define kCmdArgCommandLine StrL("cmdline")
#define kCmdArgToolbarText StrL("toolbartext")
#define kCmdArgToolbarSvgIcon StrL("toolbarsvgicon")
// text (or, when it starts with "<svg", an icon) for a button on the toolbar
// that pops up over a text selection
#define kCmdArgSelectToolbar StrL("selecttoolbar")
#define kCmdArgFocusEdit StrL("focusedit")
#define kCmdArgFocusList StrL("focuslist")
// optional bool to force a state on a toggle command instead of flipping it (#5067)
#define kCmdArgState StrL("state")
#define kCmdArgName StrL("name")
#define kCmdArgExt StrL("ext")
