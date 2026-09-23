/* Copyright 2026 the SumatraPDF project authors (see AUTHORS file).
   License: GPLv3 */

enum class TranslationProviderId : u8 {
    OpenAICompatible,
    GoogleCloud,
    Microsoft,
    None,
};

struct TranslationProviderInfo {
    TranslationProviderId id;
    Str name;
    bool needsBaseUrl;
    bool needsModel;
    bool hasOptionalRegion;
};

struct TranslationSettings {
    TranslationProviderId provider = TranslationProviderId::None;
    Str openAIBaseUrl;
    Str openAIModel;
    Str openAIKey;
    Str googleKey;
    Str microsoftEndpoint;
    Str microsoftKey;
    Str microsoftRegion;
};

struct TranslationRequest {
    Str sourceLanguage;
    Str targetLanguage;
    Str text;
};

constexpr DWORD kTranslationRequestTimeoutMs = 15 * 1000;
constexpr int kTranslationMaxResponseBytes = 32 * 1024;

struct TranslationRequestOptions {
    DWORD timeoutMs = kTranslationRequestTimeoutMs;
    int maxResponseBytes = kTranslationMaxResponseBytes;
};

enum class TranslationErrorKind : u8 {
    None,
    IncompleteConfig,
    InvalidInput,
    InvalidResponse,
    HttpStatus,
    ResponseTooLarge,
    Transport,
};

struct TranslationResult {
    bool ok = false;
    TranslationErrorKind errorKind = TranslationErrorKind::None;
    Str text;
    Str error;
    DWORD httpStatusCode = (DWORD)-1;
    DWORD winError = (DWORD)-1;

    TranslationResult() = default;
    ~TranslationResult();
};

constexpr int kTranslationProviderCount = 3;

const TranslationProviderInfo* TranslationProviders();
TranslationProviderId TranslationProviderFromName(Str name);
Str TranslationProviderName(TranslationProviderId provider);
void TranslationSettingsFromGlobal(TranslationSettings* settingsOut);
bool TranslationProviderIsConfigured(const TranslationSettings& settings);
TempStr TranslationConfigErrorTemp(const TranslationSettings& settings);
TempStr TranslationLanguageCodeTemp(TranslationProviderId provider, Str language);
bool TranslationSourceIsAuto(Str language);
TempStr NormalizeOpenAIBaseUrlTemp(Str url);
void TranslateText(const TranslationSettings& settings, const TranslationRequest& request, TranslationResult* resultOut,
                   const TranslationRequestOptions& options = {});
void TranslationSetTestEndpoint(TranslationProviderId provider, Str endpoint);
