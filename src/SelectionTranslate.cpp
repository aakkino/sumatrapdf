/* Copyright 2022 the SumatraPDF project authors (see AUTHORS file).
   License: GPLv3 */

#include "base/Base.h"
#include "base/CmdLineArgs.h"
#include "base/ScopedWin.h"
#include "base/UITask.h"
#include "base/Win.h"
#include "base/Http.h"
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
#include "AIChatCommon.h"
#include "AIChatPanel.h"
#include "Translations.h"
#include "Theme.h"
#include "DarkMode_win.h"
#include "SelectionTranslate.h"

static const Str kSrcLangAuto = StrL("Auto");

static const Str gPopularLanguages[] = {
    StrL("English"),
    StrL("Chinese (Simplified)"),
    StrL("Chinese (Traditional)"),
    StrL("Spanish"),
    StrL("Arabic"),
    StrL("Hindi"),
    StrL("Portuguese"),
    StrL("Bengali"),
    StrL("Russian"),
    StrL("Japanese"),
    StrL("Punjabi"),
    StrL("German"),
    StrL("French"),
    StrL("Korean"),
    StrL("Turkish"),
    StrL("Vietnamese"),
    StrL("Italian"),
    StrL("Polish"),
    StrL("Ukrainian"),
    StrL("Dutch"),
    StrL("Thai"),
    StrL("Indonesian"),
    StrL("Czech"),
    StrL("Swedish"),
    StrL("Romanian"),
    StrL("Greek"),
    StrL("Hebrew"),
    StrL("Danish"),
    StrL("Finnish"),
    StrL("Norwegian"),
    StrL("Hungarian"),
    StrL("Slovak"),
};

// maps the language names offered in the From/To dropdowns to ISO 639 codes
// used in Google / DeepL urls (name, code pairs)
static const char* gLangNameToCode =
    "English\0en\0Chinese (Simplified)\0zh-CN\0Chinese (Traditional)\0zh-TW\0Spanish\0es\0Arabic\0ar\0Hindi\0hi\0"
    "Portuguese\0pt\0Bengali\0bn\0Russian\0ru\0Japanese\0ja\0Punjabi\0pa\0German\0de\0French\0fr\0Korean\0ko\0"
    "Turkish\0tr\0Vietnamese\0vi\0Italian\0it\0Polish\0pl\0Ukrainian\0uk\0Dutch\0nl\0Thai\0th\0Indonesian\0id\0"
    "Czech\0cs\0Swedish\0sv\0Romanian\0ro\0Greek\0el\0Hebrew\0he\0Danish\0da\0Finnish\0fi\0Norwegian\0no\0"
    "Hungarian\0hu\0Slovak\0sk\0";

// empty result means unknown language (the dropdowns are editable, so the
// user can type anything) => auto-detect for source, English for destination
static TempStr LangCodeForUrlTemp(Str name) {
    if (str::IsEmptyOrWhiteSpace(name)) {
        return {};
    }
    TempStr n = str::DupTemp(name);
    str::TrimWSInPlace(n, str::TrimOpt::Both);
    int idx = SeqStrIndexIS(gLangNameToCode, n);
    if (idx < 0 || idx % 2 != 0) {
        return {};
    }
    return SeqStrByIndex(gLangNameToCode, idx + 1);
}

struct SelectionTranslateWnd : WindowBase {
    ~SelectionTranslateWnd() override;

    HWND hwndOwner = nullptr;
    // the labels and the buttons are virtual controls; the text fields and the
    // drop-downs are real HWNDs
    VirtText* staticPrompt = nullptr;
    DropDown* dropEngine = nullptr;
    Edit* editSrcText = nullptr;
    VirtText* staticFromLabel = nullptr;
    DropDown* dropSrcLang = nullptr;
    VirtText* staticToLabel = nullptr;
    DropDown* dropDstLang = nullptr;
    VirtButton* btnTranslate = nullptr;
    VirtButton* btnClose = nullptr;
    VirtText* staticResultLabel = nullptr;
    Edit* editResult = nullptr;

    // engine pre-selected in the dropdown when the dialog opens
    TranslateEngine engine = TranslateEngine::Google;
    // AI backend of the in-flight translation (for error formatting)
    AIChatBackend backend = AIChatBackend::Grok;
    bool translating = false;
    bool resultVisible = false;
    // true after the first size-to-content layout
    bool sizeInitialized = false;

    bool Create(HWND owner, Str selText, Str title);
    // initial: size to content and center; later: reflow keeping (or growing) current size
    void Relayout(bool initial = false);
    VirtButton* NewButton(Str text, bool isDefault);
    // the label changes width ("Translate" / "Translating..."), so the row is
    // laid out again
    void SetTranslateButtonText(Str);
    void UpdateTranslateButtonState();
    void ShowTranslationResult(Str text, bool isError);
    void StartTranslation(VirtMouseEvent* ev = nullptr);
    void OnTranslationFinished(bool ok, Str msg);
    void OnCloseClicked(VirtMouseEvent* ev = nullptr);

    void UpdateFont();

    void OnGetMinMaxInfo(WindowBase::GetMinMaxInfoEvent* ev);
    void OnDpiChanged(WindowBase::DpiChangedEvent* ev);
};

static SelectionTranslateWnd* gSelectionTranslateWnd = nullptr;

SelectionTranslateWnd::~SelectionTranslateWnd() = default;

struct SelectionTranslateTaskData {
    // the dialog can be closed and deleted (via ScheduleDelete) while the
    // translation thread runs, so remember only its HWND, never the object.
    // OnTranslateDone re-validates the HWND against gSelectionTranslateWnd.
    HWND hwndDlg = nullptr;
    AIChatBackend backend = AIChatBackend::Grok;
    Str srcLang;
    Str dstLang;
    Str text;
    ~SelectionTranslateTaskData() {
        str::Free(srcLang);
        str::Free(dstLang);
        str::Free(text);
    }
};

struct SelectionTranslateDoneData {
    HWND hwndDlg = nullptr;
    bool ok = false;
    Str msg;
    ~SelectionTranslateDoneData() { str::Free(msg); }
};

static void SelectionTranslateThread(SelectionTranslateTaskData* data);

static void PopulateLanguageDropDown(DropDown* dd, Str initial, bool includeAuto) {
    if (!dd) {
        return;
    }
    StrVec items;
    if (includeAuto) {
        items.Append(kSrcLangAuto);
    }
    for (Str lang : gPopularLanguages) {
        items.Append(lang);
    }
    dd->SetItems(items);
    if (!str::IsEmptyOrWhiteSpace(initial)) {
        dd->SetText(initial);
        for (int i = 0; i < len(items); i++) {
            if (str::EqI(items[i], initial)) {
                CbSetCurrentSelection(dd, i);
                return;
            }
        }
    }
}

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

static TempStr NormalizeLangNameTemp(Str lang) {
    if (str::IsEmptyOrWhiteSpace(lang)) {
        return {};
    }
    TempStr normalized = str::DupTemp(lang);
    str::TrimWSInPlace(normalized, str::TrimOpt::Both);
    return normalized;
}

static TempStr DefaultSourceLanguageTemp() {
    if (gSettings && !str::IsEmptyOrWhiteSpace(gSettings->translateFromLang)) {
        return gSettings->translateFromLang;
    }
    return kSrcLangAuto;
}

// update one remembered translate pref; returns true if it changed
static bool UpdateTranslatePref(Str* pref, Str value) {
    TempStr normalized = NormalizeLangNameTemp(value);
    if (!normalized || (*pref && str::EqI(*pref, normalized))) {
        return false;
    }
    str::ReplacePtr(pref, str::Dup(normalized));
    return true;
}

static Str EngineDisplayName(TranslateEngine engine);

// remember engine / from / to across launches of the dialog
static void MaybeSaveTranslatePrefs(TranslateEngine engine, Str srcLang, Str dstLang) {
    if (!gSettings) {
        return;
    }
    bool changed = UpdateTranslatePref(&gSettings->translateEngine, EngineDisplayName(engine));
    changed |= UpdateTranslatePref(&gSettings->translateFromLang, srcLang);
    changed |= UpdateTranslatePref(&gSettings->translateToLang, dstLang);
    if (changed) {
        ScheduleSaveSettings();
    }
}

static void MaybeSaveQuickTranslateEngine(TranslateEngine engine) {
    if (!gSettings) {
        return;
    }
    if (UpdateTranslatePref(&gSettings->translateEngine, EngineDisplayName(engine))) {
        ScheduleSaveSettings();
    }
}

static bool IsSrcLangAutoTemp(Str srcLang) {
    if (str::IsEmptyOrWhiteSpace(srcLang)) {
        return false;
    }
    TempStr lang = str::DupTemp(srcLang);
    str::TrimWSInPlace(lang, str::TrimOpt::Both);
    return str::EqI(lang, kSrcLangAuto);
}

static bool LanguagesAreSameTemp(Str a, Str b) {
    if (IsSrcLangAutoTemp(a) || IsSrcLangAutoTemp(b)) {
        return false;
    }
    if (str::IsEmptyOrWhiteSpace(a) || str::IsEmptyOrWhiteSpace(b)) {
        return false;
    }
    TempStr aa = str::DupTemp(a);
    TempStr bb = str::DupTemp(b);
    str::TrimWSInPlace(aa, str::TrimOpt::Both);
    str::TrimWSInPlace(bb, str::TrimOpt::Both);
    return str::EqI(aa, bb);
}

static bool TranslationLooksLikeError(Str text) {
    if (str::IsEmptyOrWhiteSpace(text)) {
        return true;
    }
    if (str::ContainsI(text, StrL("failed to authenticate"))) {
        return true;
    }
    if (str::ContainsI(text, StrL("authentication_failed"))) {
        return true;
    }
    if (str::ContainsI(text, StrL("api error"))) {
        return true;
    }
    if (str::StartsWithI(text, StrL("error:"))) {
        return true;
    }
    if (str::ContainsI(text, StrL("model is not supported"))) {
        return true;
    }
    return false;
}

static TempStr FormatTranslationErrorForDisplayTemp(AIChatBackend backend, Str raw) {
    if (str::IsEmptyOrWhiteSpace(raw)) {
        return str::DupTemp(_TRA("Translation failed."));
    }
    if (str::ContainsI(raw, StrL("failed to authenticate")) || str::ContainsI(raw, StrL("authentication_failed")) ||
        str::ContainsI(raw, StrL("invalid authentication credentials"))) {
        if (backend == AIChatBackend::Claude) {
            return str::DupTemp(
                _TRA("Claude Code is not signed in. Open a terminal, run \"claude auth login\", "
                     "then try again."));
        }
        if (backend == AIChatBackend::Grok) {
            return str::DupTemp(_TRA("Grok Build is not signed in. Sign in to Grok Build, then try again."));
        }
        if (backend == AIChatBackend::Codex) {
            return str::DupTemp(_TRA("OpenAI Codex is not signed in. Sign in to Codex, then try again."));
        }
        if (backend == AIChatBackend::AntiGravity) {
            return str::DupTemp(_TRA(
                "Antigravity CLI is not signed in. Open a terminal, run \"antigravity auth login\", then try again."));
        }
    }
    if (str::ContainsI(raw, StrL("model is not supported"))) {
        return str::DupTemp(_TRA("The configured AI model is not available for your account."));
    }
    if (str::ContainsI(raw, StrL("did not contain text"))) {
        return str::DupTemp(_TRA("Translation response did not contain text."));
    }
    return str::DupTemp(raw);
}

static TempStr StripTrailingSlashTemp(TempStr path) {
    if (!path) {
        return {};
    }
    TempStr p = str::DupTemp(path);
    while (len(p) > 0 && (p.s[len(p) - 1] == '\\' || p.s[len(p) - 1] == '/')) {
        p.len--;
        p.s[len(p)] = 0;
    }
    return p;
}

static TempStr NormalizeTextForPromptTemp(Str text) {
    if (!text) {
        return {};
    }
    str::Builder buf;
    for (int i = 0; i < text.len; i++) {
        char c = text.s[i];
        if (c == '\r' || c == '\n' || c == '\t') {
            if (len(buf) > 0 && buf.LastChar() != ' ') {
                buf.AppendChar(' ');
            }
        } else {
            buf.AppendChar(c);
        }
    }
    TempStr s = ToStrTemp(buf);
    str::TrimWSInPlace(s, str::TrimOpt::Both);
    return s;
}

static TempStr BuildTranslationPromptTemp(Str srcLang, Str dstLang, Str text) {
    TempStr normalized = NormalizeTextForPromptTemp(text);
    if (IsSrcLangAutoTemp(srcLang)) {
        return fmt(
            "Detect the language of the following text and translate it to %s. Return only the "
            "translation with no explanation, commentary, or quotation marks. Text: %s",
            dstLang, normalized);
    }
    return fmt(
        "Translate the following text from %s to %s. Return only the translation with no "
        "explanation, commentary, or quotation marks. Text: %s",
        srcLang, dstLang, normalized);
}

constexpr DWORD kTranslationTimeoutMs = 5 * 60 * 1000;
constexpr DWORD kTranslationPipePollMs = 10;

// Read without blocking past the translation deadline when a CLI hangs while
// keeping its stdout pipe open.
static bool ReadTranslationOutput(HANDLE hPipe, HANDLE hProcess, str::Builder& out) {
    ULONGLONG deadline = GetTickCount64() + kTranslationTimeoutMs;
    bool pipeOpen = true;
    for (;;) {
        if (pipeOpen) {
            DWORD available = 0;
            if (!PeekNamedPipe(hPipe, nullptr, 0, nullptr, &available, nullptr)) {
                pipeOpen = false;
            } else if (available > 0) {
                char buf[4096];
                DWORD bytesRead = 0;
                DWORD toRead = std::min<DWORD>(available, dimof(buf));
                if (!ReadFile(hPipe, buf, toRead, &bytesRead, nullptr) || bytesRead == 0) {
                    pipeOpen = false;
                } else {
                    out.Append(Str(buf, (int)bytesRead));
                    continue;
                }
            }
        }

        ULONGLONG now = GetTickCount64();
        if (now >= deadline) {
            return false;
        }
        DWORD waitMs = (DWORD)std::min<ULONGLONG>(deadline - now, kTranslationPipePollMs);
        DWORD waitRes = WaitForSingleObject(hProcess, waitMs);
        if (waitRes == WAIT_OBJECT_0) {
            return true;
        }
        if (waitRes == WAIT_FAILED) {
            return false;
        }
    }
}

static void AppendGrokTranslationText(Str line, str::Builder& out) {
    TempStr eventType = AIChatJsonStrTemp(line, StrL("type"));
    if (eventType && str::Eq(eventType, StrL("text"))) {
        TempStr text = AIChatJsonStrTemp(line, StrL("data"));
        if (len(text) > 0) {
            out.Append(text);
        }
    }
}

static void AppendClaudeTranslationText(Str line, str::Builder& out) {
    TempStr eventType = AIChatJsonStrTemp(line, StrL("type"));
    if (!eventType) {
        return;
    }
    if (str::Eq(eventType, StrL("result"))) {
        bool isError = str::Contains(line, StrL("\"is_error\":true"));
        TempStr text = AIChatJsonStrTemp(line, StrL("result"));
        if (len(text) > 0) {
            if (isError) {
                out.Reset();
                out.Append(text);
            } else if (len(out) == 0) {
                out.Append(text);
            }
        }
        return;
    }
    if (str::Contains(line, StrL("authentication_failed")) || str::Contains(line, StrL("\"is_error\":true"))) {
        return;
    }
    if (str::Eq(eventType, StrL("assistant")) && str::Contains(line, StrL("\"type\":\"text\""))) {
        TempStr text = AIChatJsonStrTemp(line, StrL("text"));
        if (len(text) > 0 && !TranslationLooksLikeError(text)) {
            out.Append(text);
        }
    } else if (str::Eq(eventType, StrL("content_block_delta"))) {
        TempStr text = AIChatJsonStrTemp(line, StrL("text"));
        if (len(text) > 0) {
            out.Append(text);
        }
    }
}

static void AppendCodexTranslationText(Str line, str::Builder& out) {
    if (!line || line.s[0] != '{') {
        return;
    }
    TempStr eventType = AIChatJsonStrTemp(line, StrL("type"));
    if (!eventType || !str::Eq(eventType, StrL("item.completed"))) {
        return;
    }
    TempStr text = AIChatJsonStrTemp(line, StrL("text"));
    if (len(text) > 0) {
        out.Append(text);
        return;
    }
    Str agentMsg;
    if (str::Cut(line, StrL("\"type\":\"agent_message\""), nullptr, &agentMsg)) {
        text = AIChatJsonStrTemp(agentMsg, StrL("text"));
        if (len(text) > 0) {
            out.Append(text);
        }
    }
}

// antigravity's stream-json isn't claude's: text arrives as `text_delta` in
// `event:step_update` lines with `step_type:agent_response`, and errors as an
// `event:result` with status ERROR (see AIAntiGravity.cpp::ParseStreamLine).
static void AppendAntiGravityTranslationText(Str line, str::Builder& out) {
    TempStr eventName = AIChatJsonStrTemp(line, StrL("event"));
    if (!eventName) {
        return;
    }
    if (str::Eq(eventName, StrL("step_update"))) {
        if (str::Contains(line, StrL("\"step_type\":\"agent_response\""))) {
            TempStr delta = AIChatJsonStrTemp(line, StrL("text_delta"));
            if (len(delta) > 0) {
                out.Append(delta);
            }
        }
        return;
    }
    if (str::Eq(eventName, StrL("result"))) {
        TempStr status = AIChatJsonStrTemp(line, StrL("status"));
        if (status && str::Eq(status, StrL("ERROR"))) {
            TempStr err = AIChatJsonStrTemp(line, StrL("error"));
            if (len(err) > 0) {
                out.Reset();
                out.Append(err);
            }
        }
    }
}

static void ParseTranslationOutput(AIChatBackend backend, Str output, str::Builder& translationOut) {
    if (str::IsEmptyOrWhiteSpace(output)) {
        return;
    }
    int off = 0;
    while (off < output.len) {
        int lineStart = off;
        while (off < output.len && output.s[off] != '\n' && output.s[off] != '\r') {
            off++;
        }
        if (off > lineStart) {
            TempStr line = str::DupTemp(Str(output.s + lineStart, off - lineStart));
            if (backend == AIChatBackend::Grok) {
                AppendGrokTranslationText(line, translationOut);
            } else if (backend == AIChatBackend::Claude) {
                AppendClaudeTranslationText(line, translationOut);
            } else if (backend == AIChatBackend::Codex) {
                AppendCodexTranslationText(line, translationOut);
            } else if (backend == AIChatBackend::AntiGravity) {
                AppendAntiGravityTranslationText(line, translationOut);
            }
        }
        while (off < output.len && (output.s[off] == '\n' || output.s[off] == '\r')) {
            off++;
        }
    }
    {
        Str s = ToStr(translationOut);
        str::TrimWSInPlace(s, str::TrimOpt::Both);
        translationOut.len = s.len;
    }
    if (len(translationOut) == 0 && output && !str::Contains(output, StrL("{\"type\":")) &&
        !str::Contains(output, StrL("{\"event\":"))) {
        TempStr trimmed = str::DupTemp(output);
        str::TrimWSInPlace(trimmed, str::TrimOpt::Both);
        if (!str::IsEmptyOrWhiteSpace(trimmed)) {
            translationOut.Append(trimmed);
        }
    }
}

static TempStr BuildGrokTranslateCmdLineTemp(Str exePath, Str prompt, Str cwd) {
    Str model = gSettings->grokBuild.model;
    if (str::IsEmptyOrWhiteSpace(model)) {
        model = StrL("grok-composer-2.5-fast");
    }
    Str permsFlag = gSettings->grokBuild.alwaysApprove ? StrL("--always-approve") : Str{};
    // QuoteCmdLineArgTemp: full Windows argv quoting (not just " -> \") so
    // prompt text ending in \" cannot inject extra CLI flags (CWE-88 / GHSA).
    return fmt("%s -p %s --cwd %s --output-format streaming-json --model %s --effort low %s",
               QuoteCmdLineArgTemp(exePath), QuoteCmdLineArgTemp(prompt), QuoteCmdLineArgTemp(cwd),
               QuoteCmdLineArgTemp(model), permsFlag);
}

static TempStr BuildClaudeTranslateCmdLineTemp(Str exePath, Str prompt) {
    Str model = gSettings->claudeCode.model;
    if (str::IsEmptyOrWhiteSpace(model)) {
        model = StrL("claude-sonnet-4-20250514");
    }
    Str permsFlag = gSettings->claudeCode.skipPermissions ? StrL("--dangerously-skip-permissions") : Str{};
    TempStr sessionId = AIChatGenerateSessionIdTemp();
    return fmt("%s -p --verbose --output-format stream-json --model %s %s --session-id %s %s",
               QuoteCmdLineArgTemp(exePath), QuoteCmdLineArgTemp(model), permsFlag, sessionId,
               QuoteCmdLineArgTemp(prompt));
}

static TempStr BuildCodexTranslateCmdLineTemp(Str exePath, Str prompt, Str cwd) {
    Str model = gSettings->codexBuild.model;
    bool hasModel = !str::IsEmptyOrWhiteSpace(model);
    Str skipFlag = gSettings->codexBuild.skipSandbox ? StrL("--dangerously-bypass-approvals-and-sandbox") : Str{};
    if (skipFlag) {
        if (hasModel) {
            return fmt("%s exec --json -C %s --skip-git-repo-check -m %s -s read-only %s %s",
                       QuoteCmdLineArgTemp(exePath), QuoteCmdLineArgTemp(cwd), QuoteCmdLineArgTemp(model), skipFlag,
                       QuoteCmdLineArgTemp(prompt));
        }
        return fmt("%s exec --json -C %s --skip-git-repo-check -s read-only %s %s", QuoteCmdLineArgTemp(exePath),
                   QuoteCmdLineArgTemp(cwd), skipFlag, QuoteCmdLineArgTemp(prompt));
    }
    if (hasModel) {
        return fmt("%s exec --json -C %s --skip-git-repo-check -m %s -s read-only %s", QuoteCmdLineArgTemp(exePath),
                   QuoteCmdLineArgTemp(cwd), QuoteCmdLineArgTemp(model), QuoteCmdLineArgTemp(prompt));
    }
    return fmt("%s exec --json -C %s --skip-git-repo-check -s read-only %s", QuoteCmdLineArgTemp(exePath),
               QuoteCmdLineArgTemp(cwd), QuoteCmdLineArgTemp(prompt));
}

static TempStr BuildAntiGravityTranslateCmdLineTemp(Str exePath, Str prompt) {
    Str model = gSettings->antiGravity.model;
    if (str::IsEmptyOrWhiteSpace(model)) {
        model = StrL("gemini-3.6-flash");
    }
    // agy takes -p/--print's next argument as the prompt and ignores flags
    // after it (see AIAntiGravity.cpp). Putting -p first made the prompt
    // "--model", so the model answered with its own name instead of translating.
    Str permsFlag = gSettings->antiGravity.autoApprove ? StrL("--dangerously-skip-permissions") : Str{};
    return fmt("%s --model %s --effort low --output-format stream-json %s -p %s", QuoteCmdLineArgTemp(exePath),
               QuoteCmdLineArgTemp(model), permsFlag, QuoteCmdLineArgTemp(prompt));
}

static TempStr FindBackendExecutableTemp(AIChatBackend backend) {
    if (backend == AIChatBackend::Grok) {
        return GrokBuildExecutablePathTemp();
    }
    if (backend == AIChatBackend::Claude) {
        return ClaudeCodeExecutablePathTemp();
    }
    if (backend == AIChatBackend::Codex) {
        return CodexBuildExecutablePathTemp();
    }
    if (backend == AIChatBackend::AntiGravity) {
        return AntiGravityExecutablePathTemp();
    }
    return {};
}

static bool IsBackendInstalled(AIChatBackend backend) {
    if (backend == AIChatBackend::Grok) {
        return IsGrokBuildInstalled();
    }
    if (backend == AIChatBackend::Claude) {
        return IsClaudeCodeInstalled();
    }
    if (backend == AIChatBackend::Codex) {
        return IsCodexBuildInstalled();
    }
    if (backend == AIChatBackend::AntiGravity) {
        return IsAntiGravityInstalled();
    }
    return false;
}

static Str BackendDisplayName(AIChatBackend backend) {
    if (backend == AIChatBackend::Grok) {
        return StrL("Grok Build");
    }
    if (backend == AIChatBackend::Claude) {
        return StrL("Claude Code");
    }
    if (backend == AIChatBackend::Codex) {
        return StrL("OpenAI Codex");
    }
    if (backend == AIChatBackend::AntiGravity) {
        return StrL("Antigravity");
    }
    return StrL("AI");
}

// in dropdown order
static const TranslateEngine gAllEngines[] = {
    TranslateEngine::Google, TranslateEngine::DeepL, TranslateEngine::Grok,
    TranslateEngine::Claude, TranslateEngine::Codex, TranslateEngine::AntiGravity,
};

static bool EngineIsAI(TranslateEngine engine) {
    return engine == TranslateEngine::Grok || engine == TranslateEngine::Claude || engine == TranslateEngine::Codex ||
           engine == TranslateEngine::AntiGravity;
}

static AIChatBackend BackendFromEngine(TranslateEngine engine) {
    if (engine == TranslateEngine::Claude) {
        return AIChatBackend::Claude;
    }
    if (engine == TranslateEngine::Codex) {
        return AIChatBackend::Codex;
    }
    if (engine == TranslateEngine::AntiGravity) {
        return AIChatBackend::AntiGravity;
    }
    return AIChatBackend::Grok;
}

static Str EngineDisplayName(TranslateEngine engine) {
    switch (engine) {
        case TranslateEngine::DeepL:
            return StrL("DeepL");
        case TranslateEngine::Grok:
        case TranslateEngine::Claude:
        case TranslateEngine::Codex:
        case TranslateEngine::AntiGravity:
            return BackendDisplayName(BackendFromEngine(engine));
        default:
            return StrL("Google");
    }
}

static bool IsEngineAvailable(TranslateEngine engine) {
    if (EngineIsAI(engine)) {
        return IsBackendInstalled(BackendFromEngine(engine));
    }
    // Google / DeepL translate by opening a browser
    return HasPermission(Perm::InternetAccess);
}

static TranslateEngine EngineFromName(Str name) {
    for (TranslateEngine engine : gAllEngines) {
        if (!str::IsEmptyOrWhiteSpace(name) && str::EqI(name, EngineDisplayName(engine))) {
            return engine;
        }
    }
    return TranslateEngine::Default;
}

// Default => the engine remembered in settings; anything unavailable falls
// back to the first available engine
static TranslateEngine ResolveEngine(TranslateEngine engine) {
    if (engine == TranslateEngine::Default && gSettings) {
        engine = EngineFromName(gSettings->translateEngine);
    }
    if (engine != TranslateEngine::Default && IsEngineAvailable(engine)) {
        return engine;
    }
    for (TranslateEngine cand : gAllEngines) {
        if (IsEngineAvailable(cand)) {
            return cand;
        }
    }
    return TranslateEngine::Google;
}

static void PopulateEngineDropDown(DropDown* dd, TranslateEngine selected) {
    StrVec items;
    int selIdx = 0;
    for (TranslateEngine engine : gAllEngines) {
        if (!IsEngineAvailable(engine)) {
            continue;
        }
        if (engine == selected) {
            selIdx = len(items);
        }
        items.Append(EngineDisplayName(engine));
    }
    if (len(items) == 0) {
        items.Append(EngineDisplayName(TranslateEngine::Google));
    }
    dd->SetItems(items);
    CbSetCurrentSelection(dd, selIdx);
}

// build the Google / DeepL web-translator url for the given languages and text
static TempStr BuildTranslateUrlTemp(TranslateEngine engine, Str srcLang, Str dstLang, Str text) {
    TempStr enc = URLEncodeMayTruncateTemp(text);
    if (!enc) {
        return {};
    }
    TempStr src = LangCodeForUrlTemp(srcLang);
    if (!src) {
        src = str::DupTemp(StrL("auto"));
    }
    TempStr dst = LangCodeForUrlTemp(dstLang);
    if (!dst) {
        dst = str::DupTemp(StrL("en"));
    }
    if (engine == TranslateEngine::DeepL) {
        // DeepL uses plain "zh" for Chinese
        if (str::StartsWithI(src, StrL("zh"))) {
            src = str::DupTemp(StrL("zh"));
        }
        if (str::StartsWithI(dst, StrL("zh"))) {
            dst = str::DupTemp(StrL("zh"));
        }
        return fmt("https://www.deepl.com/translator#%s/%s/%s", src, dst, enc);
    }
    return fmt("https://translate.google.com/?op=translate&sl=%s&tl=%s&text=%s", src, dst, enc);
}

static bool RunTranslation(AIChatBackend backend, Str srcLang, Str dstLang, Str text, Str& msgOut) {
    TempStr exePath = FindBackendExecutableTemp(backend);
    if (!exePath) {
        msgOut = str::Dup(_TRA("The selected AI CLI is not installed."));
        return false;
    }

    TempStr prompt = BuildTranslationPromptTemp(srcLang, dstLang, text);
    TempStr cwd = StripTrailingSlashTemp(GetTempDirTemp());
    TempStr cmdLine;
    if (backend == AIChatBackend::Grok) {
        cmdLine = BuildGrokTranslateCmdLineTemp(exePath, prompt, cwd);
    } else if (backend == AIChatBackend::Claude) {
        cmdLine = BuildClaudeTranslateCmdLineTemp(exePath, prompt);
    } else if (backend == AIChatBackend::Codex) {
        cmdLine = BuildCodexTranslateCmdLineTemp(exePath, prompt, cwd);
    } else if (backend == AIChatBackend::AntiGravity) {
        cmdLine = BuildAntiGravityTranslateCmdLineTemp(exePath, prompt);
    }

    AIChatProcessLaunchResult launch;
    if (!AIChatLaunchProcessWithStdoutPipe(cmdLine, cwd, &launch)) {
        msgOut = str::Dup(_TRA("Failed to launch the AI CLI."));
        return false;
    }

    str::Builder output;
    str::BuilderReserve(nullptr, output, 4096);
    bool finished = ReadTranslationOutput(launch.hReadPipe, launch.hProcess, output);
    CloseHandle(launch.hReadPipe);
    launch.hReadPipe = nullptr;

    if (!finished) {
        TerminateProcess(launch.hProcess, 1);
        AIChatCloseProcess(&launch.hProcess, false);
        msgOut = str::Dup(_TRA("Translation timed out."));
        return false;
    }
    AIChatCloseProcess(&launch.hProcess, false);

    str::Builder translation;
    str::BuilderReserve(nullptr, translation, 1024);
    ParseTranslationOutput(backend, ToStr(output), translation);
    if (len(translation) == 0) {
        msgOut = str::Dup(_TRA("Translation response did not contain text."));
        return false;
    }
    if (TranslationLooksLikeError(ToStr(translation))) {
        msgOut = translation.TakeStr();
        return false;
    }
    msgOut = translation.TakeStr();
    return true;
}

// backend: 0=Claude, 1=Grok, 2=Codex, 3=AntiGravity
TempStr SelectionTranslateResultTemp(int backend, Str srcLang, Str dstLang, Str text, int* exitCode) {
    AIChatBackend chatBackend = AIChatBackend::Grok;
    if (backend == 0) {
        chatBackend = AIChatBackend::Claude;
    } else if (backend == 2) {
        chatBackend = AIChatBackend::Codex;
    } else if (backend == 3) {
        chatBackend = AIChatBackend::AntiGravity;
    }
    Str msg;
    bool ok = RunTranslation(chatBackend, srcLang, dstLang, text, msg);
    if (exitCode) {
        *exitCode = ok ? 0 : 1;
    }
    TempStr res = str::DupTemp(msg);
    str::Free(msg);
    return res;
}

// re-pick the app font for the window's current DPI and push it to every child.
// GetAppFont() caches a PlatformFont per DPI.
void SelectionTranslateWnd::UpdateFont() {
    SetFont(GetAppFont());
    HwndSetFontForWindowAndItsChildren(hwnd, GetHFont());
    VirtText* virts[] = {staticPrompt, staticFromLabel, staticToLabel, staticResultLabel, btnTranslate, btnClose};
    for (VirtText* w : virts) {
        if (w) {
            w->font = font;
        }
    }
}

VirtButton* SelectionTranslateWnd::NewButton(Str text, bool isDefault) {
    return NewThemedButton(hwnd, text, font, isDefault);
}

void SelectionTranslateWnd::SetTranslateButtonText(Str s) {
    if (!btnTranslate) {
        return;
    }
    btnTranslate->SetText(s);
    Relayout();
    btnTranslate->Invalidate();
}

// Moving the dialog to a monitor with a different scaling changes this window's
// DPI, so re-pick the font and re-run the layout: each control's ideal size is
// measured from its font, so they resize with it. Note the Padding insets were
// DpiScale()d once when the layout tree was built and keep their old scale.
void SelectionTranslateWnd::OnDpiChanged(WindowBase::DpiChangedEvent* ev) {
    RECT* r = ev->suggested;
    if (r) {
        SetWindowPos(hwnd, nullptr, r->left, r->top, r->right - r->left, r->bottom - r->top,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    UpdateFont();
    Relayout();
    HwndInvalidate(hwnd, true);
    ev->didHandle = true;
}

void SelectionTranslateWnd::Relayout(bool initial) {
    if (!layout) {
        return;
    }
    if (initial || !sizeInitialized) {
        LayoutAndSizeToContent(layout, 0, 0, hwnd);
        // pick up the virtual controls so we paint them and they get their input
        DoLayout(HwndClientRect(hwnd).Size());
        HwndCenterDialog(hwnd, hwndOwner);
        sizeInitialized = true;
        return;
    }
    // keep current client size (or grow if new content needs more space, e.g. result)
    Rect rc = HwndClientRect(hwnd);
    LayoutAndSizeToContent(layout, rc.dx, rc.dy, hwnd);
    DoLayout(HwndClientRect(hwnd).Size());
}

void SelectionTranslateWnd::OnGetMinMaxInfo(WindowBase::GetMinMaxInfoEvent* ev) {
    if (!hwnd || !layout || !ev->mmi) {
        return;
    }
    int clientMinDx = layout->MinIntrinsicWidth(Inf);
    int clientMinDy = layout->MinIntrinsicHeight(Inf);
    clientMinDx = std::max(clientMinDx, DpiScale(200));
    clientMinDy = std::max(clientMinDy, DpiScale(150));
    RECT r{0, 0, clientMinDx, clientMinDy};
    DWORD style = (DWORD)GetWindowLongW(hwnd, GWL_STYLE);
    DWORD exStyle = (DWORD)GetWindowLongW(hwnd, GWL_EXSTYLE);
    AdjustWindowRectEx(&r, style, FALSE, exStyle);
    ev->mmi->ptMinTrackSize.x = r.right - r.left;
    ev->mmi->ptMinTrackSize.y = r.bottom - r.top;
}

void SelectionTranslateWnd::UpdateTranslateButtonState() {
    if (!btnTranslate) {
        return;
    }
    TempStr srcLang = dropSrcLang ? dropSrcLang->GetTextTemp() : TempStr{};
    TempStr dstLang = dropDstLang ? dropDstLang->GetTextTemp() : TempStr{};
    TempStr srcText = editSrcText ? editSrcText->GetTextTemp() : TempStr{};
    bool sameLang = LanguagesAreSameTemp(srcLang, dstLang);
    bool hasText = !str::IsEmptyOrWhiteSpace(srcText);
    bool enable = !translating && hasText && !sameLang;
    btnTranslate->SetIsEnabled(enable);
}

void SelectionTranslateWnd::ShowTranslationResult(Str text, bool isError) {
    if (!hwnd) {
        return;
    }
    Str label = isError ? Str(_TRA("Error:")) : Str(_TRA("Translation:"));
    if (!resultVisible) {
        if (staticResultLabel) {
            staticResultLabel->SetVisibility(Visibility::Visible);
        }
        if (editResult) {
            editResult->SetVisibility(Visibility::Visible);
        }
        resultVisible = true;
        Relayout();
    }
    if (staticResultLabel) {
        staticResultLabel->SetText(label);
    }
    if (editResult) {
        editResult->SetText(text);
    }
}

void SelectionTranslateWnd::StartTranslation(VirtMouseEvent*) {
    if (translating) {
        return;
    }
    TempStr srcLang = dropSrcLang ? dropSrcLang->GetTextTemp() : TempStr{};
    TempStr dstLang = dropDstLang ? dropDstLang->GetTextTemp() : TempStr{};
    TempStr text = editSrcText ? editSrcText->GetTextTemp() : TempStr{};
    if (str::IsEmptyOrWhiteSpace(text) || LanguagesAreSameTemp(srcLang, dstLang)) {
        return;
    }

    TranslateEngine curEngine = ResolveEngine(dropEngine ? EngineFromName(dropEngine->GetTextTemp()) : engine);
    MaybeSaveTranslatePrefs(curEngine, srcLang, dstLang);

    if (!EngineIsAI(curEngine)) {
        // Google / DeepL translate in the browser; keep the dialog open so the
        // user can tweak languages or pick a different engine
        TempStr url = BuildTranslateUrlTemp(curEngine, srcLang, dstLang, text);
        if (url) {
            SumatraLaunchBrowser(url);
        }
        return;
    }

    backend = BackendFromEngine(curEngine);
    translating = true;
    if (editSrcText) {
        editSrcText->SetIsEnabled(false);
    }
    if (dropSrcLang) {
        dropSrcLang->SetIsEnabled(false);
    }
    if (dropDstLang) {
        dropDstLang->SetIsEnabled(false);
    }
    if (btnTranslate) {
        btnTranslate->SetIsEnabled(false);
        SetTranslateButtonText(_TRA("Translating..."));
    }
    if (resultVisible) {
        if (staticResultLabel) {
            staticResultLabel->SetVisibility(Visibility::Collapse);
        }
        if (editResult) {
            editResult->SetVisibility(Visibility::Collapse);
        }
        resultVisible = false;
        Relayout();
    }

    auto* task = new SelectionTranslateTaskData();
    task->hwndDlg = hwnd;
    task->backend = backend;
    task->srcLang = str::Dup(srcLang);
    task->dstLang = str::Dup(dstLang);
    task->text = str::Dup(text);
    RunAsync(MkFunc0(SelectionTranslateThread, task), StrL("SelectionTranslate"));
}

void SelectionTranslateWnd::OnTranslationFinished(bool ok, Str msg) {
    translating = false;
    if (editSrcText) {
        editSrcText->SetIsEnabled(true);
    }
    if (dropSrcLang) {
        dropSrcLang->SetIsEnabled(true);
    }
    if (dropDstLang) {
        dropDstLang->SetIsEnabled(true);
    }
    if (btnTranslate) {
        SetTranslateButtonText(_TRA("Translate"));
    }
    TempStr display = ok ? msg : FormatTranslationErrorForDisplayTemp(backend, msg);
    ShowTranslationResult(display, !ok);
    UpdateTranslateButtonState();
}

void SelectionTranslateWnd::OnCloseClicked(VirtMouseEvent*) {
    Close();
}

static void OnTranslateDone(SelectionTranslateDoneData* data) {
    AutoDelete del(data);
    if (!gSelectionTranslateWnd || !IsWindow(gSelectionTranslateWnd->hwnd) ||
        gSelectionTranslateWnd->hwnd != data->hwndDlg) {
        return;
    }
    gSelectionTranslateWnd->OnTranslationFinished(data->ok, data->msg);
}

static void SelectionTranslateThread(SelectionTranslateTaskData* data) {
    AutoDelete del(data);
    Str result;
    bool ok = RunTranslation(data->backend, data->srcLang, data->dstLang, data->text, result);
    if (!ok && len(result) == 0) {
        result = str::Dup(_TRA("Translation failed."));
    }

    auto* done = new SelectionTranslateDoneData();
    done->hwndDlg = data->hwndDlg;
    done->ok = ok;
    done->msg = result;
    uitask::Post(MkFunc0(OnTranslateDone, done), "SelectionTranslateDone");
}

static void TeardownSelectionTranslateWnd() {
    if (!gSelectionTranslateWnd) {
        return;
    }
    SelectionTranslateWnd* w = gSelectionTranslateWnd;
    gSelectionTranslateWnd = nullptr;
    HWND hwndOwner = w->hwndOwner;
    if (hwndOwner) {
        EnableWindow(hwndOwner, TRUE);
        HwndToForeground(hwndOwner);
    }
    w->ScheduleDelete();
}

static void OnSelectionTranslateClose(WindowBase::CloseEvent* ev) {
    if (gSelectionTranslateWnd == (SelectionTranslateWnd*)ev->e->self) {
        TeardownSelectionTranslateWnd();
    }
}

static void OnSelectionTranslateDestroy(WindowBase::DestroyEvent* ev) {
    if (gSelectionTranslateWnd == (SelectionTranslateWnd*)ev->e->self) {
        TeardownSelectionTranslateWnd();
    }
}

bool SelectionTranslateWnd::Create(HWND owner, Str selText, Str title) {
    hwndOwner = owner;
    bool isRtl = IsUIRtl();

    {
        CreateCustomArgs args;
        args.title = title;
        args.visible = false;
        // resizable: thick frame; CLIPCHILDREN avoids flicker while resizing
        args.style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_CLIPCHILDREN;
        args.font = GetFont();
        args.icon = LoadIconW(GetModuleHandleW(nullptr), MAKEINTRESOURCEW(GetAppIconID()));
        CreateCustom(args);
    }
    if (!hwnd) {
        return false;
    }

    auto* vbox = new VBox();
    vbox->alignMain = MainAxisAlign::MainStart;
    vbox->alignCross = CrossAxisAlign::Stretch;

    {
        Edit::CreateArgs args;
        args.parent = hwnd;
        args.font = GetFont();
        args.text = selText;
        args.isMultiLine = true;
        args.withBorder = true;
        args.idealSizeLines = 7;
        // prefer ~40 chars wide; cap so long selection text does not widen the dialog
        args.idealWidthChars = 40;
        args.maxWidthChars = 120;
        args.isRtl = isRtl;
        editSrcText = new Edit();
        editSrcText->Create(args);
        editSrcText->onTextChanged =
            MkMethod0<SelectionTranslateWnd, &SelectionTranslateWnd::UpdateTranslateButtonState>(this);
    }

    // The two text fields come first and the controls that act on them
    // (engine, languages, buttons) follow, so the dialog reads top to bottom.
    // flex so source/result edits absorb extra height when the window is resized
    vbox->AddChild(editSrcText, 1);

    {
        staticResultLabel = NewVirtText({
            .s = _TRA("Translation:"),
            .font = font,
            .isRtl = isRtl,
            .padding = DpiScaledInsets(8, 0, 0, 0),
        });
        staticResultLabel->SetVisibility(Visibility::Collapse);
        vbox->AddChild(staticResultLabel);
    }
    {
        Edit::CreateArgs args;
        args.parent = hwnd;
        args.font = GetFont();
        args.isMultiLine = true;
        args.withBorder = true;
        args.idealSizeLines = 6;
        args.idealWidthChars = 40;
        args.maxWidthChars = 120;
        args.isRtl = isRtl;
        editResult = new Edit();
        editResult->Create(args);
        SendMessageW(editResult->hwnd, EM_SETREADONLY, TRUE, 0);
        editResult->SetVisibility(Visibility::Collapse);
        editResult->SetInsetsPt(4, 0, 0, 0);
        vbox->AddChild(editResult, 1);
    }

    {
        auto* engineRow = new HBox();
        engineRow->alignMain = MainAxisAlign::MainStart;
        engineRow->alignCross = CrossAxisAlign::CrossCenter;
        staticPrompt = NewVirtText({.s = _TRA("Translate with"), .font = font, .isRtl = isRtl});
        engineRow->AddChild(staticPrompt);
        {
            DropDown::CreateArgs args;
            args.parent = hwnd;
            args.font = GetFont();
            args.isRtl = isRtl;
            dropEngine = new DropDown();
            dropEngine->Create(args);
            PopulateEngineDropDown(dropEngine, engine);
            dropEngine->onSelectionChanged =
                MkMethod0<SelectionTranslateWnd, &SelectionTranslateWnd::UpdateTranslateButtonState>(this);
            dropEngine->SetInsetsPt(0, 0, 0, 4);
            engineRow->AddChild(dropEngine, 1);
        }
        vbox->AddChild(new Padding(engineRow, DpiScaledInsets(8, 0, 0, 0)));
    }

    {
        auto* langRow = new HBox();
        langRow->alignMain = MainAxisAlign::MainStart;
        langRow->alignCross = CrossAxisAlign::CrossCenter;

        staticFromLabel = NewVirtText({.s = _TRA("From:"), .font = font, .isRtl = isRtl});
        langRow->AddChild(staticFromLabel);
        {
            DropDown::CreateArgs args;
            args.parent = hwnd;
            args.font = GetFont();
            args.isEditable = true;
            args.isRtl = isRtl;
            dropSrcLang = new DropDown();
            dropSrcLang->Create(args);
            PopulateLanguageDropDown(dropSrcLang, DefaultSourceLanguageTemp(), true);
            dropSrcLang->onTextChanged =
                MkMethod0<SelectionTranslateWnd, &SelectionTranslateWnd::UpdateTranslateButtonState>(this);
            dropSrcLang->onSelectionChanged =
                MkMethod0<SelectionTranslateWnd, &SelectionTranslateWnd::UpdateTranslateButtonState>(this);
            dropSrcLang->SetInsetsPt(0, 0, 0, 4);
            langRow->AddChild(dropSrcLang, 1);
        }
        staticToLabel = NewVirtText({
            .s = _TRA("To:"),
            .font = font,
            .isRtl = isRtl,
            .padding = DpiScaledInsets(0, 0, 0, 4),
        });
        langRow->AddChild(staticToLabel);
        {
            DropDown::CreateArgs args;
            args.parent = hwnd;
            args.font = GetFont();
            args.isEditable = true;
            args.isRtl = isRtl;
            dropDstLang = new DropDown();
            dropDstLang->Create(args);
            PopulateLanguageDropDown(dropDstLang, DefaultDestinationLanguageTemp(), false);
            dropDstLang->onTextChanged =
                MkMethod0<SelectionTranslateWnd, &SelectionTranslateWnd::UpdateTranslateButtonState>(this);
            dropDstLang->onSelectionChanged =
                MkMethod0<SelectionTranslateWnd, &SelectionTranslateWnd::UpdateTranslateButtonState>(this);
            langRow->AddChild(dropDstLang, 1);
        }
        vbox->AddChild(new Padding(langRow, DpiScaledInsets(8, 0, 0, 0)));
    }

    {
        auto* btnRow = new HBox();
        btnRow->alignMain = MainAxisAlign::MainEnd;
        btnRow->alignCross = CrossAxisAlign::CrossCenter;
        btnRow->gap = font->averageCharWidth;

        btnClose = NewButton(_TRA("Close"), false);
        btnClose->onClick =
            MkMethod1<SelectionTranslateWnd, VirtMouseEvent*, &SelectionTranslateWnd::OnCloseClicked>(this);
        btnRow->AddChild(btnClose);

        btnTranslate = NewButton(_TRA("Translate"), true);
        btnTranslate->onClick =
            MkMethod1<SelectionTranslateWnd, VirtMouseEvent*, &SelectionTranslateWnd::StartTranslation>(this);
        btnTranslate->padding = DpiScaledInsets(0, 4, 0, 4);
        btnRow->AddChild(btnTranslate);
        vbox->AddChild(new Padding(btnRow, DpiScaledInsets(8, 0, 0, 0)));
    }

    layout = new Padding(vbox, DpiScaledInsets(12, 12));
    Relayout(true);
    UpdateTheme();
    UpdateTranslateButtonState();
    SetIsVisible(true);
    EditSetFocus(editSrcText);
    return true;
}

void ShowSelectionTranslateDialog(WindowTab* tab, TranslateEngine engineIn) {
    if (!tab || !tab->win || !tab->selectionOnPage) {
        return;
    }
    if (!HasPermission(Perm::CopySelection)) {
        return;
    }
    CloseTranslatePopupForTab(tab);
    TranslateEngine engine = ResolveEngine(engineIn);
    if (gSelectionTranslateWnd) {
        if (gSelectionTranslateWnd->hwnd && IsWindow(gSelectionTranslateWnd->hwnd)) {
            HwndSetFocus(gSelectionTranslateWnd->hwnd);
            return;
        }
        TeardownSelectionTranslateWnd();
    }

    bool isTextOnlySelection = false;
    TempStr selText = GetSelectedTextTemp(tab, StrL("\n"), isTextOnlySelection);
    if (str::IsEmptyOrWhiteSpace(selText)) {
        return;
    }

    HWND hwndOwner = tab->win->hwndFrame;
    EnableWindow(hwndOwner, FALSE);

    auto* wnd = new SelectionTranslateWnd();
    wnd->hwndOwner = hwndOwner;
    wnd->engine = engine;
    wnd->SetFont(GetAppFont());
    wnd->closeOnEsc = true;
    wnd->closeOnCtrlW = true;
    wnd->onClose = MkFunc1Void<WindowBase::CloseEvent*>(OnSelectionTranslateClose);
    wnd->onDestroy = MkFunc1Void<WindowBase::DestroyEvent*>(OnSelectionTranslateDestroy);
    wnd->onGetMinMaxInfo =
        MkMethod1<SelectionTranslateWnd, WindowBase::GetMinMaxInfoEvent*, &SelectionTranslateWnd::OnGetMinMaxInfo>(wnd);
    wnd->onDpiChanged =
        MkMethod1<SelectionTranslateWnd, WindowBase::DpiChangedEvent*, &SelectionTranslateWnd::OnDpiChanged>(wnd);
    Str title = _TRA("Translate");
    if (!wnd->Create(hwndOwner, selText, title)) {
        EnableWindow(hwndOwner, TRUE);
        delete wnd;
        return;
    }

    gSelectionTranslateWnd = wnd;
    HwndToForeground(wnd->hwnd);
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
};

enum class PopupResult {
    Failure,
    Success,
};

enum class PopupStart {
    Worker,
    NoWorker,
};

struct SelectionTranslatePopupWnd : WindowBase {
    MainWindow* win = nullptr;
    WindowTab* tab = nullptr;
    Vec<SelectionOnPage> selection;
    HWND hwndOwner = nullptr;
    TranslateEngine engine = TranslateEngine::Default;
    AIChatBackend backend = AIChatBackend::Grok;
    SelectionTranslatePopupState state = SelectionTranslatePopupState::Hidden;
    u64 requestId = 0;
    bool selectionWasCleared = false;
    bool canConfigure = false;
    bool closing = false;
    bool registeredOnWindowMoved = false;
    Str message;
    Str sourceLang;
    Str destinationLang;
    VirtButton* btnEngine = nullptr;
    VirtText* target = nullptr;
    VirtText* status = nullptr;
    Edit* result = nullptr;
    VirtButton* btnCopy = nullptr;
    VirtButton* btnConfigure = nullptr;
    VirtButton* btnClose = nullptr;
    Func1List<MainWindow*> onWindowMoved;

    ~SelectionTranslatePopupWnd() override;

    bool Create(WindowTab* tab, TranslateEngine engine, Str sourceLang, Str destinationLang);
    void Relayout();
    void Place(PopupShow show);
    void SetState(SelectionTranslatePopupState state, Str text, PopupAction action);
    void Start(Str text, PopupStart start);
    void SwitchEngine(TranslateEngine engine, PopupStart start);
    void OnDone(PopupResult result, Str text);
    void OnCopy(VirtMouseEvent*);
    void OnEngine(VirtMouseEvent*);
    void OnConfigure(VirtMouseEvent*);
    void OnClose(VirtMouseEvent*);
    void OnDpiChanged(WindowBase::DpiChangedEvent* ev);
};

struct SelectionTranslatePopupTaskData {
    HWND hwnd = nullptr;
    AIChatBackend backend = AIChatBackend::Grok;
    u64 requestId = 0;
    Str sourceLang;
    Str destinationLang;
    Str text;

    ~SelectionTranslatePopupTaskData() {
        str::Free(sourceLang);
        str::Free(destinationLang);
        str::Free(text);
    }
};

struct SelectionTranslatePopupDoneData {
    HWND hwnd = nullptr;
    u64 requestId = 0;
    PopupResult result = PopupResult::Failure;
    Str text;

    ~SelectionTranslatePopupDoneData() { str::Free(text); }
};

static Vec<SelectionTranslatePopupWnd*> gSelectionTranslatePopups;
static u64 gNextTranslatePopupRequestId = 0;
static constexpr UINT kTranslateEngineMenuFirst = 1;
static constexpr UINT kTranslateEngineMenuConfigure = 100;

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

static Str TranslatePopupEngineName(TranslateEngine engine) {
    if (EngineIsAI(engine)) {
        return EngineDisplayName(engine);
    }
    return _TRA("Choose Engine");
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

void SelectionTranslatePopupWnd::Relayout() {
    if (!layout) {
        return;
    }
    LayoutAndSizeToContent(layout, 0, 0, hwnd);
    DoLayout(HwndClientRect(hwnd).Size());
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
}

void SelectionTranslatePopupWnd::SetState(SelectionTranslatePopupState newState, Str text, PopupAction action) {
    state = newState;
    canConfigure = action == PopupAction::Configure;
    str::ReplaceWithCopy(&message, text);

    if (btnEngine) {
        btnEngine->SetText(TranslatePopupEngineName(engine));
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

void SelectionTranslatePopupWnd::OnEngine(VirtMouseEvent*) {
    if (!btnEngine || !hwnd) {
        return;
    }

    HMENU menu = CreatePopupMenu();
    if (!menu) {
        return;
    }

    Vec<TranslateEngine> engines;
    for (TranslateEngine candidate : gAllEngines) {
        if (!EngineIsAI(candidate) || !IsEngineAvailable(candidate)) {
            continue;
        }
        VecAppend(engines, candidate);
    }
    for (int i = 0; i < len(engines); i++) {
        UINT flags = MF_STRING;
        if (engines[i] == engine) {
            flags |= MF_CHECKED;
        }
        AppendMenuW(menu, flags, kTranslateEngineMenuFirst + (UINT)i, CWStrTemp(EngineDisplayName(engines[i])));
    }
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, kTranslateEngineMenuConfigure, CWStrTemp(_TRA("Configure...")));

    Rect button = btnEngine->BoundsInWindow();
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
    if (cmd >= kTranslateEngineMenuFirst && cmd < kTranslateEngineMenuFirst + (UINT)len(engines)) {
        popup->SwitchEngine(engines[cmd - kTranslateEngineMenuFirst], PopupStart::Worker);
        return;
    }
    if (cmd == kTranslateEngineMenuConfigure) {
        popup->OnConfigure(nullptr);
    }
}

void SelectionTranslatePopupWnd::OnConfigure(VirtMouseEvent*) {
    WindowTab* selectedTab = tab;
    CloseSelectionTranslatePopup(this, PopupToolbar::LeaveHidden);
    ShowSelectionTranslateDialog(selectedTab, TranslateEngine::Default);
}

void SelectionTranslatePopupWnd::OnClose(VirtMouseEvent*) {
    CloseSelectionTranslatePopup(this, PopupToolbar::Restore);
}

void SelectionTranslatePopupWnd::OnDpiChanged(WindowBase::DpiChangedEvent* ev) {
    SetFont(GetAppFont());
    HwndSetFontForWindowAndItsChildren(hwnd, GetHFont());
    if (btnEngine) {
        btnEngine->textPadding = DpiScaledInsets(2, 6);
    }
    VirtText* virts[] = {btnEngine, target, status, btnCopy, btnConfigure, btnClose};
    for (VirtText* virt : virts) {
        if (virt) {
            virt->font = font;
        }
    }
    Relayout();
    Place(PopupShow::Yes);
    ev->didHandle = true;
}

bool SelectionTranslatePopupWnd::Create(WindowTab* selectedTab, TranslateEngine selectedEngine, Str srcLang,
                                        Str dstLang) {
    if (!selectedTab || !selectedTab->win || !selectedTab->selectionOnPage) {
        return false;
    }
    win = selectedTab->win;
    tab = selectedTab;
    selection = *selectedTab->selectionOnPage;
    hwndOwner = win->hwndFrame;
    engine = selectedEngine;
    sourceLang = str::Dup(srcLang);
    destinationLang = str::Dup(dstLang);
    SetFont(GetAppFont());
    closeOnEsc = true;
    onClose = MkFunc1Void<WindowBase::CloseEvent*>(OnSelectionTranslatePopupClose);
    onDestroy = MkFunc1Void<WindowBase::DestroyEvent*>(OnSelectionTranslatePopupDestroy);
    onDpiChanged =
        MkMethod1<SelectionTranslatePopupWnd, WindowBase::DpiChangedEvent*, &SelectionTranslatePopupWnd::OnDpiChanged>(
            this);

    CreateCustomArgs args;
    args.owner = hwndOwner;
    args.title = _TRA("Translate");
    args.visible = false;
    args.style = WS_POPUP | WS_BORDER | WS_CLIPCHILDREN;
    args.exStyle = WS_EX_TOOLWINDOW;
    args.font = font;
    args.pos = Rect(0, 0, DpiScale(360), DpiScale(180));
    args.isRtl = IsUIRtl();
    CreateCustom(args);
    if (!hwnd) {
        return false;
    }

    auto* vbox = new VBox();
    vbox->alignMain = MainAxisAlign::MainStart;
    vbox->alignCross = CrossAxisAlign::Stretch;

    auto* header = new HBox();
    header->alignCross = CrossAxisAlign::CrossCenter;
    header->gap = DpiScale(4);
    btnEngine = NewThemedButton(hwnd, TranslatePopupEngineName(engine), font, false);
    btnEngine->textPadding = DpiScaledInsets(2, 6);
    btnEngine->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnEngine>(this);
    header->AddChild(btnEngine);
    target = NewVirtText({.s = fmt("-> %s", destinationLang), .font = font, .isRtl = IsUIRtl(), .ellipsis = true});
    header->AddChild(target);
    vbox->AddChild(header);

    status = NewVirtText({.font = font, .isRtl = IsUIRtl(), .padding = DpiScaledInsets(8, 0, 0, 0)});
    vbox->AddChild(status);

    Edit::CreateArgs resultArgs;
    resultArgs.parent = hwnd;
    resultArgs.font = GetFont();
    resultArgs.isMultiLine = true;
    resultArgs.withBorder = true;
    resultArgs.idealSizeLines = 8;
    resultArgs.idealWidthChars = 42;
    resultArgs.maxWidthChars = 52;
    resultArgs.isRtl = IsUIRtl();
    result = new Edit();
    result->Create(resultArgs);
    SendMessageW(result->hwnd, EM_SETREADONLY, TRUE, 0);
    vbox->AddChild(new Padding(result, DpiScaledInsets(8, 0, 0, 0)), 1);

    auto* row = new HBox();
    row->alignMain = MainAxisAlign::MainEnd;
    row->alignCross = CrossAxisAlign::CrossCenter;
    row->gap = font->averageCharWidth;
    btnCopy = NewThemedButton(hwnd, _TRA("Copy"), font, false);
    btnCopy->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnCopy>(this);
    row->AddChild(btnCopy);
    btnConfigure = NewThemedButton(hwnd, _TRA("Configure"), font, true);
    btnConfigure->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnConfigure>(this);
    row->AddChild(btnConfigure);
    btnClose = NewThemedButton(hwnd, _TRA("Close"), font, false);
    btnClose->onClick =
        MkMethod1<SelectionTranslatePopupWnd, VirtMouseEvent*, &SelectionTranslatePopupWnd::OnClose>(this);
    row->AddChild(btnClose);
    vbox->AddChild(new Padding(row, DpiScaledInsets(8, 0, 0, 0)));

    layout = new Padding(vbox, DpiScaledInsets(12, 12));
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
        popup->OnDone(done->result, done->text);
        return;
    }
}

static void SelectionTranslatePopupThread(SelectionTranslatePopupTaskData* data) {
    AutoDelete del(data);
    Str text;
    bool ok = RunTranslation(data->backend, data->sourceLang, data->destinationLang, data->text, text);
    if (!ok && len(text) == 0) {
        text = str::Dup(_TRA("Translation failed."));
    }

    auto* done = new SelectionTranslatePopupDoneData();
    done->hwnd = data->hwnd;
    done->requestId = data->requestId;
    done->result = ok ? PopupResult::Success : PopupResult::Failure;
    done->text = text;
    uitask::Post(MkFunc0(OnSelectionTranslatePopupDone, done), "SelectionTranslatePopupDone");
}

void SelectionTranslatePopupWnd::Start(Str text, PopupStart start) {
    requestId = ++gNextTranslatePopupRequestId;
    SetState(SelectionTranslatePopupState::Loading, {}, PopupAction::None);
    if (start == PopupStart::NoWorker) {
        return;
    }

    auto* task = new SelectionTranslatePopupTaskData();
    task->hwnd = hwnd;
    task->backend = backend;
    task->requestId = requestId;
    task->sourceLang = str::Dup(sourceLang);
    task->destinationLang = str::Dup(destinationLang);
    task->text = str::Dup(text);
    RunAsync(MkFunc0(SelectionTranslatePopupThread, task), StrL("SelectionTranslatePopup"));
}

void SelectionTranslatePopupWnd::SwitchEngine(TranslateEngine newEngine, PopupStart start) {
    if (!EngineIsAI(newEngine) || (start == PopupStart::Worker && !IsEngineAvailable(newEngine))) {
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
    if (newEngine == engine) {
        return;
    }

    engine = newEngine;
    backend = BackendFromEngine(engine);
    MaybeSaveQuickTranslateEngine(engine);
    Start(text, start);
}

void SelectionTranslatePopupWnd::OnDone(PopupResult result, Str text) {
    bool ok = result == PopupResult::Success;
    Str display = ok ? text : FormatTranslationErrorForDisplayTemp(backend, text);
    SetState(ok ? SelectionTranslatePopupState::Result : SelectionTranslatePopupState::Error, display,
             PopupAction::None);
}

static TranslateEngine ResolveQuickTranslateEngine() {
    if (!gSettings) {
        return TranslateEngine::Default;
    }
    TranslateEngine engine = EngineFromName(gSettings->translateEngine);
    if (!EngineIsAI(engine) || !IsEngineAvailable(engine)) {
        return TranslateEngine::Default;
    }
    return engine;
}

void ShowSelectionTranslatePopup(WindowTab* tab) {
    if (!tab || !tab->win || !tab->selectionOnPage || !HasPermission(Perm::CopySelection)) {
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
    TranslateEngine engine = ResolveQuickTranslateEngine();
    auto* popup = new SelectionTranslatePopupWnd();
    if (!popup->Create(tab, engine, sourceLang, destinationLang)) {
        delete popup;
        return;
    }
    VecAppend(gSelectionTranslatePopups, popup);
    HideSelectionToolbar(tab->win);
    if (engine == TranslateEngine::Default) {
        popup->SetState(SelectionTranslatePopupState::Error, _TRA("Configure an installed AI CLI to translate here."),
                        PopupAction::Configure);
        return;
    }
    popup->backend = BackendFromEngine(engine);
    popup->Start(text, PopupStart::Worker);
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
            return finish(StrL("state=Hidden\nvisible=0\n"), 0);
        }
        str::Builder out;
        Rect rect = popup->hwnd ? HwndWindowRect(popup->hwnd) : Rect();
        out.Append(fmt("state=%s\nvisible=%d\nconfigure=%d\ncopy=%d\nplaced=%d,%d,%d,%d\n",
                       Str(TranslatePopupStateName(popup->state)), HwndIsVisible(popup->hwnd) ? 1 : 0,
                       popup->canConfigure ? 1 : 0, popup->state == SelectionTranslatePopupState::Result ? 1 : 0,
                       rect.x, rect.y, rect.dx, rect.dy));
        Str engineName = popup->engine == TranslateEngine::Default ? StrL("Default") : EngineDisplayName(popup->engine);
        Str persisted = gSettings ? gSettings->translateEngine : Str{};
        out.Append(fmt("switcher=%d\nengine=%s\nprovider=%s\ntarget=%s\npersisted=%s\nrequest=%llu\n",
                       popup->btnEngine ? 1 : 0, engineName, TranslatePopupEngineName(popup->engine),
                       popup->destinationLang, persisted, popup->requestId));
        if (popup->state == SelectionTranslatePopupState::Result) {
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
    if (str::EqI(action, StrL("start"))) {
        if (popup) {
            CloseSelectionTranslatePopup(popup, PopupToolbar::LeaveHidden);
        }
        auto* testPopup = new SelectionTranslatePopupWnd();
        if (!testPopup->Create(win->CurrentTab(), TranslateEngine::Codex, StrL("Auto"), StrL("English"))) {
            delete testPopup;
            return finish(StrL("ERROR create"), 1);
        }
        VecAppend(gSelectionTranslatePopups, testPopup);
        HideSelectionToolbar(win);
        testPopup->backend = BackendFromEngine(testPopup->engine);
        testPopup->Start({}, PopupStart::NoWorker);
        return SelectionTranslatePopupTestTemp(StrL("dump"), {}, exitCode);
    }
    if (!popup) {
        return finish(StrL("ERROR no-popup"), 1);
    }
    if (str::EqI(action, StrL("result"))) {
        popup->OnDone(PopupResult::Success, value);
    } else if (str::EqI(action, StrL("stale"))) {
        auto* done = new SelectionTranslatePopupDoneData();
        done->hwnd = popup->hwnd;
        done->requestId = popup->requestId - 1;
        done->result = PopupResult::Success;
        done->text = str::Dup(value);
        OnSelectionTranslatePopupDone(done);
    } else if (str::EqI(action, StrL("switch"))) {
        TranslateEngine engine = EngineFromName(value);
        if (!EngineIsAI(engine)) {
            return finish(StrL("ERROR invalid-engine"), 1);
        }
        popup->SwitchEngine(engine, PopupStart::NoWorker);
    } else {
        return finish(StrL("ERROR unknown-action"), 1);
    }
    return SelectionTranslatePopupTestTemp(StrL("dump"), {}, exitCode);
}
