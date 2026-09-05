/* Copyright 2026 the SumatraPDF project authors (see AUTHORS file).
   License: GPLv3 */

#include "base/Base.h"
#include "base/Http.h"
#include "base/JsonParser.h"

#include "Settings.h"
#include "AppSettings.h"
#include "TranslationService.h"

constexpr int kTranslationMaxTextBytes = 32 * 1024;
constexpr int kTranslationLanguageLabelOffset = 0;
constexpr int kTranslationGoogleCodeOffset = 1;
constexpr int kTranslationMicrosoftCodeOffset = 2;
constexpr int kTranslationLanguageCodeFields = 3;

static const TranslationProviderInfo gProviders[] = {
    {TranslationProviderId::OpenAICompatible, StrL("OpenAI-compatible"), true, true, false},
    {TranslationProviderId::GoogleCloud, StrL("Google Cloud Translation"), false, false, false},
    {TranslationProviderId::Microsoft, StrL("Microsoft Translator"), true, false, true},
};

// Language labels are shared by the provider configuration and popup. Google
// and Microsoft use distinct Chinese language tags; OpenAI receives labels.
static const char* gLanguageCodes =
    "English\0en\0en\0Chinese (Simplified)\0zh-CN\0zh-Hans\0Chinese (Traditional)\0zh-TW\0zh-Hant\0"
    "Spanish\0es\0es\0Arabic\0ar\0ar\0Hindi\0hi\0hi\0Portuguese\0pt\0pt\0Bengali\0bn\0bn\0"
    "Russian\0ru\0ru\0Japanese\0ja\0ja\0Punjabi\0pa\0pa\0German\0de\0de\0French\0fr\0fr\0"
    "Korean\0ko\0ko\0Turkish\0tr\0tr\0Vietnamese\0vi\0vi\0Italian\0it\0it\0Polish\0pl\0pl\0"
    "Ukrainian\0uk\0uk\0Dutch\0nl\0nl\0Thai\0th\0th\0Indonesian\0id\0id\0Czech\0cs\0cs\0"
    "Swedish\0sv\0sv\0Romanian\0ro\0ro\0Greek\0el\0el\0Hebrew\0he\0he\0Danish\0da\0da\0"
    "Finnish\0fi\0fi\0Norwegian\0no\0nb\0Hungarian\0hu\0hu\0Slovak\0sk\0sk\0\0";

static Str gTestEndpoints[kTranslationProviderCount];

struct TranslationInputCopy {
    TranslationSettings settings;
    TranslationRequest request;

    ~TranslationInputCopy() {
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

TranslationResult::~TranslationResult() {
    str::Free(text);
    str::Free(error);
}

const TranslationProviderInfo* TranslationProviders() {
    return gProviders;
}

TranslationProviderId TranslationProviderFromName(Str name) {
    TempStr normalized = str::DupTemp(name);
    str::TrimWSInPlace(normalized, str::TrimOpt::Both);
    if (str::EqI(normalized, StrL("OpenAI-compatible"))) {
        return TranslationProviderId::OpenAICompatible;
    }
    if (str::EqI(normalized, StrL("Google Cloud Translation"))) {
        return TranslationProviderId::GoogleCloud;
    }
    if (str::EqI(normalized, StrL("Microsoft Translator"))) {
        return TranslationProviderId::Microsoft;
    }
    return TranslationProviderId::None;
}

Str TranslationProviderName(TranslationProviderId provider) {
    for (const TranslationProviderInfo& info : gProviders) {
        if (info.id == provider) {
            return info.name;
        }
    }
    return StrL("Translation provider");
}

void TranslationSettingsFromGlobal(TranslationSettings* settingsOut) {
    *settingsOut = {};
    if (!gSettings) {
        return;
    }
    settingsOut->provider = TranslationProviderFromName(gSettings->translationProvider);
    settingsOut->openAIBaseUrl = gSettings->translationOpenAIBaseUrl;
    settingsOut->openAIModel = gSettings->translationOpenAIModel;
    settingsOut->openAIKey = gSettings->translationOpenAIKey;
    settingsOut->googleKey = gSettings->translationGoogleKey;
    settingsOut->microsoftEndpoint = gSettings->translationMicrosoftEndpoint;
    settingsOut->microsoftKey = gSettings->translationMicrosoftKey;
    settingsOut->microsoftRegion = gSettings->translationMicrosoftRegion;
}

static bool HasValue(Str value) {
    return !str::IsEmptyOrWhiteSpace(value);
}

bool TranslationProviderIsConfigured(const TranslationSettings& settings) {
    if (settings.provider == TranslationProviderId::OpenAICompatible) {
        return HasValue(settings.openAIBaseUrl) && HasValue(settings.openAIModel) && HasValue(settings.openAIKey);
    }
    if (settings.provider == TranslationProviderId::GoogleCloud) {
        return HasValue(settings.googleKey);
    }
    if (settings.provider == TranslationProviderId::Microsoft) {
        return HasValue(settings.microsoftEndpoint) && HasValue(settings.microsoftKey);
    }
    return false;
}

TempStr TranslationConfigErrorTemp(const TranslationSettings& settings) {
    if (settings.provider == TranslationProviderId::None) {
        return str::DupTemp(StrL("Choose a translation provider."));
    }
    if (settings.provider == TranslationProviderId::OpenAICompatible) {
        if (!HasValue(settings.openAIBaseUrl)) {
            return str::DupTemp(StrL("OpenAI-compatible requires a Base URL."));
        }
        if (!HasValue(settings.openAIModel)) {
            return str::DupTemp(StrL("OpenAI-compatible requires a Model."));
        }
        if (!HasValue(settings.openAIKey)) {
            return str::DupTemp(StrL("OpenAI-compatible requires an API key."));
        }
    }
    if (settings.provider == TranslationProviderId::GoogleCloud && !HasValue(settings.googleKey)) {
        return str::DupTemp(StrL("Google Cloud Translation requires an API key."));
    }
    if (settings.provider == TranslationProviderId::Microsoft) {
        if (!HasValue(settings.microsoftEndpoint)) {
            return str::DupTemp(StrL("Microsoft Translator requires an Endpoint."));
        }
        if (!HasValue(settings.microsoftKey)) {
            return str::DupTemp(StrL("Microsoft Translator requires an API key."));
        }
    }
    return {};
}

Str TranslationLanguageLabel(int index) {
    if (index < 0 || index >= SeqStrCount(gLanguageCodes) / kTranslationLanguageCodeFields) {
        return {};
    }
    return SeqStrByIndex(gLanguageCodes, index * kTranslationLanguageCodeFields + kTranslationLanguageLabelOffset);
}

bool TranslationSourceIsAuto(Str language) {
    if (str::IsEmptyOrWhiteSpace(language)) {
        return true;
    }
    TempStr normalized = str::DupTemp(language);
    str::TrimWSInPlace(normalized, str::TrimOpt::Both);
    return str::EqI(normalized, StrL("Auto"));
}

TempStr TranslationLanguageCodeTemp(TranslationProviderId provider, Str language) {
    if (TranslationSourceIsAuto(language)) {
        return {};
    }
    TempStr normalized = str::DupTemp(language);
    str::TrimWSInPlace(normalized, str::TrimOpt::Both);
    int idx = SeqStrIndexIS(gLanguageCodes, normalized);
    if (idx < 0 || idx % kTranslationLanguageCodeFields != kTranslationLanguageLabelOffset) {
        return {};
    }
    int codeOffset =
        provider == TranslationProviderId::Microsoft ? kTranslationMicrosoftCodeOffset : kTranslationGoogleCodeOffset;
    return SeqStrByIndex(gLanguageCodes, idx + codeOffset);
}

TempStr NormalizeOpenAIBaseUrlTemp(Str url) {
    if (str::IsEmptyOrWhiteSpace(url)) {
        return {};
    }
    TempStr normalized = str::DupTemp(url);
    str::TrimWSInPlace(normalized, str::TrimOpt::Both);
    while (len(normalized) > 0 && normalized.s[len(normalized) - 1] == '/') {
        normalized.len--;
    }
    if (str::EndsWithI(normalized, StrL("/chat/completions"))) {
        normalized.len -= len(StrL("/chat/completions"));
    }
    while (len(normalized) > 0 && normalized.s[len(normalized) - 1] == '/') {
        normalized.len--;
    }
    return normalized;
}

void TranslationSetTestEndpoint(TranslationProviderId provider, Str endpoint) {
    // The debug-control test routes only Google through a local fixture.
    int idx = (int)provider;
    if (idx < 0 || idx >= kTranslationProviderCount) {
        return;
    }
    str::ReplacePtr(&gTestEndpoints[idx], str::Dup(endpoint));
}

struct ParsedTranslation {
    Str value;
};

static void OnOpenAIValue(ParsedTranslation* parsed, json::Value* value) {
    if (value->type == json::Type::String &&
        json::PathMatch(value->path, StrL("/choices"), StrL("i0"), StrL("/message"), StrL("/content"))) {
        str::ReplacePtr(&parsed->value, str::Dup(value->value));
        value->stop = true;
    }
}

static void OnGoogleValue(ParsedTranslation* parsed, json::Value* value) {
    if (value->type == json::Type::String &&
        json::PathMatch(value->path, StrL("/data"), StrL("/translations"), StrL("i0"), StrL("/translatedText"))) {
        str::ReplacePtr(&parsed->value, str::Dup(value->value));
        value->stop = true;
    }
}

static void OnMicrosoftValue(ParsedTranslation* parsed, json::Value* value) {
    if (value->type == json::Type::String &&
        json::PathMatch(value->path, StrL("i0"), StrL("/translations"), StrL("i0"), StrL("/text"))) {
        str::ReplacePtr(&parsed->value, str::Dup(value->value));
        value->stop = true;
    }
}

static bool ParseResponse(TranslationProviderId provider, Str data, Str* textOut) {
    ParsedTranslation parsed;
    Func1<json::Value*> fn;
    if (provider == TranslationProviderId::OpenAICompatible) {
        fn = MkFunc1(OnOpenAIValue, &parsed);
    } else if (provider == TranslationProviderId::GoogleCloud) {
        fn = MkFunc1(OnGoogleValue, &parsed);
    } else {
        fn = MkFunc1(OnMicrosoftValue, &parsed);
    }
    bool ok = json::Parse(data, fn) && !str::IsEmptyOrWhiteSpace(parsed.value);
    if (ok) {
        str::ReplacePtr(textOut, parsed.value);
        parsed.value = {};
    }
    str::Free(parsed.value);
    return ok;
}

static TempStr BuildOpenAIPromptTemp(Str sourceLanguage, Str targetLanguage) {
    if (TranslationSourceIsAuto(sourceLanguage)) {
        return fmt("Detect the source language and translate the user's text to %s. Return only the translation.",
                   targetLanguage);
    }
    return fmt("Translate the user's text from %s to %s. Return only the translation.", sourceLanguage, targetLanguage);
}

static bool BuildRequest(const TranslationSettings& settings, const TranslationRequest& request, Str* urlOut,
                         Str* headersOut, Str* bodyOut) {
    TranslationProviderId provider = settings.provider;
    TempStr sourceCode = TranslationLanguageCodeTemp(provider, request.sourceLanguage);
    TempStr targetCode = TranslationLanguageCodeTemp(provider, request.targetLanguage);
    if (!TranslationSourceIsAuto(request.sourceLanguage) && !sourceCode) {
        return false;
    }
    if (!targetCode) {
        return false;
    }

    if (provider == TranslationProviderId::OpenAICompatible) {
        TempStr baseUrl = NormalizeOpenAIBaseUrlTemp(settings.openAIBaseUrl);
        if (!baseUrl) {
            return false;
        }
        TempStr prompt = BuildOpenAIPromptTemp(request.sourceLanguage, request.targetLanguage);
        *urlOut = str::Dup(fmt("%s/chat/completions", baseUrl));
        *headersOut = str::Dup(fmt("Authorization: Bearer %s", settings.openAIKey));
        *bodyOut = str::Dup(fmt(
            "{\"model\":\"%s\",\"stream\":false,\"messages\":[{\"role\":\"system\",\"content\":\"%s\"},{\"role\":"
            "\"user\",\"content\":\"%s\"}]}",
            json::EscapeStrTemp(settings.openAIModel), json::EscapeStrTemp(prompt), json::EscapeStrTemp(request.text)));
        return true;
    }

    if (provider == TranslationProviderId::GoogleCloud) {
        Str endpoint = gTestEndpoints[(int)provider];
        if (!endpoint) {
            endpoint = StrL("https://translation.googleapis.com/language/translate/v2");
        }
        bool didTruncate = false;
        TempStr key = URLEncodeMayTruncateTemp(settings.googleKey, 0, &didTruncate);
        if (didTruncate) {
            return false;
        }
        *urlOut = str::Dup(fmt("%s?key=%s", endpoint, key));
        if (TranslationSourceIsAuto(request.sourceLanguage)) {
            *bodyOut = str::Dup(fmt("{\"q\":\"%s\",\"target\":\"%s\",\"format\":\"text\"}",
                                    json::EscapeStrTemp(request.text), targetCode));
        } else {
            *bodyOut = str::Dup(fmt("{\"q\":\"%s\",\"source\":\"%s\",\"target\":\"%s\",\"format\":\"text\"}",
                                    json::EscapeStrTemp(request.text), sourceCode, targetCode));
        }
        return true;
    }

    TempStr endpoint = str::DupTemp(settings.microsoftEndpoint);
    str::TrimWSInPlace(endpoint, str::TrimOpt::Both);
    while (len(endpoint) > 0 && endpoint.s[len(endpoint) - 1] == '/') {
        endpoint.len--;
    }
    *urlOut = str::Dup(fmt("%s/translate?api-version=3.0&to=%s", endpoint, targetCode));
    if (!TranslationSourceIsAuto(request.sourceLanguage)) {
        str::ReplacePtr(urlOut, str::Dup(fmt("%s&from=%s", *urlOut, sourceCode)));
    }
    str::Builder headers;
    headers.Append(fmt("Ocp-Apim-Subscription-Key: %s", settings.microsoftKey));
    if (HasValue(settings.microsoftRegion)) {
        headers.Append(fmt("\nOcp-Apim-Subscription-Region: %s", settings.microsoftRegion));
    }
    *headersOut = str::Dup(ToStr(headers));
    *bodyOut = str::Dup(fmt("[{\"Text\":\"%s\"}]", json::EscapeStrTemp(request.text)));
    return true;
}

static void SetError(TranslationResult* result, TranslationErrorKind errorKind, Str error, DWORD httpStatus = (DWORD)-1,
                     DWORD winError = (DWORD)-1) {
    result->ok = false;
    result->errorKind = errorKind;
    result->httpStatusCode = httpStatus;
    result->winError = winError;
    str::ReplacePtr(&result->error, str::Dup(error));
}

static void CopyInput(const TranslationSettings& settings, const TranslationRequest& request,
                      TranslationInputCopy* copy) {
    copy->settings.provider = settings.provider;
    copy->settings.openAIBaseUrl = str::Dup(settings.openAIBaseUrl);
    copy->settings.openAIModel = str::Dup(settings.openAIModel);
    copy->settings.openAIKey = str::Dup(settings.openAIKey);
    copy->settings.googleKey = str::Dup(settings.googleKey);
    copy->settings.microsoftEndpoint = str::Dup(settings.microsoftEndpoint);
    copy->settings.microsoftKey = str::Dup(settings.microsoftKey);
    copy->settings.microsoftRegion = str::Dup(settings.microsoftRegion);
    copy->request.sourceLanguage = str::Dup(request.sourceLanguage);
    copy->request.targetLanguage = str::Dup(request.targetLanguage);
    copy->request.text = str::Dup(request.text);
}

void TranslateText(const TranslationSettings& settings, const TranslationRequest& request, TranslationResult* resultOut,
                   const TranslationRequestOptions& options) {
    str::Free(resultOut->text);
    str::Free(resultOut->error);
    *resultOut = {};
    if (!TranslationProviderIsConfigured(settings)) {
        SetError(resultOut, TranslationErrorKind::IncompleteConfig, TranslationConfigErrorTemp(settings));
        return;
    }
    if (str::IsEmptyOrWhiteSpace(request.text) || len(request.text) > kTranslationMaxTextBytes) {
        SetError(resultOut, TranslationErrorKind::InvalidInput, StrL("Translation text is empty or too long."));
        return;
    }

    TranslationInputCopy copy;
    CopyInput(settings, request, &copy);
    Str url, headers, body;
    bool built = BuildRequest(copy.settings, copy.request, &url, &headers, &body);
    if (!built) {
        SetError(resultOut, TranslationErrorKind::InvalidInput, StrL("Translation language or endpoint is invalid."));
        str::Free(url);
        str::Free(headers);
        str::Free(body);
        return;
    }

    HttpPostOptions httpOptions;
    httpOptions.timeoutMs = options.timeoutMs;
    httpOptions.maxResponseBytes = options.maxResponseBytes;
    HttpRsp response;
    bool ok = HttpPostUrl(url, StrL("application/json; charset=utf-8"), headers, body, &response, httpOptions);
    str::Free(url);
    str::Free(headers);
    str::Free(body);

    resultOut->httpStatusCode = response.httpStatusCode;
    resultOut->winError = response.error;
    if (!ok) {
        if (response.error == ERROR_FILE_TOO_LARGE) {
            SetError(resultOut, TranslationErrorKind::ResponseTooLarge, StrL("Translation response is too large."),
                     response.httpStatusCode, response.error);
        } else if (response.error != ERROR_SUCCESS) {
            SetError(resultOut, TranslationErrorKind::Transport, StrL("Translation request failed."),
                     response.httpStatusCode, response.error);
        } else {
            SetError(resultOut, TranslationErrorKind::HttpStatus, StrL("Translation provider rejected the request."),
                     response.httpStatusCode, response.error);
        }
        return;
    }

    Str text;
    if (!ParseResponse(copy.settings.provider, ToStr(response.data), &text)) {
        SetError(resultOut, TranslationErrorKind::InvalidResponse,
                 StrL("Translation provider returned an invalid response."), response.httpStatusCode, response.error);
        return;
    }
    resultOut->ok = true;
    resultOut->text = text;
}
