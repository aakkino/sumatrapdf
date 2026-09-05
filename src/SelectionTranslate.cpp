/* Copyright 2022 the SumatraPDF project authors (see AUTHORS file).
   License: GPLv3 */

#include "base/Base.h"
#include "base/ScopedWin.h"
#include "base/UITask.h"
#include "base/Win.h"
#include "gui/Dpi.h"

#include "gui/UIModels.h"
#include "gui/Layout.h"
#include "gui/win/WinGui.h"
#include "gui/PlatformFont.h"
#include "gui/Gfx.h"
#include "gui/VirtCtrl.h"

#include "Settings.h"
#include "AppSettings.h"
#include "SumatraPDF.h"
#include "SumatraConfig.h"
#include "MainWindow.h"
#include "WindowTab.h"
#include "TextSelection.h"
#include "Selection.h"
#include "SelectionToolbar.h"
#include "TranslationService.h"
#include "TranslationConfig.h"
#include "Translations.h"
#include "Theme.h"
#include "SvgIcons.h"
#include "DarkMode_win.h"
#include "SelectionTranslate.h"

static const Str kSrcLangAuto = StrL("Auto");

// clang-format off
// Parallel LANG_* ids and English names; keep in the same order.
static const WORD gPrimaryLangIds[] = {
    LANG_ENGLISH,
    LANG_CHINESE,
    LANG_GERMAN,
    LANG_FRENCH,
    LANG_SPANISH,
    LANG_ITALIAN,
    LANG_PORTUGUESE,
    LANG_RUSSIAN,
    LANG_JAPANESE,
    LANG_KOREAN,
    LANG_ARABIC,
    LANG_HINDI,
    LANG_TURKISH,
    LANG_VIETNAMESE,
    LANG_POLISH,
    LANG_UKRAINIAN,
    LANG_DUTCH,
    LANG_THAI,
    LANG_INDONESIAN,
    LANG_CZECH,
    LANG_SWEDISH,
    LANG_ROMANIAN,
    LANG_GREEK,
    LANG_HEBREW,
    LANG_DANISH,
    LANG_FINNISH,
    LANG_NORWEGIAN,
    LANG_HUNGARIAN,
    LANG_SLOVAK,
    LANG_BENGALI,
};

static SeqStrings gPrimaryLangNames =
    "English\0"
    "Chinese (Simplified)\0"
    "German\0"
    "French\0"
    "Spanish\0"
    "Italian\0"
    "Portuguese\0"
    "Russian\0"
    "Japanese\0"
    "Korean\0"
    "Arabic\0"
    "Hindi\0"
    "Turkish\0"
    "Vietnamese\0"
    "Polish\0"
    "Ukrainian\0"
    "Dutch\0"
    "Thai\0"
    "Indonesian\0"
    "Czech\0"
    "Swedish\0"
    "Romanian\0"
    "Greek\0"
    "Hebrew\0"
    "Danish\0"
    "Finnish\0"
    "Norwegian\0"
    "Hungarian\0"
    "Slovak\0"
    "Bengali\0";
// clang-format on

static Str PrimaryLangIdToEnglishName(WORD primary) {
    int n = dimofi(gPrimaryLangIds);
    for (int i = 0; i < n; i++) {
        if (gPrimaryLangIds[i] == primary) {
            return SeqStrByIndex(gPrimaryLangNames, i);
        }
    }
    return {};
}

static TempStr OsDefaultDestinationLanguageTemp() {
    LANGID langId = GetUserDefaultUILanguage();
    Str name = PrimaryLangIdToEnglishName(PRIMARYLANGID(langId));
    if (name) {
        return name;
    }
    if (SUBLANGID(langId) == SUBLANG_CHINESE_TRADITIONAL) {
        return StrL("Chinese (Traditional)");
    }
    return StrL("English");
}

static TempStr DefaultDestinationLanguageTemp() {
    if (gSettings && !str::IsEmptyOrWhiteSpace(gSettings->translateToLang)) {
        return gSettings->translateToLang;
    }
    return OsDefaultDestinationLanguageTemp();
}

static TempStr DefaultSourceLanguageTemp() {
    if (gSettings && !str::IsEmptyOrWhiteSpace(gSettings->translateFromLang)) {
        return gSettings->translateFromLang;
    }
    return kSrcLangAuto;
}

static void FreeTranslationSettings(TranslationSettings& settings) {
    str::Free(settings.openAIBaseUrl);
    str::Free(settings.openAIModel);
    str::Free(settings.openAIKey);
    str::Free(settings.googleKey);
    str::Free(settings.microsoftEndpoint);
    str::Free(settings.microsoftKey);
    str::Free(settings.microsoftRegion);
}

static TranslationSettings DupTranslationSettings(const TranslationSettings& settings) {
    TranslationSettings copy;
    copy.provider = settings.provider;
    copy.openAIBaseUrl = str::Dup(settings.openAIBaseUrl);
    copy.openAIModel = str::Dup(settings.openAIModel);
    copy.openAIKey = str::Dup(settings.openAIKey);
    copy.googleKey = str::Dup(settings.googleKey);
    copy.microsoftEndpoint = str::Dup(settings.microsoftEndpoint);
    copy.microsoftKey = str::Dup(settings.microsoftKey);
    copy.microsoftRegion = str::Dup(settings.microsoftRegion);
    return copy;
}

static TranslationSettings SettingsForProvider(TranslationProviderId provider) {
    TranslationSettings settings;
    TranslationSettingsFromGlobal(&settings);
    settings.provider = provider;
    return settings;
}

static void SaveTranslationProvider(TranslationProviderId provider) {
    if (!gSettings) {
        return;
    }
    Str name = TranslationProviderName(provider);
    if (str::EqI(gSettings->translationProvider, name)) {
        return;
    }
    str::ReplacePtr(&gSettings->translationProvider, str::Dup(name));
    ScheduleSaveSettings();
}

enum class SelectionTranslatePopupState {
    Hidden,
    Loading,
    Result,
    Error,
};

enum class PopupShow {
    No,
    Yes,
};

enum class PopupToolbar {
    LeaveHidden,
    Restore,
};

enum class PopupAction {
    None,
    Configure,
    RetryAndConfigure,
};

enum class PopupStart {
    Worker,
    NoWorker,
};

enum class PopupCompletionSource {
    Production,
    Test,
};

struct TranslatePopupIcon : VirtCtrl {
    Size GetIdealSize() override { return {DpiScale(16), DpiScale(16)}; }

    void Paint(VirtPaintCtx& ctx) override {
        Size size = GetIdealSize();
        Pixmap* icon = GetCachedPixmapForSvg(Str(gIconTranslate), size.dx, size.dy);
        if (icon) {
            ctx.gfx->DrawPixmap(icon, {ctx.content.x, ctx.content.y, size.dx, size.dy});
        }
    }

    TranslatePopupIcon() { flags |= vwfNoHitTest; }
};

struct TranslatePopupSpinner : VirtCtrl {
    static constexpr int kFrameCount = 8;
    int frame = 0;

    Size GetIdealSize() override { return {DpiScale(16), DpiScale(16)}; }

    void Paint(VirtPaintCtx& ctx) override {
        static const Point positions[] = {{0, -3}, {2, -2}, {3, 0}, {2, 2}, {0, 3}, {-2, 2}, {-3, 0}, {-2, -2}};
        static_assert(kFrameCount == dimofi(positions));
        constexpr int kAlphaStep = 24;
        int dotSize = std::max(DpiScale(2), 1);
        int step = std::max(DpiScale(2), 1);
        Point center = {ctx.content.x + (ctx.content.dx / 2), ctx.content.y + (ctx.content.dy / 2)};
        Color color = ThemeWindowTextColor();
        for (int i = 0; i < kFrameCount; i++) {
            int age = (i - frame + kFrameCount) % kFrameCount;
            u8 alpha = (u8)(255 - (age * kAlphaStep));
            int x = center.x + positions[i].x * step - (dotSize / 2);
            int y = center.y + positions[i].y * step - (dotSize / 2);
            ctx.gfx->FillEllipse({x, y, dotSize, dotSize}, color, alpha);
        }
    }

    TranslatePopupSpinner() { flags |= vwfNoHitTest; }
};

struct SelectionTranslatePopupWnd : WindowBase {
    MainWindow* win = nullptr;
    WindowTab* tab = nullptr;
    Vec<SelectionOnPage> selection;
    HWND hwndOwner = nullptr;
    TranslationProviderId provider = TranslationProviderId::None;
    Vec<TranslationProviderId> testConfiguredProviders;
    SelectionTranslatePopupState state = SelectionTranslatePopupState::Hidden;
    u64 requestId = 0;
    bool selectionWasCleared = false;
    bool canConfigure = false;
    bool canRetry = false;
    bool closing = false;
    bool registeredOnWindowMoved = false;
    bool loadingTimerActive = false;
    bool roundedCorners = false;
    bool nativeShadow = false;
    PopupCompletionSource completionSource = PopupCompletionSource::Production;
    Size roundedSize;
    Str message;
    Str sourceLang;
    Str destinationLang;
    TranslatePopupIcon* translateIcon = nullptr;
    TranslatePopupSpinner* spinner = nullptr;
    VirtLine* headerDivider = nullptr;
    VirtLine* footerDivider = nullptr;
    HBox* headerRow = nullptr;
    HBox* statusRow = nullptr;
    HBox* buttonsRow = nullptr;
    Padding* headerDividerPad = nullptr;
    Padding* statusPad = nullptr;
    Padding* resultPad = nullptr;
    Padding* footerDividerPad = nullptr;
    Padding* buttonsPad = nullptr;
    Padding* rootPad = nullptr;
    VirtButton* btnProvider = nullptr;
    VirtText* target = nullptr;
    VirtText* status = nullptr;
    Edit* result = nullptr;
    VirtButton* btnCopy = nullptr;
    VirtButton* btnRetry = nullptr;
    VirtButton* btnConfigure = nullptr;
    VirtButton* btnClose = nullptr;
    Func1List<MainWindow*> onWindowMoved;

    ~SelectionTranslatePopupWnd() override;

    bool Create(WindowTab* tab, TranslationProviderId provider, Str sourceLang, Str destinationLang);
    bool ProviderIsConfigured(TranslationProviderId provider) const;
    void ApplyCorners();
    void StartLoadingTimer();
    void StopLoadingTimer();
    void UpdateDpi(int dpi);
    void Relayout();
    void Place(PopupShow show);
    void SetState(SelectionTranslatePopupState state, Str text, PopupAction action);
    void Start(PopupStart start);
    void SwitchProvider(TranslationProviderId provider, PopupStart start);
    void OnDone(bool ok, Str text, PopupCompletionSource source = PopupCompletionSource::Production);
    void OnCopy(VirtMouseEvent*);
    void OnRetry(VirtMouseEvent*);
    void OnProvider(VirtMouseEvent*);
    void OnConfigure(VirtMouseEvent*);
    void OnClose(VirtMouseEvent*);
    void OnDpiChanged(WindowBase::DpiChangedEvent* ev);
    void OnTimer(WindowBase::TimerEvent* ev);
};

struct SelectionTranslatePopupTaskData {
    HWND hwnd = nullptr;
    u64 requestId = 0;
    TranslationSettings settings;
    Str sourceLang;
    Str destinationLang;
    Str text;

    ~SelectionTranslatePopupTaskData() {
        FreeTranslationSettings(settings);
        str::Free(sourceLang);
        str::Free(destinationLang);
        str::Free(text);
    }
};

struct SelectionTranslatePopupDoneData {
    HWND hwnd = nullptr;
    u64 requestId = 0;
    bool ok = false;
    Str text;

    ~SelectionTranslatePopupDoneData() { str::Free(text); }
};

static Vec<SelectionTranslatePopupWnd*> gSelectionTranslatePopups;
static u64 gNextTranslatePopupRequestId = 0;
static int gTranslatePopupToolbarHideCount = 0;
static constexpr UINT kTranslateProviderMenuFirst = 1;
static constexpr UINT kTranslateProviderMenuConfigure = 100;
static constexpr UINT_PTR kTranslateLoadingTimerId = 1;
static constexpr UINT kTranslateLoadingTimerMs = 90;
static const WStr kTranslatePopupClassName = WStrL(L"SUMATRA_SELECTION_TRANSLATE_POPUP");

static const char* TranslatePopupStateName(SelectionTranslatePopupState state) {
    switch (state) {
        case SelectionTranslatePopupState::Loading:
            return "Loading";
        case SelectionTranslatePopupState::Result:
            return "Result";
        case SelectionTranslatePopupState::Error:
            return "Error";
        default:
            return "Hidden";
    }
}

static SelectionTranslatePopupWnd* FindSelectionTranslatePopup(MainWindow* win) {
    for (SelectionTranslatePopupWnd* popup : gSelectionTranslatePopups) {
        if (popup->win == win) {
            return popup;
        }
    }
    return nullptr;
}

static Str TranslatePopupProviderName(TranslationProviderId provider) {
    Str name = TranslationProviderName(provider);
    return name ? name : _TRA("Choose Provider");
}

// A TrackPopupMenu dismissal leaves its button click in the message queue.
static void EatTranslatePopupDismissClick(Rect screenRect) {
    POINT pt;
    GetCursorPos(&pt);
    if (!screenRect.Contains(pt.x, pt.y)) {
        return;
    }
    MSG msg{};
    while (PeekMessageW(&msg, nullptr, WM_LBUTTONDOWN, WM_LBUTTONDOWN, PM_REMOVE)) {
    }
    while (PeekMessageW(&msg, nullptr, WM_LBUTTONUP, WM_LBUTTONUP, PM_REMOVE)) {
    }
}

static bool SameSelection(const Vec<SelectionOnPage>& saved, const Vec<SelectionOnPage>& current) {
    if (len(saved) != len(current)) {
        return false;
    }
    for (int i = 0; i < len(saved); i++) {
        const SelectionOnPage& a = saved[i];
        const SelectionOnPage& b = current[i];
        bool sameQuad =
            a.quad.ul == b.quad.ul && a.quad.ur == b.quad.ur && a.quad.ll == b.quad.ll && a.quad.lr == b.quad.lr;
        if (a.pageNo != b.pageNo || a.rect != b.rect || !sameQuad) {
            return false;
        }
    }
    return true;
}

static bool IsCurrentTranslatePopup(SelectionTranslatePopupWnd* popup) {
    if (!popup || !popup->win || popup->win->CurrentTab() != popup->tab || !popup->tab) {
        return false;
    }
    Vec<SelectionOnPage>* current = popup->tab->selectionOnPage;
    if (!current) {
        popup->selectionWasCleared = true;
        return true;
    }
    return !popup->selectionWasCleared && SameSelection(popup->selection, *current);
}

static void CloseSelectionTranslatePopup(SelectionTranslatePopupWnd* popup, PopupToolbar toolbar) {
    if (!popup || popup->closing) {
        return;
    }
    popup->closing = true;
    popup->requestId = 0;
    popup->StopLoadingTimer();
    VecRemove(gSelectionTranslatePopups, popup);
    if (popup->registeredOnWindowMoved && popup->win) {
        popup->win->UnregisterOnWindowMoved(&popup->onWindowMoved);
        popup->registeredOnWindowMoved = false;
    }
    bool canRestoreToolbar = toolbar == PopupToolbar::Restore && IsCurrentTranslatePopup(popup);
    if (popup->hwnd) {
        ShowWindow(popup->hwnd, SW_HIDE);
    }
    popup->ScheduleDelete();
    if (canRestoreToolbar) {
        ShowSelectionToolbar(popup->win);
    }
}

SelectionTranslatePopupWnd::~SelectionTranslatePopupWnd() {
    StopLoadingTimer();
    if (registeredOnWindowMoved && win) {
        win->UnregisterOnWindowMoved(&onWindowMoved);
    }
    VecRemove(gSelectionTranslatePopups, this);
    str::Free(message);
    str::Free(sourceLang);
    str::Free(destinationLang);
}

static void OnSelectionTranslatePopupClose(WindowBase::CloseEvent* ev) {
    auto* popup = (SelectionTranslatePopupWnd*)ev->e->self;
    CloseSelectionTranslatePopup(popup, PopupToolbar::Restore);
}

static void OnSelectionTranslatePopupDestroy(WindowBase::DestroyEvent* ev) {
    auto* popup = (SelectionTranslatePopupWnd*)ev->e->self;
    CloseSelectionTranslatePopup(popup, PopupToolbar::LeaveHidden);
}

bool SelectionTranslatePopupWnd::ProviderIsConfigured(TranslationProviderId candidate) const {
    if (VecContains(testConfiguredProviders, candidate)) {
        return true;
    }
    TranslationSettings settings = SettingsForProvider(candidate);
    return TranslationProviderIsConfigured(settings);
}

void SelectionTranslatePopupWnd::ApplyCorners() {
    if (!hwnd) {
        return;
    }
    Size size = HwndWindowRect(hwnd).Size();
    if (size == roundedSize) {
        return;
    }
    roundedSize = size;
    int radius = DpiScale(6);
    HRGN region = CreateRoundRectRgn(0, 0, size.dx + 1, size.dy + 1, radius, radius);
    if (!region) {
        roundedCorners = false;
        SetWindowRgn(hwnd, nullptr, TRUE);
        return;
    }
    roundedCorners = SetWindowRgn(hwnd, region, TRUE) != 0;
    if (!roundedCorners) {
        DeleteObject(region);
        SetWindowRgn(hwnd, nullptr, TRUE);
    }
}

void SelectionTranslatePopupWnd::StartLoadingTimer() {
    if (!hwnd || loadingTimerActive) {
        return;
    }
    loadingTimerActive = SetTimer(hwnd, kTranslateLoadingTimerId, kTranslateLoadingTimerMs, nullptr) != 0;
}

void SelectionTranslatePopupWnd::StopLoadingTimer() {
    if (!loadingTimerActive) {
        return;
    }
    if (hwnd) {
        KillTimer(hwnd, kTranslateLoadingTimerId);
    }
    loadingTimerActive = false;
}

static Insets TranslatePopupInsets(int dpi, int top, int right, int bottom, int left) {
    return {DpiScaleByDpi(dpi, top), DpiScaleByDpi(dpi, right), DpiScaleByDpi(dpi, bottom), DpiScaleByDpi(dpi, left)};
}

void SelectionTranslatePopupWnd::UpdateDpi(int dpi) {
    SetFont(GetAppFontForDpi(dpi));
    HwndSetFontForWindowAndItsChildren(hwnd, GetHFont());

    btnProvider->textPadding = TranslatePopupInsets(dpi, 2, 6, 2, 6);
    Insets buttonPadding = TranslatePopupInsets(dpi, 5, 12, 5, 12);
    VirtButton* buttons[] = {btnCopy, btnRetry, btnConfigure, btnClose};
    for (VirtButton* button : buttons) {
        button->textPadding = buttonPadding;
    }
    headerRow->gap = DpiScaleByDpi(dpi, 4);
    statusRow->gap = DpiScaleByDpi(dpi, 6);
    buttonsRow->gap = font->averageCharWidth;
    headerDividerPad->insets = TranslatePopupInsets(dpi, 6, 0, 0, 0);
    statusPad->insets = TranslatePopupInsets(dpi, 8, 0, 0, 0);
    resultPad->insets = TranslatePopupInsets(dpi, 8, 0, 0, 0);
    footerDividerPad->insets = TranslatePopupInsets(dpi, 8, 0, 0, 0);
    buttonsPad->insets = TranslatePopupInsets(dpi, 8, 0, 0, 0);
    rootPad->insets = TranslatePopupInsets(dpi, 12, 12, 12, 12);
    headerDivider->thickness = DpiScaleByDpi(dpi, 1);
    footerDivider->thickness = DpiScaleByDpi(dpi, 1);
    roundedSize = {};

    VirtText* virts[] = {btnProvider, target, status, btnCopy, btnRetry, btnConfigure, btnClose};
    for (VirtText* virt : virts) {
        virt->font = font;
    }
}

void SelectionTranslatePopupWnd::Relayout() {
    if (!layout) {
        return;
    }
    LayoutAndSizeToContent(layout, 0, 0, hwnd);
    DoLayout(HwndClientRect(hwnd).Size());
    ApplyCorners();
}

void SelectionTranslatePopupWnd::Place(PopupShow show) {
    if (!hwnd || !win || !IsCurrentTranslatePopup(this)) {
        return;
    }
    Rect selectionBounds;
    if (!GetVisibleSelectionBounds(win, selectionBounds)) {
        if (!tab->selectionOnPage) {
            return;
        }
        ShowWindow(hwnd, SW_HIDE);
        return;
    }

    Point selectionTop = HwndClientToScreen(win->hwndCanvas, selectionBounds.TL());
    Point selectionBottom = HwndClientToScreen(win->hwndCanvas, selectionBounds.BR());
    Rect work = GetWorkAreaRect(Rect(selectionTop.x, selectionTop.y, 1, 1), nullptr);
    Rect window = HwndWindowRect(hwnd);
    window.dx = std::min(window.dx, work.dx);
    window.dy = std::min(window.dy, work.dy);
    int gap = DpiScale(8);
    int x = selectionTop.x + (selectionBounds.dx / 2) - (window.dx / 2);
    int y = selectionTop.y - gap - window.dy;
    Rect placed{x, y, window.dx, window.dy};
    if (y < work.y) {
        placed.y = selectionBottom.y + gap;
    }
    placed = ShiftRectToWorkArea(placed, nullptr, true);
    uint flags = SWP_NOACTIVATE | SWP_NOZORDER;
    if (show == PopupShow::Yes || !HwndIsVisible(hwnd)) {
        flags |= SWP_SHOWWINDOW;
    }
    SetWindowPos(hwnd, HWND_TOP, placed.x, placed.y, placed.dx, placed.dy, flags);
    DoLayout(HwndClientRect(hwnd).Size());
    ApplyCorners();
}

void SelectionTranslatePopupWnd::SetState(SelectionTranslatePopupState newState, Str text, PopupAction action) {
    state = newState;
    canConfigure = action != PopupAction::None;
    canRetry = action == PopupAction::RetryAndConfigure;
    str::ReplaceWithCopy(&message, text);

    if (spinner) {
        spinner->SetVisibility(state == SelectionTranslatePopupState::Loading ? Visibility::Visible
                                                                              : Visibility::Collapse);
    }
    if (state == SelectionTranslatePopupState::Loading) {
        StartLoadingTimer();
    } else {
        StopLoadingTimer();
    }

    if (btnProvider) {
        btnProvider->SetText(TranslatePopupProviderName(provider));
    }
    if (target) {
        target->SetText(fmt("-> %s", destinationLang));
    }
    if (status) {
        if (state == SelectionTranslatePopupState::Loading) {
            status->SetText(_TRA("Translating..."));
        } else if (state == SelectionTranslatePopupState::Error) {
            status->SetText(message);
        } else {
            status->SetText({});
        }
        status->SetVisibility(state == SelectionTranslatePopupState::Result ? Visibility::Collapse
                                                                            : Visibility::Visible);
    }
    if (result) {
        result->SetText(state == SelectionTranslatePopupState::Result ? message : Str{});
        result->SetVisibility(state == SelectionTranslatePopupState::Result ? Visibility::Visible
                                                                            : Visibility::Collapse);
    }
    if (btnCopy) {
        btnCopy->SetVisibility(state == SelectionTranslatePopupState::Result ? Visibility::Visible
                                                                             : Visibility::Collapse);
    }
    if (btnRetry) {
        btnRetry->SetVisibility(canRetry ? Visibility::Visible : Visibility::Collapse);
    }
    if (btnConfigure) {
        btnConfigure->SetVisibility(canConfigure ? Visibility::Visible : Visibility::Collapse);
    }
    Relayout();
    UpdateTheme();
    Place(PopupShow::Yes);
}

void SelectionTranslatePopupWnd::OnCopy(VirtMouseEvent*) {
    if (state == SelectionTranslatePopupState::Result) {
        CopyTextToClipboard(message);
    }
}

void SelectionTranslatePopupWnd::OnRetry(VirtMouseEvent*) {
    Start(PopupStart::Worker);
}

void SelectionTranslatePopupWnd::OnProvider(VirtMouseEvent*) {
    if (!btnProvider || !hwnd) {
        return;
    }

    HMENU menu = CreatePopupMenu();
    if (!menu) {
        return;
    }

    const TranslationProviderInfo* providers = TranslationProviders();
    for (int i = 0; i < kTranslationProviderCount; i++) {
        const TranslationProviderInfo& candidate = providers[i];
        bool configured = ProviderIsConfigured(candidate.id);
        UINT flags = MF_STRING;
        if (!configured) {
            flags |= MF_GRAYED;
        }
        if (candidate.id == provider) {
            flags |= MF_CHECKED;
        }
        TempStr label =
            configured ? str::DupTemp(candidate.name) : fmt("%s - %s", candidate.name, _TRA("Not configured"));
        AppendMenuW(menu, flags, kTranslateProviderMenuFirst + (UINT)i, CWStrTemp(label));
    }
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, kTranslateProviderMenuConfigure, CWStrTemp(_TRA("Configure...")));

    Rect button = btnProvider->BoundsInWindow();
    Point origin = HwndClientToScreen(hwnd, Point());
    Rect buttonScreen{origin.x + button.x, origin.y + button.y, button.dx, button.dy};
    Point screen{buttonScreen.x, buttonScreen.y + buttonScreen.dy};
    MainWindow* popupWin = win;
    UINT cmd = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY | TPM_LEFTALIGN, screen.x, screen.y, 0, hwnd, nullptr);
    DestroyMenu(menu);
    EatTranslatePopupDismissClick(buttonScreen);

    SelectionTranslatePopupWnd* popup = FindSelectionTranslatePopup(popupWin);
    if (popup != this) {
        return;
    }
    if (cmd >= kTranslateProviderMenuFirst && cmd < kTranslateProviderMenuFirst + (UINT)kTranslationProviderCount) {
        int index = (int)(cmd - kTranslateProviderMenuFirst);
        popup->SwitchProvider(providers[index].id, PopupStart::Worker);
        return;
    }
    if (cmd == kTranslateProviderMenuConfigure) {
        popup->OnConfigure(nullptr);
    }
}

void SelectionTranslatePopupWnd::OnConfigure(VirtMouseEvent*) {
    CloseSelectionTranslatePopup(this, PopupToolbar::LeaveHidden);
    ShowTranslationConfig();
}

void SelectionTranslatePopupWnd::OnClose(VirtMouseEvent*) {
    CloseSelectionTranslatePopup(this, PopupToolbar::Restore);
}

void SelectionTranslatePopupWnd::OnDpiChanged(WindowBase::DpiChangedEvent* ev) {
    if (!layout) {
        ev->didHandle = true;
        return;
    }
    UpdateDpi((int)ev->dpiX);
    Relayout();
    Place(PopupShow::Yes);
    ev->didHandle = true;
}

void SelectionTranslatePopupWnd::OnTimer(WindowBase::TimerEvent* ev) {
    if (ev->timerId != kTranslateLoadingTimerId || state != SelectionTranslatePopupState::Loading || !spinner) {
        return;
    }
    spinner->frame = (spinner->frame + 1) % TranslatePopupSpinner::kFrameCount;
    spinner->Invalidate();
}

bool SelectionTranslatePopupWnd::Create(WindowTab* selectedTab, TranslationProviderId selectedProvider, Str srcLang,
                                        Str dstLang) {
    if (!selectedTab || !selectedTab->win || !selectedTab->selectionOnPage) {
        return false;
    }
    win = selectedTab->win;
    tab = selectedTab;
    selection = *selectedTab->selectionOnPage;
    hwndOwner = win->hwndFrame;
    provider = selectedProvider;
    sourceLang = str::Dup(srcLang);
    destinationLang = str::Dup(dstLang);
    SetFont(GetAppFont());
    bool isRtl = IsUIRtl();
    closeOnEsc = true;
    onClose = MkFunc1Void<WindowBase::CloseEvent*>(OnSelectionTranslatePopupClose);
    onDestroy = MkFunc1Void<WindowBase::DestroyEvent*>(OnSelectionTranslatePopupDestroy);
    onDpiChanged =
        MkMethod1<SelectionTranslatePopupWnd, WindowBase::DpiChangedEvent*, &SelectionTranslatePopupWnd::OnDpiChanged>(
            this);
    onTimer =
        MkMethod1<SelectionTranslatePopupWnd, WindowBase::TimerEvent*, &SelectionTranslatePopupWnd::OnTimer>(this);

    CreateCustomArgs args;
    args.owner = hwndOwner;
    args.className = kTranslatePopupClassName;
    args.title = _TRA("Translate");
    args.visible = false;
    args.style = WS_POPUP | WS_BORDER | WS_CLIPCHILDREN;
    args.exStyle = WS_EX_TOOLWINDOW;
    args.font = font;
    args.pos = Rect(0, 0, DpiScale(360), DpiScale(180));
    args.isRtl = isRtl;
    CreateCustom(args);
    if (!hwnd) {
        return false;
    }
    LONG_PTR classStyle = GetClassLongPtrW(hwnd, GCL_STYLE);
    // The native shadow exists only with this private popup class and degrades to no shadow.
    SetClassLongPtrW(hwnd, GCL_STYLE, classStyle | CS_DROPSHADOW);
    nativeShadow = (GetClassLongPtrW(hwnd, GCL_STYLE) & CS_DROPSHADOW) != 0;

    auto* vbox = new VBox();
    vbox->alignMain = MainAxisAlign::MainStart;
    vbox->alignCross = CrossAxisAlign::Stretch;

    headerRow = new HBox();
    headerRow->alignCross = CrossAxisAlign::CrossCenter;
    headerRow->rtl = isRtl;
    translateIcon = new TranslatePopupIcon();
    headerRow->AddChild(translateIcon);
    btnProvider = NewThemedButton(hwnd, TranslatePopupProviderName(provider), font, false);
    btnProvider->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnProvider>(this);
    headerRow->AddChild(btnProvider);
    target = NewVirtText({.s = fmt("-> %s", destinationLang), .font = font, .isRtl = isRtl, .ellipsis = true});
    headerRow->AddChild(target);
    vbox->AddChild(headerRow);

    headerDivider = new VirtLine();
    headerDividerPad = new Padding(headerDivider, Insets{});
    vbox->AddChild(headerDividerPad);

    statusRow = new HBox();
    statusRow->alignCross = CrossAxisAlign::CrossCenter;
    statusRow->rtl = isRtl;
    spinner = new TranslatePopupSpinner();
    statusRow->AddChild(spinner);
    status = NewVirtText({.font = font, .isRtl = isRtl});
    statusRow->AddChild(status, 1);
    statusPad = new Padding(statusRow, Insets{});
    vbox->AddChild(statusPad);

    Edit::CreateArgs resultArgs;
    resultArgs.parent = hwnd;
    resultArgs.font = GetFont();
    resultArgs.isMultiLine = true;
    resultArgs.withBorder = true;
    resultArgs.idealSizeLines = 8;
    resultArgs.idealWidthChars = 42;
    resultArgs.maxWidthChars = 52;
    resultArgs.isRtl = isRtl;
    result = new Edit();
    result->Create(resultArgs);
    SendMessageW(result->hwnd, EM_SETREADONLY, TRUE, 0);
    resultPad = new Padding(result, Insets{});
    vbox->AddChild(resultPad, 1);

    footerDivider = new VirtLine();
    footerDividerPad = new Padding(footerDivider, Insets{});
    vbox->AddChild(footerDividerPad);

    buttonsRow = new HBox();
    buttonsRow->alignMain = MainAxisAlign::MainEnd;
    buttonsRow->alignCross = CrossAxisAlign::CrossCenter;
    buttonsRow->rtl = isRtl;
    btnCopy = NewThemedButton(hwnd, _TRA("Copy"), font, false);
    btnCopy->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnCopy>(this);
    buttonsRow->AddChild(btnCopy);
    btnRetry = NewThemedButton(hwnd, _TRA("Retry"), font, true);
    btnRetry->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnRetry>(this);
    buttonsRow->AddChild(btnRetry);
    btnConfigure = NewThemedButton(hwnd, _TRA("Configure"), font, false);
    btnConfigure->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnConfigure>(this);
    buttonsRow->AddChild(btnConfigure);
    btnClose = NewThemedButton(hwnd, _TRA("Close"), font, false);
    btnClose->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnClose>(this);
    buttonsRow->AddChild(btnClose);
    buttonsPad = new Padding(buttonsRow, Insets{});
    vbox->AddChild(buttonsPad);

    rootPad = new Padding(vbox, Insets{});
    layout = rootPad;
    UpdateDpi(GetDpi());
    Relayout();
    UpdateTheme();
    onWindowMoved = MkFunc1Void(RepositionTranslatePopup);
    win->RegisterOnWindowMoved(&onWindowMoved);
    registeredOnWindowMoved = true;
    return true;
}

static void OnSelectionTranslatePopupDone(SelectionTranslatePopupDoneData* done) {
    AutoDelete del(done);
    for (SelectionTranslatePopupWnd* popup : gSelectionTranslatePopups) {
        if (popup->hwnd != done->hwnd || popup->requestId != done->requestId || !IsCurrentTranslatePopup(popup)) {
            continue;
        }
        popup->OnDone(done->ok, done->text);
        return;
    }
}

static void SelectionTranslatePopupThread(SelectionTranslatePopupTaskData* data) {
    AutoDelete del(data);
    TranslationRequest request{data->sourceLang, data->destinationLang, data->text};
    TranslationResult result;
    TranslateText(data->settings, request, &result);

    auto* done = new SelectionTranslatePopupDoneData();
    done->hwnd = data->hwnd;
    done->requestId = data->requestId;
    done->ok = result.ok;
    done->text = str::Dup(result.ok ? result.text : result.error);
    uitask::Post(MkFunc0(OnSelectionTranslatePopupDone, done), "SelectionTranslatePopupDone");
}

void SelectionTranslatePopupWnd::Start(PopupStart start) {
    if (!HasPermission(Perm::InternetAccess)) {
        CloseSelectionTranslatePopup(this, PopupToolbar::Restore);
        return;
    }
    if (!IsCurrentTranslatePopup(this) || !HasPermission(Perm::CopySelection)) {
        CloseSelectionTranslatePopup(this, PopupToolbar::LeaveHidden);
        return;
    }
    bool isTextOnly = false;
    TempStr text = GetSelectedTextTemp(tab, StrL("\n"), isTextOnly);
    if (str::IsEmptyOrWhiteSpace(text)) {
        CloseSelectionTranslatePopup(this, PopupToolbar::LeaveHidden);
        return;
    }

    requestId = ++gNextTranslatePopupRequestId;
    SetState(SelectionTranslatePopupState::Loading, {}, PopupAction::None);
    if (start == PopupStart::NoWorker) {
        return;
    }

    TranslationSettings settings = SettingsForProvider(provider);
    if (!TranslationProviderIsConfigured(settings)) {
        SetState(SelectionTranslatePopupState::Error, TranslationConfigErrorTemp(settings), PopupAction::Configure);
        return;
    }

    auto* task = new SelectionTranslatePopupTaskData();
    task->hwnd = hwnd;
    task->requestId = requestId;
    task->settings = DupTranslationSettings(settings);
    task->sourceLang = str::Dup(sourceLang);
    task->destinationLang = str::Dup(destinationLang);
    task->text = str::Dup(text);
    RunAsync(MkFunc0(SelectionTranslatePopupThread, task), StrL("SelectionTranslatePopup"));
}

void SelectionTranslatePopupWnd::SwitchProvider(TranslationProviderId newProvider, PopupStart start) {
    if (!HasPermission(Perm::InternetAccess)) {
        CloseSelectionTranslatePopup(this, PopupToolbar::Restore);
        return;
    }
    if (newProvider == TranslationProviderId::None || newProvider == provider) {
        return;
    }
    if (!IsCurrentTranslatePopup(this) || !HasPermission(Perm::CopySelection)) {
        CloseSelectionTranslatePopup(this, PopupToolbar::LeaveHidden);
        return;
    }
    if (!ProviderIsConfigured(newProvider)) {
        return;
    }
    bool isTextOnly = false;
    TempStr text = GetSelectedTextTemp(tab, StrL("\n"), isTextOnly);
    if (str::IsEmptyOrWhiteSpace(text)) {
        CloseSelectionTranslatePopup(this, PopupToolbar::LeaveHidden);
        return;
    }

    provider = newProvider;
    SaveTranslationProvider(provider);
    Start(start);
}

void SelectionTranslatePopupWnd::OnDone(bool ok, Str text, PopupCompletionSource source) {
    completionSource = source;
    Str display = text;
    if (!ok && str::IsEmptyOrWhiteSpace(display)) {
        display = _TRA("Translation failed.");
    }
    SetState(ok ? SelectionTranslatePopupState::Result : SelectionTranslatePopupState::Error, display,
             ok ? PopupAction::None : PopupAction::RetryAndConfigure);
}

void ShowSelectionTranslatePopup(WindowTab* tab) {
    if (!tab || !tab->win || !tab->selectionOnPage || !HasPermission(Perm::CopySelection) ||
        !HasPermission(Perm::InternetAccess)) {
        return;
    }
    if (FindSelectionTranslatePopup(tab->win)) {
        return;
    }
    bool isTextOnly = false;
    TempStr text = GetSelectedTextTemp(tab, StrL("\n"), isTextOnly);
    if (str::IsEmptyOrWhiteSpace(text)) {
        return;
    }

    TempStr sourceLang = DefaultSourceLanguageTemp();
    TempStr destinationLang = DefaultDestinationLanguageTemp();
    TranslationSettings settings;
    TranslationSettingsFromGlobal(&settings);
    auto* popup = new SelectionTranslatePopupWnd();
    if (!popup->Create(tab, settings.provider, sourceLang, destinationLang)) {
        delete popup;
        return;
    }
    VecAppend(gSelectionTranslatePopups, popup);
    gTranslatePopupToolbarHideCount++;
    HideSelectionToolbar(tab->win);
    if (!TranslationProviderIsConfigured(settings)) {
        popup->SetState(SelectionTranslatePopupState::Error, TranslationConfigErrorTemp(settings),
                        PopupAction::Configure);
        return;
    }
    popup->Start(PopupStart::Worker);
}

bool HasSelectionTranslatePopup(MainWindow* win) {
    return FindSelectionTranslatePopup(win) != nullptr;
}

void UpdateSelectionTranslatePopup(MainWindow* win) {
    SelectionTranslatePopupWnd* popup = FindSelectionTranslatePopup(win);
    if (!popup) {
        return;
    }
    if (!IsCurrentTranslatePopup(popup)) {
        CloseSelectionTranslatePopup(popup, PopupToolbar::LeaveHidden);
        return;
    }
    popup->Place(PopupShow::No);
}

void RepositionTranslatePopup(MainWindow* win) {
    SelectionTranslatePopupWnd* popup = FindSelectionTranslatePopup(win);
    if (popup && IsCurrentTranslatePopup(popup)) {
        popup->Place(PopupShow::No);
    }
}

void OnTranslateSelectionChanged(MainWindow* win) {
    SelectionTranslatePopupWnd* popup = FindSelectionTranslatePopup(win);
    WindowTab* tab = win ? win->CurrentTab() : nullptr;
    if (popup && tab && tab->selectionOnPage) {
        CloseSelectionTranslatePopup(popup, PopupToolbar::LeaveHidden);
    }
}

void CloseTranslatePopupForTab(WindowTab* tab) {
    for (int i = len(gSelectionTranslatePopups) - 1; i >= 0; i--) {
        SelectionTranslatePopupWnd* popup = gSelectionTranslatePopups[i];
        if (popup->tab == tab) {
            CloseSelectionTranslatePopup(popup, PopupToolbar::LeaveHidden);
        }
    }
}

static void AppendProviderStatus(str::Builder& out, SelectionTranslatePopupWnd* popup) {
    const TranslationProviderInfo* providers = TranslationProviders();
    out.Append(StrL("providers="));
    for (int i = 0; i < kTranslationProviderCount; i++) {
        if (i > 0) {
            out.AppendChar(',');
        }
        out.Append(providers[i].name);
        out.Append(popup->ProviderIsConfigured(providers[i].id) ? StrL(":configured") : StrL(":not-configured"));
    }
    out.AppendChar('\n');
}

TempStr SelectionTranslatePopupTestTemp(Str action, Str value, int* exitCode) {
    auto finish = [exitCode](Str text, int code) -> TempStr {
        if (exitCode) {
            *exitCode = code;
        }
        return str::DupTemp(text);
    };
    MainWindow* win = len(gWindows) > 0 ? gWindows[0] : nullptr;
    SelectionTranslatePopupWnd* popup = FindSelectionTranslatePopup(win);
    if (str::EqI(action, StrL("dump"))) {
        if (!popup) {
            Str persisted = gSettings ? gSettings->translationProvider : Str{};
            return finish(fmt("state=Hidden\nvisible=0\nrequest=0\npersisted=%s\ntoolbarHides=%d\n", persisted,
                              gTranslatePopupToolbarHideCount),
                          0);
        }
        str::Builder out;
        Rect rect = popup->hwnd ? HwndWindowRect(popup->hwnd) : Rect();
        out.Append(fmt("state=%s\nvisible=%d\nconfigure=%d\nretry=%d\ncopy=%d\nplaced=%d,%d,%d,%d\n",
                       Str(TranslatePopupStateName(popup->state)), HwndIsVisible(popup->hwnd) ? 1 : 0,
                       popup->canConfigure ? 1 : 0, popup->canRetry ? 1 : 0,
                       popup->state == SelectionTranslatePopupState::Result ? 1 : 0, rect.x, rect.y, rect.dx, rect.dy));
        Str persisted = gSettings ? gSettings->translationProvider : Str{};
        out.Append(fmt("switcher=%d\nprovider=%s\ntarget=%s\npersisted=%s\nrequest=%llu\n", popup->btnProvider ? 1 : 0,
                       TranslatePopupProviderName(popup->provider), popup->destinationLang, persisted,
                       popup->requestId));
        out.Append(fmt("toolbarHides=%d\n", gTranslatePopupToolbarHideCount));
        out.Append(fmt("polish=rounded:%d,shadow:%d,icon:%d,dividers:%d\nloadingTimer=%d\n",
                       popup->roundedCorners ? 1 : 0, popup->nativeShadow ? 1 : 0, popup->translateIcon ? 1 : 0,
                       (popup->headerDivider ? 1 : 0) + (popup->footerDivider ? 1 : 0),
                       popup->loadingTimerActive ? 1 : 0));
        AppendProviderStatus(out, popup);
        if (popup->state == SelectionTranslatePopupState::Result) {
            out.Append(fmt("resultLength=%d\n", len(popup->message)));
        }
        if (popup->state == SelectionTranslatePopupState::Result &&
            popup->completionSource == PopupCompletionSource::Test) {
            out.Append(fmt("result=%s\n", popup->message));
        }
        return finish(ToStr(out), 0);
    }
    if (str::EqI(action, StrL("close"))) {
        if (popup) {
            CloseSelectionTranslatePopup(popup, PopupToolbar::Restore);
        }
        return SelectionTranslatePopupTestTemp(StrL("dump"), {}, exitCode);
    }
    if (!win || !win->CurrentTab() || !win->CurrentTab()->selectionOnPage) {
        return finish(StrL("ERROR no-selection"), 1);
    }
    if (str::EqI(action, StrL("start")) || str::EqI(action, StrL("start-worker")) ||
        str::EqI(action, StrL("prepare"))) {
        if (popup) {
            CloseSelectionTranslatePopup(popup, PopupToolbar::LeaveHidden);
        }
        auto* testPopup = new SelectionTranslatePopupWnd();
        if (!testPopup->Create(win->CurrentTab(), TranslationProviderId::OpenAICompatible, StrL("Auto"),
                               StrL("English"))) {
            delete testPopup;
            return finish(StrL("ERROR create"), 1);
        }
        VecAppend(testPopup->testConfiguredProviders, TranslationProviderId::OpenAICompatible);
        VecAppend(testPopup->testConfiguredProviders, TranslationProviderId::Microsoft);
        VecAppend(gSelectionTranslatePopups, testPopup);
        if (!str::EqI(action, StrL("prepare"))) {
            PopupStart start = str::EqI(action, StrL("start-worker")) ? PopupStart::Worker : PopupStart::NoWorker;
            testPopup->Start(start);
            if (FindSelectionTranslatePopup(win) == testPopup) {
                HideSelectionToolbar(win);
            }
        }
        return SelectionTranslatePopupTestTemp(StrL("dump"), {}, exitCode);
    }
    if (!popup) {
        return finish(StrL("ERROR no-popup"), 1);
    }
    if (str::EqI(action, StrL("result"))) {
        popup->OnDone(true, value, PopupCompletionSource::Test);
    } else if (str::EqI(action, StrL("worker-result"))) {
        auto* done = new SelectionTranslatePopupDoneData();
        done->hwnd = popup->hwnd;
        done->requestId = popup->requestId;
        done->ok = true;
        done->text = str::Dup(value);
        OnSelectionTranslatePopupDone(done);
    } else if (str::EqI(action, StrL("error"))) {
        popup->OnDone(false, value, PopupCompletionSource::Test);
    } else if (str::EqI(action, StrL("stale"))) {
        auto* done = new SelectionTranslatePopupDoneData();
        done->hwnd = popup->hwnd;
        done->requestId = popup->requestId - 1;
        done->ok = true;
        done->text = str::Dup(value);
        OnSelectionTranslatePopupDone(done);
    } else if (str::EqI(action, StrL("retry")) || str::EqI(action, StrL("retry-worker"))) {
        PopupStart start = str::EqI(action, StrL("retry-worker")) ? PopupStart::Worker : PopupStart::NoWorker;
        popup->Start(start);
    } else if (str::EqI(action, StrL("switch")) || str::EqI(action, StrL("switch-worker"))) {
        TranslationProviderId provider = TranslationProviderFromName(value);
        if (provider == TranslationProviderId::None) {
            return finish(StrL("ERROR invalid-provider"), 1);
        }
        PopupStart start = str::EqI(action, StrL("switch-worker")) ? PopupStart::Worker : PopupStart::NoWorker;
        popup->SwitchProvider(provider, start);
    } else if (str::EqI(action, StrL("configure"))) {
        popup->OnConfigure(nullptr);
        return SelectionTranslatePopupTestTemp(StrL("dump"), {}, exitCode);
    } else {
        return finish(StrL("ERROR unknown-action"), 1);
    }
    return SelectionTranslatePopupTestTemp(StrL("dump"), {}, exitCode);
}
