/* Copyright 2026 the SumatraPDF project authors (see AUTHORS file).
   License: GPLv3 */

#include "base/Base.h"
#include "base/UITask.h"
#include "base/Win.h"
#include "gui/Dpi.h"

#include "gui/UIModels.h"
#include "gui/Layout.h"
#include "gui/Layout_win.h"
#include "gui/win/WinGui.h"
#include "gui/PlatformFont.h"
#include "gui/Gfx.h"
#include "gui/VirtCtrl.h"

#include "Settings.h"
#include "AppSettings.h"
#include "MainWindow.h"
#include "SumatraConfig.h"
#include "SumatraPDF.h"
#include "Theme.h"
#include "Translations.h"
#include "TranslationService.h"
#include "TranslationConfig.h"

enum class ConfigTestStart {
    Worker,
    NoWorker,
};

enum class ConfigEditKind {
    Text,
    Key,
};

enum class ConfigWorking {
    No,
    Yes,
};

enum class ConfigTestResult {
    Failure,
    Success,
};

enum class ConfigSelectionKind {
    Provider,
    Language,
};

enum class AutoLanguage {
    Exclude,
    Include,
};

constexpr int kConfigEditWidthChars = 36;
constexpr int kConfigColumnGap = 8;
constexpr int kConfigRowGap = 6;
constexpr int kConfigProviderGap = 16;
constexpr int kConfigRootGap = 8;
constexpr int kConfigRootPadding = 12;
constexpr int kConfigHeadingBottomPadding = 6;
constexpr int kConfigButtonVerticalPadding = 5;
constexpr int kConfigButtonHorizontalPadding = 12;

struct TranslationConfigWnd : WindowBase {
    DropDown* dropProvider = nullptr;
    DropDown* dropSource = nullptr;
    DropDown* dropTarget = nullptr;
    Edit* editOpenAIBaseUrl = nullptr;
    Edit* editOpenAIModel = nullptr;
    Edit* editOpenAIKey = nullptr;
    Edit* editGoogleKey = nullptr;
    Edit* editMicrosoftEndpoint = nullptr;
    Edit* editMicrosoftRegion = nullptr;
    Edit* editMicrosoftKey = nullptr;
    Table* openAITable = nullptr;
    Table* googleTable = nullptr;
    Table* microsoftTable = nullptr;
    Table* languagesTable = nullptr;
    ILayout* openAIGroup = nullptr;
    ILayout* googleGroup = nullptr;
    VirtText* googleHeading = nullptr;
    VirtText* googleKeyLabel = nullptr;
    ILayout* microsoftGroup = nullptr;
    HBox* providerRow = nullptr;
    HBox* buttons = nullptr;
    VBox* rootBox = nullptr;
    Padding* rootPadding = nullptr;
    VirtText* storageWarning = nullptr;
    VirtText* costWarning = nullptr;
    VirtText* status = nullptr;
    VirtButton* btnTest = nullptr;
    VirtButton* btnCancel = nullptr;
    VirtButton* btnSave = nullptr;
    bool working = false;
    int requestId = 0;
    int fontDpi = 0;
    Vec<VirtText*> rowLabels;
    Vec<VirtText*> headings;

    bool Create(HWND owner);
    Edit* NewEdit(Str text, ConfigEditKind kind = ConfigEditKind::Text);
    DropDown* NewDropDown();
    VirtText* NewRowLabel(Str text);
    VirtText* NewHeading(Str text);
    ILayout* NewProviderGroup(TranslationProviderId provider);
    void LoadSettings();
    void ProviderChanged();
    void InputChanged();
    TranslationProviderId Provider() const;
    TranslationSettings SettingsTemp() const;
    TempStr SourceLanguageTemp() const;
    TempStr TargetLanguageTemp() const;
    TempStr ValidateTemp() const;
    void SetStatus(Str text);
    void UpdateState();
    void SetWorking(ConfigWorking value);
    void StartTest(ConfigTestStart start = ConfigTestStart::Worker);
    void OnTestClicked(VirtMouseEvent* ev = nullptr);
    void OnTestDone(int finishedRequestId, ConfigTestResult result);
    void Save(VirtMouseEvent* ev = nullptr);
    void Cancel(VirtMouseEvent* ev = nullptr);
    void Relayout();
    void UpdateDpi(int dpi);
    void OnDpiChanged(WindowBase::DpiChangedEvent* ev);
    void OnGetMinMaxInfo(WindowBase::GetMinMaxInfoEvent* ev);
};

static TranslationConfigWnd* gTranslationConfigWnd = nullptr;
static int gNextTranslationConfigRequestId = 0;

struct TranslationConfigTask {
    HWND hwnd = nullptr;
    int requestId = 0;
    TranslationSettings settings;
    TranslationRequest request;

    ~TranslationConfigTask() {
        str::Free(settings.openAIBaseUrl);
        str::Free(settings.openAIModel);
        str::Free(settings.openAIKey);
        str::Free(settings.googleKey);
        str::Free(settings.microsoftEndpoint);
        str::Free(settings.microsoftKey);
        str::Free(settings.microsoftRegion);
        str::Free(request.sourceLanguage);
        str::Free(request.targetLanguage);
        str::Free(request.text);
    }
};

struct TranslationConfigDone {
    HWND hwnd = nullptr;
    int requestId = 0;
    bool ok = false;
};

static void AddConfigRow(Table* table, int row, VirtText* label, ILayout* control, bool isRtl) {
    int labelColumn = isRtl ? 1 : 0;
    int controlColumn = isRtl ? 0 : 1;
    auto& labelCell = table->SetCell(row, labelColumn, label);
    labelCell.alignH = CrossAxisAlign::Stretch;
    labelCell.alignV = CrossAxisAlign::CrossCenter;
    auto& controlCell = table->SetCell(row, controlColumn, control);
    controlCell.alignH = CrossAxisAlign::Stretch;
    controlCell.alignV = CrossAxisAlign::CrossCenter;
}

static int ProviderIndex(TranslationProviderId provider) {
    const TranslationProviderInfo* providers = TranslationProviders();
    for (int i = 0; i < kTranslationProviderCount; i++) {
        if (providers[i].id == provider) {
            return i;
        }
    }
    return 0;
}

static int LanguageIndex(Str language, AutoLanguage autoLanguage) {
    bool includeAuto = autoLanguage == AutoLanguage::Include;
    if (includeAuto && TranslationSourceIsAuto(language)) {
        return 0;
    }
    for (int i = 0;; i++) {
        Str label = TranslationLanguageLabel(i);
        if (!label) {
            break;
        }
        if (str::EqI(label, language)) {
            return i + (includeAuto ? 1 : 0);
        }
    }
    return -1;
}

Edit* TranslationConfigWnd::NewEdit(Str text, ConfigEditKind kind) {
    Edit::CreateArgs args;
    args.parent = hwnd;
    args.font = GetFont();
    args.text = text;
    args.withBorder = true;
    args.isPassword = kind == ConfigEditKind::Key;
    args.isRtl = IsUIRtl();
    args.idealWidthChars = kConfigEditWidthChars;
    auto* edit = new Edit();
    edit->Create(args);
    edit->onTextChanged = MkMethod0<TranslationConfigWnd, &TranslationConfigWnd::InputChanged>(this);
    return edit;
}

DropDown* TranslationConfigWnd::NewDropDown() {
    DropDown::CreateArgs args;
    args.parent = hwnd;
    args.font = GetFont();
    args.isRtl = IsUIRtl();
    auto* drop = new DropDown();
    drop->Create(args);
    return drop;
}

VirtText* TranslationConfigWnd::NewRowLabel(Str text) {
    int gap = DpiScale(kConfigColumnGap);
    Insets padding = IsUIRtl() ? Insets{0, 0, 0, gap} : Insets{0, gap, 0, 0};
    auto* label = NewVirtText({.s = text, .font = font, .isRtl = IsUIRtl(), .padding = padding});
    VecAppend(rowLabels, label);
    return label;
}

VirtText* TranslationConfigWnd::NewHeading(Str text) {
    auto* heading = NewVirtText({.s = text,
                                 .font = font,
                                 .isRtl = IsUIRtl(),
                                 .padding = DpiScaledInsets(0, 0, kConfigHeadingBottomPadding, 0)});
    VecAppend(headings, heading);
    return heading;
}

ILayout* TranslationConfigWnd::NewProviderGroup(TranslationProviderId provider) {
    bool isRtl = IsUIRtl();
    auto* table = new Table();
    const TranslationProviderInfo* info = TranslationProviders();
    int rows = provider == TranslationProviderId::OpenAICompatible ? 3
               : provider == TranslationProviderId::Microsoft      ? 3
                                                                   : 1;
    table->SetSize(rows, 2);
    table->colGap = DpiScale(kConfigColumnGap);
    table->rowGap = DpiScale(kConfigRowGap);

    if (provider == TranslationProviderId::OpenAICompatible) {
        openAITable = table;
        editOpenAIBaseUrl = NewEdit({});
        editOpenAIModel = NewEdit({});
        editOpenAIKey = NewEdit({}, ConfigEditKind::Key);
        AddConfigRow(table, 0, NewRowLabel(_TRA("Base URL:")), editOpenAIBaseUrl, isRtl);
        AddConfigRow(table, 1, NewRowLabel(_TRA("Model:")), editOpenAIModel, isRtl);
        AddConfigRow(table, 2, NewRowLabel(_TRA("API Key:")), editOpenAIKey, isRtl);
    } else if (provider == TranslationProviderId::GoogleCloud) {
        googleTable = table;
        editGoogleKey = NewEdit({}, ConfigEditKind::Key);
        googleKeyLabel = NewRowLabel(_TRA("API Key:"));
        AddConfigRow(table, 0, googleKeyLabel, editGoogleKey, isRtl);
    } else {
        microsoftTable = table;
        editMicrosoftEndpoint = NewEdit({});
        editMicrosoftRegion = NewEdit({});
        editMicrosoftKey = NewEdit({}, ConfigEditKind::Key);
        AddConfigRow(table, 0, NewRowLabel(_TRA("Endpoint:")), editMicrosoftEndpoint, isRtl);
        AddConfigRow(table, 1, NewRowLabel(_TRA("Region:")), editMicrosoftRegion, isRtl);
        AddConfigRow(table, 2, NewRowLabel(_TRA("API Key:")), editMicrosoftKey, isRtl);
    }

    auto* box = new VBox();
    box->alignCross = CrossAxisAlign::Stretch;
    auto* heading = NewHeading(info[ProviderIndex(provider)].name);
    if (provider == TranslationProviderId::GoogleCloud) {
        googleHeading = heading;
    }
    box->AddChild(heading);
    box->AddChild(table);
    return box;
}

TranslationProviderId TranslationConfigWnd::Provider() const {
    int idx = dropProvider ? CbGetCurrentSelection(dropProvider) : -1;
    if (idx < 0 || idx >= kTranslationProviderCount) {
        return TranslationProviderId::None;
    }
    return TranslationProviders()[idx].id;
}

TranslationSettings TranslationConfigWnd::SettingsTemp() const {
    TranslationSettings settings;
    settings.provider = Provider();
    settings.openAIBaseUrl = editOpenAIBaseUrl ? editOpenAIBaseUrl->GetTextTemp() : Str{};
    settings.openAIModel = editOpenAIModel ? editOpenAIModel->GetTextTemp() : Str{};
    settings.openAIKey = editOpenAIKey ? editOpenAIKey->GetTextTemp() : Str{};
    settings.googleKey = editGoogleKey ? editGoogleKey->GetTextTemp() : Str{};
    settings.microsoftEndpoint = editMicrosoftEndpoint ? editMicrosoftEndpoint->GetTextTemp() : Str{};
    settings.microsoftRegion = editMicrosoftRegion ? editMicrosoftRegion->GetTextTemp() : Str{};
    settings.microsoftKey = editMicrosoftKey ? editMicrosoftKey->GetTextTemp() : Str{};
    return settings;
}

TempStr TranslationConfigWnd::SourceLanguageTemp() const {
    int idx = dropSource ? CbGetCurrentSelection(dropSource) : -1;
    if (idx == 0) {
        return str::DupTemp(StrL("Auto"));
    }
    return idx > 0 ? str::DupTemp(TranslationLanguageLabel(idx - 1)) : TempStr{};
}

TempStr TranslationConfigWnd::TargetLanguageTemp() const {
    int idx = dropTarget ? CbGetCurrentSelection(dropTarget) : -1;
    return idx >= 0 ? str::DupTemp(TranslationLanguageLabel(idx)) : TempStr{};
}

TempStr TranslationConfigWnd::ValidateTemp() const {
    TranslationSettings settings = SettingsTemp();
    TempStr error = TranslationConfigErrorTemp(settings);
    if (error) {
        return str::DupTemp(error);
    }
    if (!SourceLanguageTemp()) {
        return str::DupTemp(StrL("Choose a source language."));
    }
    if (!TargetLanguageTemp()) {
        return str::DupTemp(StrL("Choose a target language."));
    }
    return {};
}

void TranslationConfigWnd::SetStatus(Str text) {
    if (!status) {
        return;
    }
    status->SetText(text);
    status->Invalidate();
    Relayout();
}

void TranslationConfigWnd::SetWorking(ConfigWorking value) {
    working = value == ConfigWorking::Yes;
    ControlBase* controls[] = {dropProvider,        dropSource,      dropTarget,    editOpenAIBaseUrl,
                               editOpenAIModel,     editOpenAIKey,   editGoogleKey, editMicrosoftEndpoint,
                               editMicrosoftRegion, editMicrosoftKey};
    for (ControlBase* control : controls) {
        if (control) {
            control->SetIsEnabled(!working);
        }
    }
    if (btnTest) {
        btnTest->SetIsEnabled(!working && HasPermission(Perm::InternetAccess));
    }
    if (btnSave) {
        btnSave->SetIsEnabled(!working);
    }
}

void TranslationConfigWnd::UpdateState() {
    TempStr error = ValidateTemp();
    bool valid = !error;
    if (btnTest) {
        btnTest->SetIsEnabled(valid && !working && HasPermission(Perm::InternetAccess));
    }
    if (btnSave) {
        btnSave->SetIsEnabled(valid && !working);
    }
    if (!working) {
        SetStatus(error);
    }
}

void TranslationConfigWnd::ProviderChanged() {
    TranslationProviderId provider = Provider();
    Visibility openAIVisibility =
        provider == TranslationProviderId::OpenAICompatible ? Visibility::Visible : Visibility::Collapse;
    bool isGoogleProvider = provider == TranslationProviderId::GoogleCloud ||
                            provider == TranslationProviderId::Google || provider == TranslationProviderId::GoogleAPI;
    Visibility googleVisibility = isGoogleProvider ? Visibility::Visible : Visibility::Collapse;
    Visibility googleKeyVisibility =
        provider == TranslationProviderId::GoogleCloud ? Visibility::Visible : Visibility::Collapse;
    Visibility microsoftVisibility =
        provider == TranslationProviderId::Microsoft ? Visibility::Visible : Visibility::Collapse;
    openAIGroup->SetVisibility(openAIVisibility);
    editOpenAIBaseUrl->SetVisibility(openAIVisibility);
    editOpenAIModel->SetVisibility(openAIVisibility);
    editOpenAIKey->SetVisibility(openAIVisibility);
    googleGroup->SetVisibility(googleVisibility);
    googleKeyLabel->SetVisibility(googleKeyVisibility);
    editGoogleKey->SetVisibility(googleKeyVisibility);
    if (googleHeading) {
        TranslationProviderId headingProvider = isGoogleProvider ? provider : TranslationProviderId::GoogleCloud;
        googleHeading->SetText(TranslationProviderName(headingProvider));
    }
    microsoftGroup->SetVisibility(microsoftVisibility);
    editMicrosoftEndpoint->SetVisibility(microsoftVisibility);
    editMicrosoftRegion->SetVisibility(microsoftVisibility);
    editMicrosoftKey->SetVisibility(microsoftVisibility);
    Relayout();
    InputChanged();
}

void TranslationConfigWnd::InputChanged() {
    if (working) {
        return;
    }
    UpdateState();
}

void TranslationConfigWnd::LoadSettings() {
    TranslationSettings settings;
    TranslationSettingsFromGlobal(&settings);
    CbSetCurrentSelection(dropProvider, ProviderIndex(settings.provider));
    editOpenAIBaseUrl->SetText(settings.openAIBaseUrl);
    editOpenAIModel->SetText(settings.openAIModel);
    editOpenAIKey->SetText(settings.openAIKey);
    editGoogleKey->SetText(settings.googleKey);
    editMicrosoftEndpoint->SetText(settings.microsoftEndpoint);
    editMicrosoftRegion->SetText(settings.microsoftRegion);
    editMicrosoftKey->SetText(settings.microsoftKey);

    Str source = gSettings ? gSettings->translateFromLang : Str{};
    Str target = gSettings ? gSettings->translateToLang : Str{};
    int sourceIdx = LanguageIndex(source, AutoLanguage::Include);
    int targetIdx = LanguageIndex(target, AutoLanguage::Exclude);
    CbSetCurrentSelection(dropSource, sourceIdx >= 0 ? sourceIdx : 0);
    CbSetCurrentSelection(dropTarget,
                          targetIdx >= 0 ? targetIdx : LanguageIndex(StrL("English"), AutoLanguage::Exclude));
    ProviderChanged();
}

static void OnTranslationConfigDone(TranslationConfigDone* done) {
    AutoDelete del(done);
    TranslationConfigWnd* wnd = gTranslationConfigWnd;
    if (!wnd || wnd->deleteScheduled || !IsWindow(wnd->hwnd) || wnd->hwnd != done->hwnd) {
        return;
    }
    wnd->OnTestDone(done->requestId, done->ok ? ConfigTestResult::Success : ConfigTestResult::Failure);
}

static void TranslationConfigThread(TranslationConfigTask* task) {
    AutoDelete del(task);
    TranslationResult result;
    TranslateText(task->settings, task->request, &result);
    auto* done = new TranslationConfigDone{task->hwnd, task->requestId, result.ok};
    uitask::Post(MkFunc0(OnTranslationConfigDone, done), "TranslationConfigDone");
}

void TranslationConfigWnd::StartTest(ConfigTestStart start) {
    if (!HasPermission(Perm::InternetAccess)) {
        return;
    }
    TempStr error = ValidateTemp();
    if (working || error) {
        if (error) {
            SetStatus(error);
        }
        return;
    }

    requestId = ++gNextTranslationConfigRequestId;
    SetWorking(ConfigWorking::Yes);
    SetStatus(_TRA("Testing connection..."));
    if (start == ConfigTestStart::NoWorker) {
        return;
    }

    TranslationSettings settings = SettingsTemp();
    auto* task = new TranslationConfigTask();
    task->hwnd = hwnd;
    task->requestId = requestId;
    task->settings.provider = settings.provider;
    task->settings.openAIBaseUrl = str::Dup(settings.openAIBaseUrl);
    task->settings.openAIModel = str::Dup(settings.openAIModel);
    task->settings.openAIKey = str::Dup(settings.openAIKey);
    task->settings.googleKey = str::Dup(settings.googleKey);
    task->settings.microsoftEndpoint = str::Dup(settings.microsoftEndpoint);
    task->settings.microsoftRegion = str::Dup(settings.microsoftRegion);
    task->settings.microsoftKey = str::Dup(settings.microsoftKey);
    task->request.sourceLanguage = str::Dup(SourceLanguageTemp());
    task->request.targetLanguage = str::Dup(TargetLanguageTemp());
    task->request.text = str::Dup(StrL("Hello."));
    RunAsync(MkFunc0(TranslationConfigThread, task), StrL("TranslationConfigTest"));
}

void TranslationConfigWnd::OnTestClicked(VirtMouseEvent*) {
    StartTest();
}

void TranslationConfigWnd::OnTestDone(int finishedRequestId, ConfigTestResult result) {
    if (!working || finishedRequestId != requestId) {
        return;
    }
    SetWorking(ConfigWorking::No);
    SetStatus(result == ConfigTestResult::Success ? _TRA("Connection succeeded.") : _TRA("Connection failed."));
    TempStr error = ValidateTemp();
    bool valid = !error;
    btnTest->SetIsEnabled(valid && HasPermission(Perm::InternetAccess));
    btnSave->SetIsEnabled(valid);
}

void TranslationConfigWnd::Save(VirtMouseEvent*) {
    TempStr error = ValidateTemp();
    if (working || error || !gSettings) {
        if (error) {
            SetStatus(error);
        }
        return;
    }

    TranslationSettings settings = SettingsTemp();
    str::ReplaceWithCopy(&gSettings->translationProvider, TranslationProviderName(settings.provider));
    str::ReplaceWithCopy(&gSettings->translationOpenAIBaseUrl, settings.openAIBaseUrl);
    str::ReplaceWithCopy(&gSettings->translationOpenAIModel, settings.openAIModel);
    str::ReplaceWithCopy(&gSettings->translationOpenAIKey, settings.openAIKey);
    str::ReplaceWithCopy(&gSettings->translationGoogleKey, settings.googleKey);
    str::ReplaceWithCopy(&gSettings->translationMicrosoftEndpoint, settings.microsoftEndpoint);
    str::ReplaceWithCopy(&gSettings->translationMicrosoftRegion, settings.microsoftRegion);
    str::ReplaceWithCopy(&gSettings->translationMicrosoftKey, settings.microsoftKey);
    str::ReplaceWithCopy(&gSettings->translateFromLang, SourceLanguageTemp());
    str::ReplaceWithCopy(&gSettings->translateToLang, TargetLanguageTemp());
    if (HasPermission(Perm::SavePreferences)) {
        SaveSettings();
    }
    ScheduleDelete();
}

void TranslationConfigWnd::Cancel(VirtMouseEvent*) {
    ScheduleDelete();
}

void TranslationConfigWnd::Relayout() {
    if (!layout || !hwnd) {
        return;
    }
    Rect client = HwndClientRect(hwnd);
    LayoutAndSizeToContent(layout, client.dx, client.dy, hwnd);
    DoLayout(HwndClientRect(hwnd).Size());
}

void TranslationConfigWnd::UpdateDpi(int dpi) {
    PlatformFont* appFont = GetAppFontForDpi(dpi);
    fontDpi = dpi;
    SetFont(appFont);
    HwndSetFontForWindowAndItsChildren(hwnd, GetHFont());

    Edit* edits[] = {editOpenAIBaseUrl,     editOpenAIModel,     editOpenAIKey,   editGoogleKey,
                     editMicrosoftEndpoint, editMicrosoftRegion, editMicrosoftKey};
    for (Edit* edit : edits) {
        edit->SetIdealWidthChars(kConfigEditWidthChars);
    }

    int columnGap = DpiScaleByDpi(dpi, kConfigColumnGap);
    int rowGap = DpiScaleByDpi(dpi, kConfigRowGap);
    Table* tables[] = {openAITable, googleTable, microsoftTable, languagesTable};
    for (Table* table : tables) {
        table->colGap = columnGap;
        table->rowGap = rowGap;
    }
    int labelLeft = IsUIRtl() ? columnGap : 0;
    int labelRight = IsUIRtl() ? 0 : columnGap;
    for (VirtText* label : rowLabels) {
        label->font = appFont;
        label->padding = Insets{0, labelRight, 0, labelLeft};
    }
    for (VirtText* heading : headings) {
        heading->font = appFont;
        heading->padding = Insets{0, 0, DpiScaleByDpi(dpi, kConfigHeadingBottomPadding), 0};
    }

    providerRow->gap = DpiScaleByDpi(dpi, kConfigProviderGap);
    rootBox->gap = DpiScaleByDpi(dpi, kConfigRootGap);
    int padding = DpiScaleByDpi(dpi, kConfigRootPadding);
    rootPadding->insets = Insets{padding, padding, padding, padding};
    buttons->gap = appFont->averageCharWidth;
    Insets buttonPadding{
        DpiScaleByDpi(dpi, kConfigButtonVerticalPadding), DpiScaleByDpi(dpi, kConfigButtonHorizontalPadding),
        DpiScaleByDpi(dpi, kConfigButtonVerticalPadding), DpiScaleByDpi(dpi, kConfigButtonHorizontalPadding)};
    VirtButton* configButtons[] = {btnTest, btnCancel, btnSave};
    for (VirtButton* button : configButtons) {
        button->textPadding = buttonPadding;
    }

    Vec<VirtCtrl*> controls;
    CollectVirtCtrls(layout, controls);
    for (VirtCtrl* control : controls) {
        VirtText* text = AsVirtText(control);
        if (text) {
            text->font = appFont;
        }
    }
}

void TranslationConfigWnd::OnDpiChanged(WindowBase::DpiChangedEvent* ev) {
    if (!layout) {
        ev->didHandle = true;
        return;
    }
    if (ev->suggested) {
        RECT* r = ev->suggested;
        SetWindowPos(hwnd, nullptr, r->left, r->top, r->right - r->left, r->bottom - r->top,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    UpdateDpi((int)ev->dpiX);
    Relayout();
    ev->didHandle = true;
}

void TranslationConfigWnd::OnGetMinMaxInfo(WindowBase::GetMinMaxInfoEvent* ev) {
    if (!layout || !ev->mmi) {
        return;
    }
    int clientDx = std::max(layout->MinIntrinsicWidth(Inf), DpiScale(520));
    int clientDy = std::max(layout->MinIntrinsicHeight(clientDx), DpiScale(300));
    RECT rect{0, 0, clientDx, clientDy};
    DWORD style = (DWORD)GetWindowLongW(hwnd, GWL_STYLE);
    DWORD exStyle = (DWORD)GetWindowLongW(hwnd, GWL_EXSTYLE);
    AdjustWindowRectEx(&rect, style, FALSE, exStyle);
    ev->mmi->ptMinTrackSize.x = rect.right - rect.left;
    ev->mmi->ptMinTrackSize.y = rect.bottom - rect.top;
}

bool TranslationConfigWnd::Create(HWND owner) {
    CreateCustomArgs args;
    args.owner = owner;
    args.title = _TRA("Translation Providers");
    args.visible = false;
    args.style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_CLIPCHILDREN;
    args.font = GetFont();
    args.icon = LoadIconW(GetModuleHandleW(nullptr), MAKEINTRESOURCEW(GetAppIconID()));
    CreateCustom(args);
    if (!hwnd) {
        return false;
    }

    bool isRtl = IsUIRtl();
    dropProvider = NewDropDown();
    {
        StrVec items;
        const TranslationProviderInfo* providers = TranslationProviders();
        for (int i = 0; i < kTranslationProviderCount; i++) {
            items.Append(providers[i].name);
        }
        dropProvider->SetItems(items);
        dropProvider->onSelectionChanged =
            MkMethod0<TranslationConfigWnd, &TranslationConfigWnd::ProviderChanged>(this);
    }

    openAIGroup = NewProviderGroup(TranslationProviderId::OpenAICompatible);
    googleGroup = NewProviderGroup(TranslationProviderId::GoogleCloud);
    microsoftGroup = NewProviderGroup(TranslationProviderId::Microsoft);

    auto* form = new VBox();
    form->alignCross = CrossAxisAlign::Stretch;
    form->AddChild(openAIGroup);
    form->AddChild(googleGroup);
    form->AddChild(microsoftGroup);

    auto* providerColumn = new VBox();
    providerColumn->alignCross = CrossAxisAlign::Stretch;
    providerColumn->AddChild(NewHeading(_TRA("Provider")));
    providerColumn->AddChild(dropProvider);

    providerRow = new HBox();
    providerRow->alignCross = CrossAxisAlign::CrossStart;
    providerRow->rtl = isRtl;
    providerRow->gap = DpiScale(kConfigProviderGap);
    providerRow->AddChild(providerColumn);
    providerRow->AddChild(form, 1);

    dropSource = NewDropDown();
    dropTarget = NewDropDown();
    {
        StrVec sourceItems;
        StrVec targetItems;
        sourceItems.Append(StrL("Auto"));
        for (int i = 0;; i++) {
            Str label = TranslationLanguageLabel(i);
            if (!label) {
                break;
            }
            sourceItems.Append(label);
            targetItems.Append(label);
        }
        dropSource->SetItems(sourceItems);
        dropTarget->SetItems(targetItems);
        dropSource->onSelectionChanged = MkMethod0<TranslationConfigWnd, &TranslationConfigWnd::InputChanged>(this);
        dropTarget->onSelectionChanged = MkMethod0<TranslationConfigWnd, &TranslationConfigWnd::InputChanged>(this);
    }
    languagesTable = new Table();
    languagesTable->SetSize(2, 2);
    languagesTable->colGap = DpiScale(kConfigColumnGap);
    languagesTable->rowGap = DpiScale(kConfigRowGap);
    AddConfigRow(languagesTable, 0, NewRowLabel(_TRA("Source language:")), dropSource, isRtl);
    AddConfigRow(languagesTable, 1, NewRowLabel(_TRA("Target language:")), dropTarget, isRtl);

    rootBox = new VBox();
    rootBox->alignCross = CrossAxisAlign::Stretch;
    rootBox->gap = DpiScale(kConfigRootGap);
    rootBox->AddChild(providerRow, 1);
    rootBox->AddChild(languagesTable);
    storageWarning = NewVirtText({.s = _TRA("API keys are stored in plain text."), .font = font, .isRtl = isRtl});
    rootBox->AddChild(storageWarning);
    rootBox->AddChild(NewVirtText(
        {.s = _TRA("Local files, backups, and sync services may expose them."), .font = font, .isRtl = isRtl}));
    costWarning = NewVirtText({.s = _TRA("Test Connection may incur provider charges."), .font = font, .isRtl = isRtl});
    rootBox->AddChild(costWarning);
    status = NewVirtText({.s = {}, .font = font, .isRtl = isRtl});
    rootBox->AddChild(status);

    buttons = new HBox();
    buttons->alignMain = MainAxisAlign::MainEnd;
    buttons->alignCross = CrossAxisAlign::CrossCenter;
    buttons->rtl = isRtl;
    buttons->gap = font->averageCharWidth;
    btnTest = NewThemedButton(hwnd, _TRA("Test Connection"), font, false);
    btnTest->onClick = MkMethod1<TranslationConfigWnd, VirtMouseEvent*, &TranslationConfigWnd::OnTestClicked>(this);
    buttons->AddChild(btnTest);
    btnCancel = NewThemedButton(hwnd, _TRA("Cancel"), font, false);
    btnCancel->onClick = MkMethod1<TranslationConfigWnd, VirtMouseEvent*, &TranslationConfigWnd::Cancel>(this);
    buttons->AddChild(btnCancel);
    btnSave = NewThemedButton(hwnd, _TRA("Save"), font, true);
    btnSave->onClick = MkMethod1<TranslationConfigWnd, VirtMouseEvent*, &TranslationConfigWnd::Save>(this);
    buttons->AddChild(btnSave);
    rootBox->AddChild(buttons);

    rootPadding = new Padding(rootBox, DpiScaledInsets(kConfigRootPadding));
    layout = rootPadding;
    LoadSettings();
    LayoutAndSizeToContent(layout, DpiScale(620), DpiScale(360), hwnd);
    DoLayout(HwndClientRect(hwnd).Size());
    HwndCenterDialog(hwnd, owner);
    UpdateTheme();
    SetIsVisible(true);
    return true;
}

static void ClearTranslationConfigWnd() {
    gTranslationConfigWnd = nullptr;
}

static void OnTranslationConfigClose(WindowBase::CloseEvent*) {
    if (gTranslationConfigWnd) {
        gTranslationConfigWnd->Cancel();
    }
}

static void OnTranslationConfigDestroy(WindowBase::DestroyEvent*) {
    if (gTranslationConfigWnd) {
        gTranslationConfigWnd->ScheduleDelete();
    }
}

void ShowTranslationConfig() {
    if (gTranslationConfigWnd) {
        HwndToForeground(gTranslationConfigWnd->hwnd);
        gTranslationConfigWnd->SetFocusTo(gTranslationConfigWnd->dropProvider);
        return;
    }

    HWND owner = len(gWindows) > 0 ? gWindows[0]->hwndFrame : nullptr;
    auto* wnd = new TranslationConfigWnd();
    wnd->SetFont(GetAppFont());
    wnd->closeOnEsc = true;
    wnd->closeOnCtrlW = true;
    wnd->onBeforeDelete = MkFunc0Void(ClearTranslationConfigWnd);
    wnd->onClose = MkFunc1Void<WindowBase::CloseEvent*>(OnTranslationConfigClose);
    wnd->onDestroy = MkFunc1Void<WindowBase::DestroyEvent*>(OnTranslationConfigDestroy);
    wnd->onDpiChanged =
        MkMethod1<TranslationConfigWnd, WindowBase::DpiChangedEvent*, &TranslationConfigWnd::OnDpiChanged>(wnd);
    wnd->onGetMinMaxInfo =
        MkMethod1<TranslationConfigWnd, WindowBase::GetMinMaxInfoEvent*, &TranslationConfigWnd::OnGetMinMaxInfo>(wnd);
    if (!wnd->Create(owner)) {
        delete wnd;
        return;
    }
    gTranslationConfigWnd = wnd;
    HwndToForeground(wnd->hwnd);
    wnd->SetFocusTo(wnd->dropProvider);
}

static TempStr TranslationConfigDumpTemp() {
    str::Builder out;
    TranslationConfigWnd* wnd = gTranslationConfigWnd;
    bool open = wnd && !wnd->deleteScheduled;
    out.Append(fmt("open=%d\n", open ? 1 : 0));
    if (open) {
        TranslationSettings settings = wnd->SettingsTemp();
        TempStr source = wnd->SourceLanguageTemp();
        TempStr target = wnd->TargetLanguageTemp();
        TempStr error = wnd->ValidateTemp();
        bool focused = wnd->dropProvider->IsFocused();
        DWORD keyStyle = (DWORD)GetWindowLongW(wnd->editOpenAIKey->hwnd, GWL_STYLE);
        keyStyle &= (DWORD)GetWindowLongW(wnd->editGoogleKey->hwnd, GWL_STYLE);
        keyStyle &= (DWORD)GetWindowLongW(wnd->editMicrosoftKey->hwnd, GWL_STYLE);
        int rowLabelsWithCurrentFont = 0;
        for (VirtText* label : wnd->rowLabels) {
            rowLabelsWithCurrentFont += label->font == wnd->GetFont();
        }
        int headingsWithCurrentFont = 0;
        for (VirtText* heading : wnd->headings) {
            headingsWithCurrentFont += heading->font == wnd->GetFont();
        }
        out.Append(
            fmt("provider=%s\nsource=%s\ntarget=%s\n", TranslationProviderName(settings.provider), source, target));
        out.Append(
            fmt("openAIVisible=%d\ngoogleVisible=%d\ngoogleKeyVisible=%d\nmicrosoftVisible=%d\n",
                wnd->openAIGroup->GetVisibility() == Visibility::Visible && wnd->editOpenAIKey->IsVisible(),
                wnd->googleGroup->GetVisibility() == Visibility::Visible, wnd->editGoogleKey->IsVisible(),
                wnd->microsoftGroup->GetVisibility() == Visibility::Visible && wnd->editMicrosoftKey->IsVisible()));
        out.Append(fmt("openAIBaseUrlBytes=%d\nopenAIModelBytes=%d\nopenAIKeyBytes=%d\ngoogleKeyBytes=%d\n",
                       len(settings.openAIBaseUrl), len(settings.openAIModel), len(settings.openAIKey),
                       len(settings.googleKey)));
        out.Append(fmt("microsoftEndpointBytes=%d\nmicrosoftRegionBytes=%d\nmicrosoftKeyBytes=%d\n",
                       len(settings.microsoftEndpoint), len(settings.microsoftRegion), len(settings.microsoftKey)));
        out.Append(fmt("providerCount=%d\nsourceCount=%d\ntargetCount=%d\nfocused=%d\n",
                       CbGetItemsCount(wnd->dropProvider->hwnd), CbGetItemsCount(wnd->dropSource->hwnd),
                       CbGetItemsCount(wnd->dropTarget->hwnd), focused));
        out.Append(fmt("fontDpi=%d\nrowLabelFonts=%d/%d\nheadingFonts=%d/%d\n", wnd->fontDpi, rowLabelsWithCurrentFont,
                       len(wnd->rowLabels), headingsWithCurrentFont, len(wnd->headings)));
        out.Append(
            fmt("keyMasked=%d\nwarning=%d\ncostWarning=%d\nvalid=%d\ntestEnabled=%d\nsaveEnabled=%d\n"
                "working=%d\nrequest=%d\nstatus=%s\n",
                (keyStyle & ES_PASSWORD) != 0, wnd->storageWarning && wnd->storageWarning->IsVisible(),
                wnd->costWarning && wnd->costWarning->IsVisible(), error ? 0 : 1,
                wnd->btnTest && wnd->btnTest->IsEnabled(), wnd->btnSave && wnd->btnSave->IsEnabled(), wnd->working,
                wnd->requestId, wnd->status ? wnd->status->s : Str{}));
    }
    if (gSettings) {
        out.Append(fmt("persistedProvider=%s\npersistedSource=%s\npersistedTarget=%s\n", gSettings->translationProvider,
                       gSettings->translateFromLang, gSettings->translateToLang));
        out.Append(
            fmt("persistedOpenAIBaseUrlBytes=%d\npersistedOpenAIModelBytes=%d\n"
                "persistedOpenAIKeyBytes=%d\npersistedGoogleKeyBytes=%d\n",
                len(gSettings->translationOpenAIBaseUrl), len(gSettings->translationOpenAIModel),
                len(gSettings->translationOpenAIKey), len(gSettings->translationGoogleKey)));
        out.Append(
            fmt("persistedMicrosoftEndpointBytes=%d\npersistedMicrosoftRegionBytes=%d\n"
                "persistedMicrosoftKeyBytes=%d\n",
                len(gSettings->translationMicrosoftEndpoint), len(gSettings->translationMicrosoftRegion),
                len(gSettings->translationMicrosoftKey)));
    }
    return ToStrTemp(out);
}

static void SetConfigSelection(DropDown* drop, Str value, ConfigSelectionKind kind, AutoLanguage autoLanguage) {
    bool isProvider = kind == ConfigSelectionKind::Provider;
    int idx = isProvider ? ProviderIndex(TranslationProviderFromName(value)) : LanguageIndex(value, autoLanguage);
    if (isProvider && TranslationProviderFromName(value) == TranslationProviderId::None) {
        idx = -1;
    }
    CbSetCurrentSelection(drop, idx);
}

TempStr TranslationConfigTestTemp(Str action, Str value, int* exitCode) {
    int code = 0;
    if (str::Eq(action, StrL("open"))) {
        ShowTranslationConfig();
    } else if (str::Eq(action, StrL("dump"))) {
    } else if (!gTranslationConfigWnd) {
        code = 1;
    } else if (str::Eq(action, StrL("dpi"))) {
        int dpi = ParseInt(value);
        if (dpi <= 0) {
            code = 1;
        } else {
            gTranslationConfigWnd->UpdateDpi(dpi);
            gTranslationConfigWnd->Relayout();
        }
    } else if (str::Eq(action, StrL("provider"))) {
        SetConfigSelection(gTranslationConfigWnd->dropProvider, value, ConfigSelectionKind::Provider,
                           AutoLanguage::Exclude);
        gTranslationConfigWnd->ProviderChanged();
    } else if (str::Eq(action, StrL("source"))) {
        SetConfigSelection(gTranslationConfigWnd->dropSource, value, ConfigSelectionKind::Language,
                           AutoLanguage::Include);
        gTranslationConfigWnd->InputChanged();
    } else if (str::Eq(action, StrL("target"))) {
        SetConfigSelection(gTranslationConfigWnd->dropTarget, value, ConfigSelectionKind::Language,
                           AutoLanguage::Exclude);
        gTranslationConfigWnd->InputChanged();
    } else if (str::Eq(action, StrL("base"))) {
        gTranslationConfigWnd->editOpenAIBaseUrl->SetText(value);
        gTranslationConfigWnd->InputChanged();
    } else if (str::Eq(action, StrL("model"))) {
        gTranslationConfigWnd->editOpenAIModel->SetText(value);
        gTranslationConfigWnd->InputChanged();
    } else if (str::Eq(action, StrL("endpoint"))) {
        gTranslationConfigWnd->editMicrosoftEndpoint->SetText(value);
        gTranslationConfigWnd->InputChanged();
    } else if (str::Eq(action, StrL("region"))) {
        gTranslationConfigWnd->editMicrosoftRegion->SetText(value);
        gTranslationConfigWnd->InputChanged();
    } else if (str::Eq(action, StrL("key"))) {
        TranslationProviderId provider = gTranslationConfigWnd->Provider();
        Edit* edit = provider == TranslationProviderId::OpenAICompatible ? gTranslationConfigWnd->editOpenAIKey
                     : provider == TranslationProviderId::GoogleCloud    ? gTranslationConfigWnd->editGoogleKey
                     : provider == TranslationProviderId::Microsoft      ? gTranslationConfigWnd->editMicrosoftKey
                                                                         : nullptr;
        if (edit) {
            edit->SetText(value);
            gTranslationConfigWnd->InputChanged();
        }
    } else if (str::Eq(action, StrL("test"))) {
        gTranslationConfigWnd->StartTest(ConfigTestStart::NoWorker);
    } else if (str::Eq(action, StrL("result"))) {
        ConfigTestResult result = str::Eq(value, StrL("ok")) ? ConfigTestResult::Success : ConfigTestResult::Failure;
        gTranslationConfigWnd->OnTestDone(gTranslationConfigWnd->requestId, result);
    } else if (str::Eq(action, StrL("stale"))) {
        gTranslationConfigWnd->OnTestDone(gTranslationConfigWnd->requestId - 1, ConfigTestResult::Failure);
    } else if (str::Eq(action, StrL("save"))) {
        gTranslationConfigWnd->Save();
    } else if (str::Eq(action, StrL("cancel"))) {
        gTranslationConfigWnd->Cancel();
    } else {
        code = 1;
    }
    if (exitCode) {
        *exitCode = code;
    }
    return TranslationConfigDumpTemp();
}
